"""Migration guards and shared-core MOCK only; no formal instance or API."""
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from heuristic_design.core import execution
from heuristic_design.core.storage import read,write,sha
from heuristic_design.core.results import validate_complete
from heuristic_design.llm.legacy import ClientConfig
from heuristic_design.problems.tsp import campaign,candidates
from heuristic_design.problems.tsp.operations import MockTransport

ROOT=campaign.ROOT
spec=importlib.util.spec_from_file_location('tsp_archive_inspector',ROOT/'experiments/tsp/inspect_archive.py')
inspector=importlib.util.module_from_spec(spec);spec.loader.exec_module(inspector)


class MockAdapter:
    ROOT=ROOT
    entrypoint='experiments/tsp/manage.py'
    CandidateError=candidates.CandidateError
    read=staticmethod(read);write=staticmethod(write);sha=staticmethod(sha)
    def __init__(self,directory,stop_first=False):
        self.directory=directory;self.protocol_sha=sha(directory/'Protocol.json');self.task_sha=sha(directory/'Tasks.json');self.stop_first=stop_first
    def check_run(self,directory):
        if sha(directory/'Protocol.json')!=self.protocol_sha or sha(directory/'Tasks.json')!=self.task_sha:raise ValueError('MOCK identity changed')
        return read(directory/'Protocol.json')
    def client_config(self,p):return ClientConfig(p)
    def transport(self,p):return MockTransport(ClientConfig(p))
    def members(self,directory):return [None,None]
    def build_prompt(self,*args):return 'MOCK engineering fixture only\nH MEMBER 0\nH MEMBER 1\n'
    def parse_candidate(self,text,config):return candidates.parse(text,'U',2)
    def checked_candidate(self,value):return candidates.checked(value,2)
    def validate_result(self,result,instances):return validate_complete(result,instances)
    def evaluate(self,directory,state,p,candidate):
        # Deliberate fake scalar result. The TSP solver is never called.
        if candidate.key in state['evaluations']:return read(directory/state['evaluations'][candidate.key]['path']),True
        path=directory/'evaluations'/candidate.key/'result.json'
        result={'valid':True,'fitness':-1.,'total_instances':1,'instances':[{'file':'MOCK_NOT_SOLVED','score':-1.}]}
        write(path,result);state['evaluations'][candidate.key]={'status':'completed','path':str(path.relative_to(directory)),'sha256':sha(path)}
        write(directory/'checkpoint.json',state)
        if self.stop_first:self.stop_first=False;execution.stop(directory,adapter=self)
        return result,False
    def summary(self,directory,write_files=False):return {'phase':read(directory/'checkpoint.json')['phase']}


class Tests(unittest.TestCase):
    def setUp(self):
        self.guard=patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK'));self.guard.start();self.addCleanup(self.guard.stop)

    def fixture(self,folder):
        config=read(ROOT/'experiments/tsp/configs/pilot-mock.json')
        config.update(api_attempt_cap=3,type='ind',population_size=2,cross_parents=2,window_seconds=3600,search_seed=41,candidate_kind='U')
        p={'config':config,'instances':[{'file':'MOCK_NOT_SOLVED'}],'budgets':{'logical_generation':2,'max_program_instances':2}}
        write(folder/'Protocol.json',p);write(folder/'Tasks.json',[{'id':'MOCK/0','stage':'new','operator':'I1'},{'id':'MOCK/1','stage':'new','operator':'I1'}])
        write(folder/'checkpoint.json',{'identity':sha(folder/'Protocol.json'),'phase':'prepared','cursor':0,'tasks':{},'evaluations':{},'population':[],'children':[],'seen':{},'generation':0,'pause_ack':0})
        return p

    def test_shared_core_pause_resume_keeps_clock_budget_and_first_response(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'runs',prefix='integration-mock-') as t:
            folder=Path(t);self.fixture(folder);adapter=MockAdapter(folder,stop_first=True)
            with patch('heuristic_design.problems.tsp.solver.construct',side_effect=AssertionError('NO SOLVE')):
                first=execution.start(folder,adapter=adapter)
                self.assertEqual((first['phase'],first['cursor']),('paused',1));self.assertFalse((folder/'.execution.lock').exists())
                clock=sha(folder/'Run_clock.json');journal=read(folder/'API_attempts.json')
                second=execution.start(folder,adapter=adapter,resume=True)
            self.assertEqual((second['phase'],second['cursor']),('completed',2))
            self.assertEqual(sha(folder/'Run_clock.json'),clock);self.assertFalse((folder/'.execution.lock').exists())
            after=read(folder/'API_attempts.json');self.assertEqual(len(after['requests']),2);self.assertEqual(len(after['api_attempts']),2)
            for key,value in journal['requests'].items():self.assertEqual(after['requests'][key],value)
            for key,value in journal['api_attempts'].items():self.assertEqual(after['api_attempts'][key],value)

    def test_source_identity_and_unknown_attempt_are_not_replayed(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'runs',prefix='integration-identity-') as t:
            folder=Path(t);p=self.fixture(folder);adapter=MockAdapter(folder)
            value=read(folder/'Protocol.json');value['tampered']=True;write(folder/'Protocol.json',value)
            with self.assertRaises(ValueError):execution.start(folder,adapter=adapter)
            write(folder/'Protocol.json',p)
            write(folder/'API_attempts.json',{'halt_reason':None,'api_attempts':{'unknown':{'status':'interrupted_unknown'}}})
            with self.assertRaises(ValueError):execution.start(folder,adapter=adapter)
            self.assertFalse((folder/'.execution.lock').exists())

    def test_real_api_default_gate_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'runs',prefix='integration-gate-') as t:
            folder=Path(t);p=self.fixture(folder);p['config']['api_mode']='real';p['config']['real_requests_authorized']=False;write(folder/'Protocol.json',p)
            state=read(folder/'checkpoint.json');state['identity']=sha(folder/'Protocol.json');write(folder/'checkpoint.json',state)
            adapter=MockAdapter(folder)
            with patch.object(adapter,'transport',side_effect=AssertionError('NO CLIENT')):
                with self.assertRaises(PermissionError):execution.start(folder,adapter=adapter,allow_api=True)
            self.assertFalse((folder/'.execution.lock').exists())
        self.assertFalse(read(ROOT/'experiments/tsp/configs/pilot-real.json')['real_requests_authorized'])

    def test_foreign_archive_is_rejected_before_any_old_path_read_or_write(self):
        folder=ROOT/'archives/not-an-executable-campaign'
        with patch.object(campaign,'read',side_effect=AssertionError('NO OLD FILE READ')),patch.object(campaign,'write',side_effect=AssertionError('NO ARCHIVE WRITE')):
            for action in [lambda:campaign.check(folder),lambda:campaign.summary(folder),lambda:campaign.stop(folder)]:
                with self.assertRaises(ValueError):action()
        with tempfile.TemporaryDirectory(dir=ROOT/'runs',prefix='integration-foreign-') as t:
            folder=Path(t);write(folder/'Protocol.json',{'config_file':'/absent/original/config.json'})
            with self.assertRaisesRegex(ValueError,'historical absolute'):campaign.check(folder)

    def test_archive_maps_names_without_old_filesystem_fallback(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);vault=folder/'vault';p=vault/'workspace/runs/example/Protocol.json';write(p,{'immutable':True})
            manifest={'source_root':'/absent/original','workspace':'workspace','source_commit':'fixture','files':{'runs/example/Protocol.json':{'sha256':sha(p),'bytes':p.stat().st_size}}}
            write(vault/'Manifest.json',manifest);receipt=folder/'receipt.json';write(receipt,{'vault':str(vault),'manifest_sha256':sha(vault/'Manifest.json')})
            archive=inspector.EvidenceVault(receipt)
            self.assertEqual(archive.read('/absent/original/runs/example/Protocol.json'),{'immutable':True})
            for bad in ['/different/Protocol.json','runs/../escape.json']:
                with self.assertRaises(ValueError):archive.read(bad)
            write(p,{'changed':True})
            with self.assertRaises(ValueError):archive.read('runs/example/Protocol.json')
