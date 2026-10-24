"""Read only pinned V2 matrices; choose/define at most one ordinal mechanism.

All recorded states, by source and deduplicated union. Exact WS certificates on
a seed501 reservoir of 64 unique states per pair (not selected on outcome).
No instance parser, H function, new schedule, supplier API or holdout access.
"""
from collections import Counter, defaultdict
import csv
import gzip
import json
from pathlib import Path
import random

from fjsp_usage.fusion_v3.ranking import borda_scores, ws_certificate
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from tools import fusion_v2_experiment as v2

ROOT = v2.ROOT
SOURCE = v2.DEFAULT
OUT = ROOT/'reports/fusion-v3-borda-train21-seed501-20261024-v1/diagnosis'


def main():
    if OUT.exists():
        raise ValueError('new diagnostic directory only; never overwrite')
    p = v2.check(SOURCE)
    OUT.mkdir(parents=True)
    atomic_json(OUT/'Plan.json', {'source_protocol_sha256':v2.sha(SOURCE/'Protocol.json'),
        'states':'all successful first-pass V2 recorded states; invalid-strategy prefixes only for behavior',
        'candidate':'equal midrank Borda on RAW finite H scores; final original first-argmax tie',
        'sampling':'seed501 independent reservoir64 per pair over first-seen deduplicated states',
        'selection_gate':'retain only if actual same-state differences from WS exist and math is non-equivalent',
        'new_solves':0,'API_requests':0,'source_sha256':v2.sha(__file__)})
    rngs = {pair:random.Random(501) for pair in ('0/1','0/5','5/9')}
    samples, seen, counts = defaultdict(list), set(), Counter()
    source_counts, union_counts = defaultdict(Counter), defaultdict(Counter)
    artifacts = []
    with gzip.open(OUT/'Actions.csv.gz','wt',encoding='utf-8') as stream:
        fields = ['pair','source','file','step','state_sha256','action_count','BORDA_action',
                  'WS_action','MAX_action','MIN_action','BORDA_top_ties','WS_top_ties',
                  'MAX_top_ties','MIN_top_ties','BORDA_diff_WS','BORDA_diff_MAX','BORDA_diff_MIN',
                  'raw_vs_minmax_BORDA_diff','WS_squared_spacing_diff']
        writer = csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for spec in v2.specs():
            result_path = SOURCE/'evidence'/spec['id']/'result.json'
            result = v2.read(result_path)
            for row in result['instances']:
                path = SOURCE/row['trace_path']
                if v2.sha(path) != row['trace_sha256']:
                    raise ValueError('V2 trace identity mismatch')
                artifacts.append({'path':row['trace_path'],'sha256':row['trace_sha256']})
                with gzip.open(path,'rt',encoding='utf-8') as handle:
                    for trace in map(json.loads,handle):
                        if digest(trace['physical_state']) != trace['state_sha256']:
                            raise ValueError('V2 full-state identity differs')
                        support=tuple(trace['support'])
                        raw={int(i):tuple(v) for i,v in trace['columns'].items()}
                        norm={int(i):tuple(v) for i,v in trace['normalized'].items()}
                        points,_=borda_scores(raw,support)
                        normalized_points,_=borda_scores(norm,support)
                        pick=lambda values:max(range(len(values)),key=values.__getitem__)
                        choices={};ties={}
                        for op in v2.OPERATORS:
                            scores,_=v2.fuse_scores(raw,trace['weights'],support,op)
                            choices[op]=pick(scores)
                            ties[op]=sum(x==scores[choices[op]] for x in scores)
                            if op==spec['operator'] and (choices[op]!=trace['winner'] or tuple(scores)!=tuple(trace['scores'])):
                                raise ValueError('frozen V2 recombination differs')
                        chosen=pick(points)
                        square_ws=[norm[support[0]][a]**2+norm[support[1]][a]**2 for a in range(len(points))]
                        pair='/'.join(map(str,support));key=(pair,row['file'],trace['state_sha256'])
                        metrics={'states':1,'BORDA_diff_WS':chosen!=choices['WEIGHTED_SUM'],
                            'BORDA_diff_MAX':chosen!=choices['MAX'],'BORDA_diff_MIN':chosen!=choices['MIN'],
                            'BORDA_tied_states':sum(x==points[chosen] for x in points)>1,
                            'WS_tied_states':ties['WEIGHTED_SUM']>1,'MAX_tied_states':ties['MAX']>1,
                            'MIN_tied_states':ties['MIN']>1,
                            'raw_vs_minmax_BORDA_diff':chosen!=pick(normalized_points),
                            'WS_squared_spacing_diff':choices['WEIGHTED_SUM']!=pick(square_ws)}
                        source_counts[(pair,spec['id'])].update(metrics)
                        if key not in seen:
                            seen.add(key);union_counts[pair].update(metrics);counts[pair]+=1
                            entry={'pair':pair,'source':spec['id'],'file':row['file'],
                                'step':trace['step'],'state_sha256':trace['state_sha256'],
                                'raw':raw,'normalized':norm,'support':support,'target':chosen}
                            sample=samples[pair]
                            if len(sample)<64:sample.append(entry)
                            else:
                                index=rngs[pair].randrange(counts[pair])
                                if index<64:sample[index]=entry
                        writer.writerow({'pair':pair,'source':spec['id'],'file':row['file'],'step':trace['step'],
                            'state_sha256':trace['state_sha256'],'action_count':len(points),'BORDA_action':chosen,
                            'WS_action':choices['WEIGHTED_SUM'],'MAX_action':choices['MAX'],'MIN_action':choices['MIN'],
                            'BORDA_top_ties':sum(x==points[chosen] for x in points),
                            'WS_top_ties':ties['WEIGHTED_SUM'],'MAX_top_ties':ties['MAX'],'MIN_top_ties':ties['MIN'],
                            **{k:metrics[k] for k in ('BORDA_diff_WS','BORDA_diff_MAX','BORDA_diff_MIN',
                                'raw_vs_minmax_BORDA_diff','WS_squared_spacing_diff')}})
    certificates=[]
    for pair,entries in samples.items():
        for entry in entries:
            certificates.append(dict(entry,certificate=ws_certificate(entry['raw'],entry['normalized'],
                                                                      entry['support'],entry['target'])))
    with gzip.open(OUT/'Exact_WS_samples.jsonl.gz','wt',encoding='utf-8') as handle:
        for entry in certificates:handle.write(json.dumps(entry,separators=(',',':'))+'\n')
    certificate_counts={pair:dict(Counter(e['certificate']['status'] for e in certificates if e['pair']==pair))
                        for pair in samples}
    summaries=[{'pair':pair,'source':source,**dict(stats)} for (pair,source),stats in source_counts.items()]
    summaries += [{'pair':pair,'source':'UNION_DEDUPLICATED',**dict(stats)} for pair,stats in union_counts.items()]
    v2.csv_write(OUT/'Common_state_summary.csv',summaries)
    conclusion={'source_protocol_sha256':v2.sha(SOURCE/'Protocol.json'), 'summaries':summaries,
        'sample_WS_certificate_counts':certificate_counts,
        'selected_mechanism':'BORDA_MIDRANK_RAW',
        'selection_reason':'ordinal spacing is mathematically distinct from minmax-linear scores; observed same-state choices differ',
        'definition':'sum_i(2*number_lower_i + number_equal_i - 1), equal two members; exact score ties; stable first final max',
        'normalization':'integer points are positive-affine equivalent to equal mean percentile ranks; raw columns ranked before minmax',
        'fairness':'same three historical member pairs; all chosen before any new Fitness; legacy time15 and train21 remain',
        'certificate_boundary':'exact real-arithmetic constraints over stored normalized float values; not proof over every IEEE weight evaluation',
        'new_solves':0,'new_H_calls':0,'API_requests':0}
    if not all(union_counts[pair]['BORDA_diff_WS']>0 for pair in union_counts):
        conclusion['selected_mechanism']=None
    atomic_json(OUT/'Diagnosis.json',conclusion)
    atomic_json(OUT/'Artifact_sources.json',artifacts)
    v2.check(SOURCE)
    print(json.dumps({'union':{k:dict(v) for k,v in union_counts.items()},
                      'certificates':certificate_counts,'selected':conclusion['selected_mechanism']},ensure_ascii=False))


if __name__=='__main__':main()
