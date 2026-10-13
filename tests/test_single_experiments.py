"""Independent fixtures: no model calls and no real benchmark access."""
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.candidates import U_ARGS, CandidateError, validate_code, compile_candidate
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.single_experiments import (
    VERSION, file_hashes, verify_sources, budget_inventory, Guard, GuardedTransport, declaration_pins)


class SingleSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'work'; self.origin = Path(self.tmp.name)/'origin'
        for root in (self.root,self.origin):
            (root/'runs/old').mkdir(parents=True)
            (root/'runs/old/budget.json').write_text(json.dumps({'identity':'old','mode':'real',
                'records':{'sent':{'usage':None,'reservation':{'input_tokens':65536,'output_tokens':32768},
                                  'send_confirmed':True}}}))
        self.pins = file_hashes(self.origin)

    def test_root_notes_stay_in_snapshot_but_not_asset_declaration(self):
        note=self.origin/'runs/root-note.log';note.write_text('historical evidence')
        pins=file_hashes(self.origin)
        self.assertIn('root-note.log',pins)
        self.assertNotIn('root-note.log',declaration_pins(pins))
        self.assertIn('old/budget.json',declaration_pins(pins))

    def test_read_only_source_and_copy_match(self):
        verify_sources(self.root,self.origin,self.pins)
        self.assertEqual(file_hashes(self.root),self.pins)

    def test_source_edit_stops(self):
        (self.origin/'runs/old/budget.json').write_text('{}')
        with self.assertRaises(BudgetStop):verify_sources(self.root,self.origin,self.pins)

    def test_local_missing_copy_stops(self):
        (self.root/'runs/old/budget.json').unlink()
        with self.assertRaises(BudgetStop):verify_sources(self.root,self.origin,self.pins)

    def test_duplicate_copied_ledgers_count_once_and_unknown_preserved(self):
        inventory = budget_inventory([self.root,self.origin])
        self.assertEqual(len(inventory),1)
        self.assertIsNone(json.loads((self.root/'runs/old/budget.json').read_text())['records']['sent']['usage'])

    def test_divergent_ledger_copy_stops(self):
        path = self.root/'runs/old/budget.json';body=json.loads(path.read_text())
        body['records']['second']={};path.write_text(json.dumps(body))
        with self.assertRaises(BudgetStop):budget_inventory([self.root,self.origin])

    def test_other_writer_stops_and_own_writer_is_allowed(self):
        active=self.root/'runs/new';active.mkdir();(active/'.writer.lock').write_text('{}')
        with self.assertRaises(BudgetStop):budget_inventory([self.root,self.origin])
        self.assertEqual(len(budget_inventory([self.root,self.origin],exclude=active)),1)

    def test_peer_new_request_stops_before_transport(self):
        directory=self.root/'runs/current';directory.mkdir()
        flow=SimpleNamespace(context='context',project_root=self.root,directory=directory,assert_current=lambda:None)
        binding={'version':VERSION,'context':'context','origin_root':str(self.origin),
                 'source_files_sha256':self.pins,'real_budget_inventory':budget_inventory([self.root,self.origin])}
        inner=SimpleNamespace(identity='fixture',preflight=lambda p:self.fail('provider preflight reached'),
                              dispatch=lambda *a,**k:self.fail('provider dispatch reached'),redact=lambda s:s)
        transport=GuardedTransport(inner,Guard(flow,binding))
        peer=self.origin/'runs/new';peer.mkdir()
        (peer/'budget.json').write_text(json.dumps({'identity':'peer','mode':'real','records':{'unknown':{}}}))
        with patch('fjsp_usage.research_real.single_experiments.worktree_roots',return_value=[self.root,self.origin]):
            with self.assertRaises(BudgetStop):transport.preflight('prompt')
            with self.assertRaises(BudgetStop):transport.dispatch('id','prompt')

    def test_current_batch_records_do_not_look_like_peer_consumption(self):
        active=self.root/'runs/current';active.mkdir()
        (active/'budget.json').write_text(json.dumps({'identity':'own','mode':'real','records':{'sent':{}}}))
        self.assertEqual(len(budget_inventory([self.root,self.origin],exclude=active)),1)


class SingleLanguageTests(unittest.TestCase):
    def test_score_calculation_is_legal_without_tuple_or_mix(self):
        code='def select_heuristic('+', '.join(U_ARGS)+'):\n    s0 = 1.0 - progress\n    s1 = progress * progress\n    return 0 if s0 >= s1 else 1\n'
        function=compile_candidate(validate_code(code))
        self.assertEqual(function(.1,1.,0.,0.,0.,0.,-1),0)
        self.assertEqual(function(.9,1.,0.,0.,0.,0.,0),1)

    def test_usage_v2_tuple_cannot_enter_scalar_population(self):
        for expression in ('(0, (1, 0))','(1, (1, 1))'):
            code='def select_heuristic('+', '.join(U_ARGS)+'):\n    return '+expression+'\n'
            with self.assertRaises(CandidateError):validate_code(code)


if __name__=='__main__':unittest.main()
