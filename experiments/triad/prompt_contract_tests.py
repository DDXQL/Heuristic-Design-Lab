#!/usr/bin/env python3
"""Prompt/unchanged-parser audit only. Never call a generated H or a solver."""
import ast
from dataclasses import asdict
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT),str(ROOT/'deploy/eoh-baseline')]
from experiments.triad import runtime,problems,evaluation,assets,entry
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport
from heuristic_design.problems import routing_fixtures
import eoh_gap
import prompt_contract as contract
PUBLIC='923781f05686f1899c24fd7899fb3bc6b1df1562'
OLD=Path('/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/reports/triad-package-20261113/fetch-20261114-234303-78d966/result/runs/fjsp-priority-1f6982e4fd45/fjsp-priority-1f6982e4fd45-fjsp-eoh-seed-501')
OUT=ROOT/'reports/eoh-prompt-contract-20261115'


def deny(*a,**k):raise AssertionError('OFFLINE: credential, transport, network, H execution or solver forbidden')


def rejects(fn):
    try:fn()
    except (ValueError,TypeError,SyntaxError) as x:return str(x)
    raise AssertionError('expected unchanged parser/admission refusal')


def main():
    checks=[];prompts={};cases=[]
    with tempfile.TemporaryDirectory(prefix='prompt-v2-offline-') as folder,patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(StrictNonstreamTransport,'__init__',deny),patch.object(entry,'key',deny),patch.object(problems,'compile_h',deny),patch.object(problems,'solve_row',deny),patch.object(problems,'solve_obp',deny),patch.object(evaluation,'evaluate',deny),patch.object(routing_fixtures,'solve',deny):
        tmp=Path(folder)
        for problem,abi in [('fjsp',None),('tsp',None),('obp','obp-two-scalar-h-v1'),('obp','obp-vector-feasible-h-v2')]:
            key=problem+('-vector' if abi=='obp-vector-feasible-h-v2' else '-scalar')
            c=read(ROOT/'experiments/triad/configs'/(problem+'-eoh.json'));c['obp_h_abi']=abi
            if problem=='obp':c.update(obp_actions='preallocated_empty_bins',obp_bound={'version':'obp-R-code-int64-float64-v1','rule':'int(float64(sum_int64(items))/float64(C)+0.5)'})
            host=problems.obp_contract(c) if problem=='obp' else None
            desc=contract.description(problem,abi,host);sample=contract.example(problem,abi)
            parsed=problems.parse_h(problem,sample)
            a=runtime.Adapter();a.p={'run_kind':'eoh'};assert a.parse_candidate(sample,c)==parsed
            parents=[dict(id='SYNTHETIC-'+str(i),candidate=asdict(parsed),fitness=-float(i+1)) for i in range(2)]
            for op in ('I1','E1','E2','M1','M2'):
                prompt=a.build_prompt(c,{'operator':op},parents,[])
                assert desc in prompt and 'literal ASCII braces, NOT LaTeX' in prompt
                prompts[key+'-'+op]={'sha256':digest(prompt),'bytes':len(prompt.encode()),'contract':contract.identity(problem,abi,host)}
                write(OUT/'prompts'/(key+'-'+op+'.json'),{'prompt':prompt,'synthetic_parents':True,'sent':False})
            # Same actual Adapter hook used by H construction; I1 ignores parents.
            a.p={'run_kind':'h-build','config':c};task,parents0=a.task_context(tmp,{'eoh':{}},a.p,{'operator':'M2'},0)
            assert task['operator']=='I1' and not parents0
            assert desc in a.build_prompt(c,task,parents0,[])
            args=problems.h_args(problem,abi);head=contract.signature(problem,abi)+'\n    return '
            vector=abi=='obp-vector-feasible-h-v2';arg=args[0]
            good=['0','1e6' if vector else '1e9',arg+' ** 2']
            bad=[arg+' ** 0.5',arg+' ** -1',arg+' ** 2.0',arg+' ** '+arg,'float("inf")','1e300','1000001' if vector else '1000000001']
            # Validation permits scalar-shaped returns in vector source; host enforces vector output.
            for expr in good:
                problems.validate_h(problem,head+expr+'\n','SYNTHETIC parser sample')
                cases.append({'case':key+':'+expr,'accepted_by_parser':True,'H_executed':False})
            for expr in bad:
                reason=rejects(lambda expr=expr:problems.validate_h(problem,head+expr+'\n','SYNTHETIC invalid'))
                cases.append({'case':key+':'+expr,'accepted_by_parser':False,'reason':reason})
            for body in ['    import os\n    return 0\n','    global x\n    return 0\n','    return '+arg+'.real\n']:
                rejects(lambda body=body:problems.validate_h(problem,contract.signature(problem,abi)+'\n'+body,'bad'))
            tuple_code=head+'(0, 1)\n'
            if vector:problems.validate_h(problem,tuple_code,'vector container syntax')
            else:rejects(lambda:problems.validate_h(problem,tuple_code,'scalar tuple rejected'))
            loop=contract.signature(problem,abi)+'\n    x = 0\n    for i in range(2):\n        x = x + i\n    return x\n'
            if problem=='fjsp':problems.validate_h(problem,loop,'FJSP existing loop language')
            else:rejects(lambda:problems.validate_h(problem,loop,'scalar/vector standalone loops rejected'))
            rejects(lambda:problems.validate_h(problem,'def priority(wrong):\n    return 0\n','wrong signature'))
            # FJSP strict full-match fence parser, and native first-brace gate remain unchanged.
            rejects(lambda:a.parse_candidate('Explanation\n'+sample,c)) if problem=='fjsp' else None
            rejects(lambda:a.parse_candidate(sample+'\n```python\nx=0\n```',c))
            for token in ('0..8','0.5','2.0','float("inf")','24576','2000','1000','ASCII','priority','No defaults'):
                assert token in desc,(key,token)
            assert ('<=1e6' if vector else '<=1e9') in desc
        checks.append('actual triad five native operators and H-build I1 include exact contract for FJSP/TSP/OBP scalar+vector')
        a=eoh_gap.Adapter();p=problems.parse_h('fjsp',contract.example('fjsp'));parents=[dict(id='SYNTHETIC-'+str(i),candidate=asdict(p),fitness=-i) for i in range(2)]
        assert eoh_gap.task_description()==contract.description('fjsp')
        for op in ('I1','E1','E2','M1','M2'):assert contract.description('fjsp') in a.build_prompt({},dict(operator=op),parents,[])
        checks.append('standalone FJSP J-min adapter uses same contract in all five operators')
        # Entry/assets dispatch actually points to the shared H-build adapter.
        assert "run_kind='h-build' if args.kind=='h-build' else None" in (ROOT/'experiments/triad/entry.py').read_text()
        assert "'--kind','h-build'" in (ROOT/'experiments/triad/assets.py').read_text()
        # Original protocol and unbound v2 protocol refuse even with consistent file hashes.
        d=tmp/'identity';write(d/'Tasks.json',[])
        protocol={'version':runtime.VERSION,'source_files':{},'tasks_sha256':sha(d/'Tasks.json'),'run_kind':'eoh','config':{'problem':'fjsp'}}
        def save(p):
            write(d/'Protocol.json',p);(d/'Protocol.sha256').write_text(sha(d/'Protocol.json'));write(d/'checkpoint.json',{'identity':sha(d/'Protocol.json')})
        save(protocol);assert 'new H prompt contract' in rejects(lambda:runtime.Adapter().check_run(d))
        protocol['version']='triad-shared-native-adapter-v1';save(protocol);assert 'no legacy reinterpretation' in rejects(lambda:runtime.Adapter().check_run(d))
        checks.append('old version and missing contract fingerprint cannot resume under new adapter')
        # Original 20 replies are parsed AS IS. Do not rewrite/re-extract/repair any response.
        expected=read(ROOT/'reports/fjsp-eoh-616362-20261114/parse-replay.json')
        protected=[OLD/'Protocol.json',OLD/'checkpoint.json']+sorted((OLD/'prompts').glob('*.json'))+sorted((OLD/'responses').glob('*.json'))
        before={str(p):sha(p) for p in protected};replay=[]
        for row in expected:
            path=OLD/'responses'/f'{row["slot"]:05d}.json';reply=read(path)['text']
            try:problems.parse_h('fjsp',reply);outcome='valid'
            except Exception as x:outcome=str(x)
            assert outcome==row['replayed'],(row['slot'],outcome,row['replayed'])
            replay.append({'slot':row['slot'],'outcome':outcome,'response_file_sha256':sha(path)})
        assert len(replay)==20 and sum(x['outcome']=='valid' for x in replay)==2
        assert before=={str(p):sha(p) for p in protected}
        write(OUT/'OLD20_REPLAY.json',{'unchanged':True,'protected_sha256':before,'rows':replay,'valid':2,'rejected':18,'API_requests':0,'actual_solves':0})
        checks.append('original 20 response replay: identical 2 valid/18 rejects; old protocol/checkpoint/prompts/replies byte-preserved')
        # No changes to the admitted public engine/validators or triad evaluator/problem parser.
        public={}
        for p in (ROOT/'code').rglob('*'):
            if p.is_file() and p.suffix!='.pyc' and '__pycache__' not in p.parts:
                name=str(p.relative_to(ROOT));raw=subprocess.check_output(['git','show',PUBLIC+':'+name],cwd=ROOT);assert raw==p.read_bytes();public[name]=sha(p)
        for name in ('experiments/common/run_frozen.py','experiments/triad/problems.py','experiments/triad/obp_h.py','experiments/triad/evaluation.py'):
            ref=PUBLIC if name.startswith('experiments/common/') else '86d37bba65498e5c05be74868aa0ad3687d415f4'
            assert subprocess.check_output(['git','show',ref+':'+name],cwd=ROOT)==(ROOT/name).read_bytes()
        checks.append('public code and run_frozen exactly 923781f; problem parsers/evaluator unchanged from repair parent')
    value={'passed':True,'contract_version':contract.VERSION,'checks':checks,'parser_cases':cases,'actual_prompt_fingerprints':prompts,'public_files_unchanged':len(public),'CODE_READY':True,'RUN_READY':False,'API_requests':0,'actual_solves':0,'LKH_runs':0,'credential_reads':0,'claim_limit':'Parser/prompt wiring only; no evidence of improved real model success rate'}
    write(OUT/'OFFLINE_CHECKS.json',value);print(json.dumps({'passed':True,'evidence':str(OUT/'OFFLINE_CHECKS.json'),'API_requests':0,'actual_solves':0},indent=2))


if __name__=='__main__':main()
