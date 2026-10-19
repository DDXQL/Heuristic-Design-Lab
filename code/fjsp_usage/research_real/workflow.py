"""Independent staged experiment controller, no provider creation after search.

Synthetic acceptance assets are deliberately incompatible with real runs.
Use under RunLock. Existing Tier1, v1/v2 and research_v1 remain unchanged.
"""

import ast
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path

from fjsp_usage.research.events import atomic_json, Events
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.sets import ranked
from .assets import (seal, check_seal, checked_candidate, check_result, load_h,
                     check_population, review_member)
from .budget import BudgetLedger, BudgetStop, request_history
from .config import fingerprint, protocol
from .evaluation_cache import EvaluationCache
from .real_transport import JsonCandidateTransport
from .search import V5BudgetedSearch
from .review_packet import write_review_packet

ARMS = ('B0', 'B1', 'B2', 'P')


class Workflow:
    _protocol = staticmethod(protocol)
    def __init__(self, directory, *, config, dataset, project_root):
        self.directory, self.config, self.dataset = Path(directory), config, dataset
        self.project_root = Path(project_root)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.protocol = self._protocol(config, dataset.metadata, fingerprint(self.project_root))
        self.context = digest(self.protocol)
        path = self.directory / 'protocol.json'
        if path.exists() and digest(json.loads(path.read_text())) != self.context:
            raise ValueError('resume rejected: protocol/source/runtime/data changed; start a new run')
        if config.request_budget is not None:
            request_history(config, self.project_root, exclude=self.directory)
        atomic_json(path, self.protocol)
        self.ledger = BudgetLedger(self.directory / 'budget.json', config, self.context)
        self.cache = EvaluationCache(self.directory / 'stage_evaluations.json', self.context)
        self.events = Events(self.directory / 'events.jsonl')
        self._client = None
        self._train = None

    def assert_current(self):
        if hashlib.sha256(self.dataset.path.read_bytes()).hexdigest() != self.dataset.metadata['manifest_sha256']:
            raise ValueError('dataset manifest changed during run')
        if digest(self._protocol(self.config, self.dataset.metadata, fingerprint(self.project_root))) != self.context:
            raise ValueError('implementation changed during run; new run required')

    def client(self):
        if self._client is None:
            if self.config.request_budget is not None:
                from .single_io import WireRecorder
                def verify():
                    self.assert_current()
                    self.ledger.request_history()
                verify()
                self._client = WireRecorder(JsonCandidateTransport(self.config),
                    self.directory/'wire_responses', verify)
                return self._client
            evidence = None
            research_history = None
            if self.config.conditional_research:
                from .conditional_research import dispatch_check
                research_history = dispatch_check(self)
            if self.config.development_continuation_source is not None:
                from .continuation import check_dispatch_gate
                evidence = check_dispatch_gate(self)
            self._client = JsonCandidateTransport(self.config)
            if self.config.platform_quota_ceiling is not None:
                from .quota_guard import QuotaGuardedTransport
                kwargs = {}
                if research_history:
                    kwargs = dict(retained_extra=research_history['retained_account_hold'],
                        settlement_min_used=research_history['latest_saved_account_used'])
                if self.config.development_acceptance:
                    from .development_acceptance import check_plan
                    plan = check_plan(self,evidence)
                    kwargs = dict(retained_records={k:evidence['quota']['records'][k]
                        for k in evidence['unresolved']}, retained_extra=plan['previous_unknown_account_hold'],
                        allowed_phase=f'r{self.config.seeds[0]}/P/',settlement_min_used=plan.get('settlement_min_used',0))
                self._client = QuotaGuardedTransport(self._client,
                    self.directory / 'platform_quota.json', self.context, **kwargs)
        return self._client

    def read(self, name, kind):
        asset = json.loads((self.directory / name).read_text())
        return check_seal(asset, kind=kind, mode=self.config.mode, context=self.context)

    def write(self, name, kind, **fields):
        asset = seal({'kind': kind, 'mode': self.config.mode, 'context': self.context, **fields})
        atomic_json(self.directory / name, asset)
        return asset

    def progress(self, stage, **fields):
        record = {'stage': stage, 'mode': self.config.mode, **fields,
                  'budget': self.ledger.summary()}
        atomic_json(self.directory / 'progress.json', record)
        self.events.emit('stage', stage=stage, **fields)

    def train_eval(self, candidate, members):
        self.dataset.verify('train')
        if self._train is None:
            self._train = self.dataset.load('train')
        return self.dataset.evaluate(candidate, members, 'train', timeout=self.config.instance_timeout,
                                     instances=self._train, diagnostics=self.config.training_diagnostics)

    def search_engine(self, folder, arm, members, search_config, init_phase, search_phase, initial=None):
        return V5BudgetedSearch(self.directory / folder, arm=arm, config=search_config,
            members=members, evaluator=lambda c: self.train_eval(c, members), transport=self.client(),
            context=self.context, kind='h' if arm == 'H' else 'U', initial=initial,
            init_phase=init_phase, search_phase=search_phase, ledger=self.ledger,
            experiment=self.config, training_names=self.dataset.names['train'])

    def generate_h(self):
        if self.config.conditional_research:
            raise ValueError('conditional fixed-H research does not generate a new H')
        self.assert_current()
        if (self.directory / 'H_candidates.json').exists():
            asset = self.read('H_candidates.json', 'H_candidates')
            self.review_h()
            return asset
        engine = self.search_engine('H', 'H', (), self.config.h_search(), 'H/init', 'H/search')
        if self.config.development_h_source is not None:
            self.seed_development_h(engine)
        try:
            report = engine.run()
        except BudgetStop:
            self.progress('H_GENERATION_FAILED', reason='budget_or_context_stop')
            raise
        if report['phase'] != 'completed':
            self.progress('H_GENERATION_FAILED', reason=report['phase'])
            raise ValueError('H initialization failed; no smaller H or refill')
        asset = self.write('H_candidates.json', 'H_candidates', population=engine.export_rows(),
            training_files=list(self.dataset.names['train']), member_count=self.config.H_size,
            search_report={k: v for k, v in report.items() if k != 'population'})
        self.progress('H_REVIEW_REQUIRED')
        self.review_h()
        return asset

    def seed_development_h(self, engine):
        from .development_reuse import source_rows, check_imported_rows
        path = self.directory/'H_development_source.json'
        originals, audit = source_rows(self.project_root, self.config, self.dataset.metadata,
                                       self.protocol['implementation'])
        if path.exists():
            asset = self.read('H_development_source.json', 'H_development_source')
            check_imported_rows(asset, originals, audit)
        else:
            rows = []
            for row in originals:
                check_result(row['training_result'], self.dataset.names['train'])
                result = self.train_eval(checked_candidate(row['candidate'], 'h'), ())
                check_result(result, self.dataset.names['train'])
                if not result['valid'] or result['fitness'] != row['fitness'] or [r['score'] for r in result['instances']] != row['scores']:
                    raise ValueError('imported h did not reproduce complete training results')
                rows.append({**row, 'training_result':result})
            asset = self.write('H_development_source.json', 'H_development_source',
                population=rows, audit=audit, notice='Development reuse only; original receipts are foreign, not new sends.')
        if engine.state.get('source_import_hash') is None:
            if engine.state['population'] or engine.state['attempts'] or engine.state['inflight']:
                raise ValueError('development sources must be declared before new generation')
            rows = [{**r, 'source_import_hash':asset['artifact_sha256']} for r in asset['population']]
            engine.state.update(population=ranked(rows), seen={r['candidate']['key']:r['id'] for r in rows},
                                source_import_hash=asset['artifact_sha256'])
            engine._save()
            self.progress('H_DEVELOPMENT_SOURCE_REUSED', members=len(rows), new_model_requests=0)
        elif engine.state['source_import_hash'] != asset['artifact_sha256']:
            raise ValueError('development import checkpoint changed')

    def review_h(self):
        self.assert_current()
        self.dataset.verify('train')
        source = self.read('H_candidates.json', 'H_candidates')
        self.check_receipts(source['population'])
        packet = write_review_packet(self.directory, ranked(source['population']),
            self.dataset.names['train'], mode=self.config.mode, context=self.context,
            source_hash=source['artifact_sha256'], timeout=self.config.review_timeout)
        self.progress('H_REVIEW_REQUIRED', review_packet='H_review_packet.md',
            automatic_sample_failures=sum(not r['automatic_samples']['valid'] for r in packet['rows']))
        return packet

    def freeze_h(self, reviews=None):
        self.assert_current()
        self.dataset.verify('train')
        if (self.directory / 'H_frozen.json').exists():
            return self.h_asset()[0]
        source = self.read('H_candidates.json', 'H_candidates')
        rows = ranked(source['population'])
        if len(rows) != self.config.H_size:
            raise ValueError('exact K generated members required')
        if reviews is None and self.config.mode != 'synthetic':
            raise ValueError('real H requires an explicit code-key-bound human review file')
        if reviews is not None and (not isinstance(reviews, dict) or set(reviews) != {r['candidate']['key'] for r in rows}):
            raise ValueError('review keys must cover the exact generated H')
        members = []
        for index, row in enumerate(rows):
            candidate = checked_candidate(row['candidate'], 'h')
            if reviews is None:
                tree = ast.parse(candidate.code)
                body = tree.body[0].body
                if len(body) != 1 or not isinstance(body[0], ast.Return):
                    raise ValueError('synthetic auto-review supports single return fixtures only')
                review = review_member(candidate, description='Return ' + ast.unparse(body[0].value)
                    + '; highest finite score wins.', reviewer='local-fixture-expression-review',
                    method='synthetic-expression-review', note='Synthetic acceptance only; no research quality claim.',
                    timeout=self.config.review_timeout)
            else:
                fields = reviews[candidate.key]
                if not isinstance(fields, dict) or set(fields) != {'description','reviewer','method','note'}:
                    raise ValueError('review fields must be exactly description/reviewer/method/note')
                review = review_member(candidate, **fields, timeout=self.config.review_timeout)
            members.append({**row, 'member_id': index, 'review': review})
        asset = seal({'kind': 'H_frozen', 'mode': self.config.mode, 'context': self.context,
            'member_count': self.config.H_size, 'training_files': list(self.dataset.names['train']),
            'members': members, 'source_hash': source['artifact_sha256'],
            'source_mechanism': 'minimal complementary survival/parents adapter; not full upstream runner'})
        load_h(asset, mode=self.config.mode, context=self.context, size=self.config.H_size,
               names=self.dataset.names['train'], review_timeout=self.config.review_timeout)
        atomic_json(self.directory / 'H_frozen.json', asset)
        self.progress('H_FROZEN')
        return asset

    def check_receipts(self, rows):
        for row in rows:
            if self.config.development_continuation_source is not None:
                from .continuation import check_foreign_row
                if check_foreign_row(self, row):
                    continue
            if row.get('source_import_hash'):
                if self.config.purpose != 'framework_development' or not self.config.development_h_source:
                    raise ValueError('foreign receipt forbidden in research protocol')
                asset = self.read('H_development_source.json', 'H_development_source')
                imported = [r for r in asset['population'] if r['id']==row['id']]
                if (row['source_import_hash'] != asset['artifact_sha256'] or len(imported)!=1
                        or any(row[k] != v for k,v in imported[0].items())):
                    raise ValueError('development source receipt/result binding mismatch')
                from .development_reuse import source_rows, check_imported_rows
                originals, audit = source_rows(self.project_root,self.config,self.dataset.metadata,self.protocol['implementation'])
                check_imported_rows(asset, originals, audit)
                continue
            receipt = row['receipt']
            expected_transport = digest({'provider': self.config.payload()['provider'], 'mode': self.config.mode})
            if (receipt['model'] != self.config.provider.model or receipt['protocol'] != self.config.provider.protocol
                    or receipt['transport_identity'] != expected_transport
                    or not receipt['global_key'].endswith('/'+row['id'])):
                raise ValueError('receipt model/protocol/candidate ID mismatch')
            if receipt['ledger_identity'] != self.ledger.identity:
                raise ValueError('foreign receipt ledger')
            charged = self.ledger.data['records'].get(receipt['global_key'])
            if not charged or not charged['send_confirmed'] or charged['status'] != 'completed':
                raise ValueError('receipt not backed by completed ledger send')
            if charged['usage'] != receipt['usage'] or charged['prompt_key'] != receipt['prompt_key']:
                raise ValueError('receipt ledger usage/prompt mismatch')
            # Bind the receipt back to the immutable local request response too.
            phase = charged['phase']
            if phase.startswith('H/'):
                folder = self.directory / 'H'
            else:
                repeat, part = phase.split('/')
                folder = self.directory / repeat / ('INIT' if part == 'init' else part)
            journal_name = 'budgeted_initial_requests.json' if phase.endswith('/init') else 'budgeted_evolution_requests.json'
            journal = json.loads((folder / journal_name).read_text())
            records = [r for r in journal['requests'].values() if r['global_key'] == receipt['global_key']]
            if len(records) != 1 or records[0].get('text') != receipt['response_text']:
                raise ValueError('receipt local response mismatch')

    def h_asset(self):
        self.dataset.verify('train')
        if self.config.conditional_research:
            from .conditional_research import h_asset
            return h_asset(self)
        asset = self.read('H_frozen.json', 'H_frozen')
        members = load_h(asset, mode=self.config.mode, context=self.context, size=self.config.H_size,
                         names=self.dataset.names['train'], review_timeout=self.config.review_timeout)
        self.check_receipts(asset['members'])
        source = self.read('H_candidates.json', 'H_candidates')
        if source['artifact_sha256'] != asset['source_hash']:
            raise ValueError('H generated source changed after freeze')
        if [{k:v for k,v in r.items() if k not in ('review','member_id')} for r in asset['members']] != ranked(source['population']):
            raise ValueError('H differs from generated source')
        return asset, members

    def population(self, name, kind, H_hash):
        asset = self.read(name, kind)
        rows = check_population(asset, mode=self.config.mode, context=self.context, kind=kind,
            H_hash=H_hash, names=self.dataset.names['train'], size=self.config.population_size)
        self.check_receipts(rows)
        folder = self.directory / name
        folder = folder.parent/'INIT' if kind == 'Shared_initial' else folder.parent
        state = json.loads((folder/'checkpoint.json').read_text())
        if (len(state['population']) != len(rows) or [r['id'] for r in rows] != [r['id'] for r in state['population']]
                or state['phase'] != ('evolution' if kind == 'Shared_initial' else 'completed')
                or (kind == 'Final_population' and state['generation'] != self.config.generations)):
            raise ValueError('population not backed by a completed stage checkpoint')
        for row, original in zip(rows, state['population']):
            if any(row[k] != v for k,v in original.items()):
                raise ValueError('population row differs from checkpoint')
            cached = state['evaluations'].get(row['id'])
            if cached and cached.get('result') != row['training_result']:
                raise ValueError('population train result differs from evaluation checkpoint')
        return asset, rows

    def prepare_continuation(self):
        """Bind existing development assets offline; never construct a client."""
        from .continuation import prepare
        return prepare(self)

    def initialize_u(self, seed, *, max_new_requests=None):
        """One declared repeat, no evolutionary requests; shared by all arms."""
        self.assert_current()
        if type(seed) is not int or seed not in self.config.seeds:
            raise ValueError('seed must be one of the predeclared built-in integers')
        H, members = self.h_asset()
        repeat = f'r{seed}'
        name = repeat + '/Shared_initial.json'
        if (self.directory/name).exists():
            asset, _ = self.population(name, 'Shared_initial', H['artifact_sha256'])
            return {'status': 'initialized', 'asset': asset}
        status_name = repeat + '/Initialization_status.json'
        if (self.directory/status_name).exists():
            status = self.read(status_name, 'Initialization_status')
            if status['H_hash'] != H['artifact_sha256'] or status['seed'] != seed:
                raise ValueError('initialization status binding changed')
            return {'status': status['status'], 'asset': None}
        engine = self.search_engine(repeat+'/INIT', 'INIT', members, self.config.u_search(seed),
                                    repeat+'/init', repeat+'/B0')
        try:
            valid = engine.initialize(stop_after_attempts=max_new_requests)
            failure = 'initialization_failed'
        except BudgetStop:
            valid, failure = False, 'initialization_budget_stopped'
        if valid is None:
            self.progress('U_INITIALIZATION_WINDOW_PAUSED', seed=seed,
                          total_initial_attempts=engine.state['init_cursor'])
            return {'status': 'initialization_paused', 'asset': None}
        if not valid:
            self.write(status_name, 'Initialization_status', seed=seed, status=failure,
                       H_hash=H['artifact_sha256'], search_report=engine.report())
            self.progress('REPEAT_INITIALIZATION_FAILED', seed=seed, reason=failure)
            return {'status': failure, 'asset': None}
        asset = self.write(name, 'Shared_initial', seed=seed, H_hash=H['artifact_sha256'],
            training_files=list(self.dataset.names['train']), population=engine.export_rows())
        self.progress('U_INITIALIZED', seed=seed)
        return {'status': 'initialized', 'asset': asset}

    def search_arm(self, seed, arm):
        """Explicit one-arm entry; cannot itself open validation or test."""
        self.assert_current()
        if arm not in ARMS:
            raise ValueError('unknown search arm')
        if self.config.development_acceptance and arm != 'P':
            raise ValueError('single-P acceptance authorizes P only')
        change = (self.config.development_continuation_source or {}).get('search_change')
        if change and arm != 'P' and not (self.directory/f'r{seed}/P/Final_population.json').exists():
            raise ValueError('reduced development must inspect P first; use explicit search-arm')
        initialized = self.initialize_u(seed)
        if initialized['status'] != 'initialized':
            return {'seed': seed, 'arm': arm, 'status': initialized['status'], 'population_hash': None}
        H, members = self.h_asset()
        initial = initialized['asset']
        folder = f'r{seed}/{arm}'
        name = folder + '/Final_population.json'
        if (self.directory/name).exists():
            asset, _ = self.population(name, 'Final_population', H['artifact_sha256'])
            if asset['shared_initial_hash'] != initial['artifact_sha256']:
                raise ValueError('arm shared initialization changed')
        else:
            engine = self.search_engine(folder, arm, members, self.config.u_search(seed),
                f'r{seed}/init', f'r{seed}/{arm}', initial=initial['population'])
            try:
                report = engine.run()
            except BudgetStop:
                self.progress('ARM_BUDGET_STOPPED', seed=seed, arm=arm)
                return {'seed': seed, 'arm': arm, 'status': 'budget_stopped', 'population_hash': None}
            if report['phase'] != 'completed':
                raise ValueError('unfinished search cannot export final population')
            asset = self.write(name, 'Final_population', seed=seed, arm=arm,
                H_hash=H['artifact_sha256'], shared_initial_hash=initial['artifact_sha256'],
                training_files=list(self.dataset.names['train']), population=engine.export_rows(),
                search_report={k: v for k, v in report.items() if k != 'population'})
        self.progress('ARM_COMPLETED', seed=seed, arm=arm)
        return {'seed': seed, 'arm': arm, 'status': 'completed', 'population_hash': asset['artifact_sha256']}

    def search_all(self):
        self.assert_development_stage('search')
        self.assert_current()
        H, _ = self.h_asset()
        if (self.directory / 'Search_complete.json').exists():
            gate = self.read('Search_complete.json', 'Search_complete')
            self.check_search(gate, H)
            return gate
        entries = [self.search_arm(seed, arm) for seed in self.config.seeds for arm in ARMS]
        hashes = [e['population_hash'] for e in entries if e['status'] == 'completed']
        gate = self.write('Search_complete.json', 'Search_complete', dataset_hash=self.dataset.key,
            H_hash=H['artifact_sha256'], reference_H_hash=H['artifact_sha256'],
            seeds=list(self.config.seeds), entries=entries, population_hashes=hashes)
        self.progress('SEARCH_COMPLETE')
        return gate

    def check_search(self, gate, H):
        check_seal(gate, kind='Search_complete', mode=self.config.mode, context=self.context)
        if (gate['dataset_hash'] != self.dataset.key or gate['H_hash'] != H['artifact_sha256']
                or gate['reference_H_hash'] != H['artifact_sha256']):
            raise ValueError('search gate binding mismatch')
        if [(e['seed'], e['arm']) for e in gate['entries']] != [(s,a) for s in self.config.seeds for a in ARMS]:
            raise ValueError('missing or changed predeclared repeat/group')
        hashes = []
        for entry in gate['entries']:
            if entry['status'] == 'completed':
                name = f'r{entry["seed"]}/{entry["arm"]}/Final_population.json'
                asset, _ = self.population(name, 'Final_population', H['artifact_sha256'])
                initial, _ = self.population(f'r{entry["seed"]}/Shared_initial.json', 'Shared_initial', H['artifact_sha256'])
                if (asset['artifact_sha256'] != entry['population_hash'] or asset['seed'] != entry['seed']
                        or asset['arm'] != entry['arm'] or asset['shared_initial_hash'] != initial['artifact_sha256']):
                    raise ValueError('final population provenance mismatch')
                hashes.append(asset['artifact_sha256'])
            elif entry['status'] not in ('initialization_failed', 'initialization_budget_stopped', 'budget_stopped') or entry['population_hash'] is not None:
                raise ValueError('unknown terminal search status')
        if gate['population_hashes'] != hashes:
            raise ValueError('registered final population hashes mismatch')

    def stage_eval(self, candidate, members, split, gate, population_hash=None):
        if split == 'validation' and candidate.kind == 'U' and population_hash not in gate['population_hashes']:
            raise ValueError('U validation requires a registered final population')
        if split == 'validation' and candidate.kind == 'h' and population_hash != gate['reference_H_hash']:
            raise ValueError('h reference validation requires registered H')
        self.dataset.authorize(split, context=self.context, gate=gate, population_hash=population_hash)
        key = digest({'split': split, 'candidate': candidate.key,
                      'H': [m.key for m in members], 'gate': gate['artifact_sha256']})
        return self.cache.get(key, self.dataset.names[split], lambda: self.dataset.evaluate(candidate, members,
            split, timeout=self.config.instance_timeout, context=self.context, gate=gate, population_hash=population_hash))

    def assert_development_stage(self, stage):
        if (self.config.development_continuation_source or {}).get('search_change'):
            raise ValueError('reduced development is train-only; explicit arms only, no '+stage)

    def select(self):
        self.assert_development_stage('select')
        self.assert_current()
        H, members = self.h_asset()
        gate = self.read('Search_complete.json', 'Search_complete')
        self.check_search(gate, H)
        if (self.directory / 'Selection_complete.json').exists():
            asset = self.read('Selection_complete.json', 'Selection_complete')
            self.check_selection(asset, gate, H)
            return asset
        entries = []
        for entry in gate['entries']:
            if entry['status'] != 'completed':
                entries.append({**entry, 'selection_status': 'search_failed', 'U_star_hash': None})
                continue
            folder = f'r{entry["seed"]}/{entry["arm"]}'
            population, rows = self.population(folder+'/Final_population.json', 'Final_population', H['artifact_sha256'])
            evaluated = []
            for row in rows:
                candidate = checked_candidate(row['candidate'], 'U')
                result = self.stage_eval(candidate, members, 'validation', gate, population['artifact_sha256'])
                evaluated.append({'id': row['id'], 'result': result})
            valid = [r for r in evaluated if r['result']['valid']]
            if not valid:
                entries.append({**entry, 'selection_status': 'selection_failed', 'U_star_hash': None,
                                'validation_results': evaluated})
                atomic_json(self.directory/folder/'validation_results.json', evaluated)
                continue
            best = min(valid, key=lambda r: (-r['result']['fitness'], r['id']))
            chosen = next(r for r in rows if r['id'] == best['id'])
            star = self.write(folder+'/U_star.json', 'U_star', seed=entry['seed'], arm=entry['arm'],
                H_hash=H['artifact_sha256'], population_hash=population['artifact_sha256'],
                row=chosen, validation_result=best['result'], validation_results=evaluated)
            entries.append({**entry, 'selection_status': 'selected', 'U_star_hash': star['artifact_sha256']})
        # Fixed h reference selected once on validation, never on test.
        evaluated_h = []
        for row in H['members']:
            result = self.stage_eval(checked_candidate(row['candidate'], 'h'), (), 'validation', gate,
                                    gate['reference_H_hash'])
            evaluated_h.append({'member_id': row['member_id'], 'result': result})
        valid = [r for r in evaluated_h if r['result']['valid']]
        fixed = min(valid, key=lambda r: (-r['result']['fitness'], r['member_id'])) if valid else None
        selection = self.write('Selection_complete.json', 'Selection_complete', dataset_hash=self.dataset.key,
            H_hash=H['artifact_sha256'], search_hash=gate['artifact_sha256'], entries=entries,
            fixed_h=fixed, fixed_h_validation=evaluated_h)
        self.check_selection(selection, gate, H)
        self.progress('SELECTION_COMPLETE')
        return selection

    def check_selection(self, selection, gate, H):
        check_seal(selection, kind='Selection_complete', mode=self.config.mode, context=self.context)
        if (selection['search_hash'] != gate['artifact_sha256'] or selection['H_hash'] != H['artifact_sha256']
                or selection['dataset_hash'] != self.dataset.key or len(selection['entries']) != len(gate['entries'])):
            raise ValueError('selection binding mismatch')
        self.dataset.verify('validation', context=self.context, gate=gate, population_hash=gate['reference_H_hash'])
        for entry, search_entry in zip(selection['entries'], gate['entries']):
            if any(entry[k] != search_entry[k] for k in search_entry):
                raise ValueError('selection planned entry mismatch')
            if entry['selection_status'] == 'selected':
                folder = f'r{entry["seed"]}/{entry["arm"]}'
                star = self.read(folder+'/U_star.json', 'U_star')
                population, rows = self.population(folder+'/Final_population.json', 'Final_population', H['artifact_sha256'])
                if (star['artifact_sha256'] != entry['U_star_hash'] or star['population_hash'] != population['artifact_sha256']
                        or star['H_hash'] != H['artifact_sha256'] or star['row'] not in rows
                        or star['seed'] != entry['seed'] or star['arm'] != entry['arm']):
                    raise ValueError('selected U not bound to final population')
                results = star['validation_results']
                if [r['id'] for r in results] != [r['id'] for r in rows]:
                    raise ValueError('selection must evaluate entire final population only')
                for result in results:
                    check_result(result['result'], self.dataset.names['validation'])
                valid = [r for r in results if r['result']['valid']]
                best = min(valid, key=lambda r: (-r['result']['fitness'], r['id']))
                if best['id'] != star['row']['id'] or best['result'] != star['validation_result']:
                    raise ValueError('U selection violates full-validation mean/stable tie')
            elif entry['selection_status'] not in ('search_failed', 'selection_failed') or entry['U_star_hash'] is not None:
                raise ValueError('invalid selection failure status')
            elif entry['selection_status'] == 'selection_failed':
                population, rows = self.population(f'r{entry["seed"]}/{entry["arm"]}/Final_population.json',
                                                   'Final_population', H['artifact_sha256'])
                results = entry.get('validation_results', [])
                if [r['id'] for r in results] != [r['id'] for r in rows] or any(r['result']['valid'] for r in results):
                    raise ValueError('selection failure requires all final candidates invalid')
                for row in results:
                    check_result(row['result'], self.dataset.names['validation'])
            if entry['selection_status'] == 'search_failed' and search_entry['status'] == 'completed':
                raise ValueError('completed search cannot be hidden as a search failure')
        fixed_results = selection['fixed_h_validation']
        if [r['member_id'] for r in fixed_results] != list(range(self.config.H_size)):
            raise ValueError('all H reference candidates must be validated once')
        for row in fixed_results:
            check_result(row['result'], self.dataset.names['validation'])
        valid = [r for r in fixed_results if r['result']['valid']]
        expected = min(valid, key=lambda r: (-r['result']['fitness'], r['member_id'])) if valid else None
        if selection['fixed_h'] != expected:
            raise ValueError('fixed h selection changed')

    def freeze(self):
        self.assert_development_stage('freeze')
        self.assert_current()
        H, _ = self.h_asset()
        gate = self.read('Search_complete.json', 'Search_complete')
        self.check_search(gate, H)
        selection = self.read('Selection_complete.json', 'Selection_complete')
        self.check_selection(selection, gate, H)
        fields = dict(dataset_hash=self.dataset.key, H_hash=H['artifact_sha256'],
            search_hash=gate['artifact_sha256'], selection_hash=selection['artifact_sha256'],
            selection=selection, protocol_hash=self.context, analysis=self.config.analysis,
            seeds=list(self.config.seeds),
            frozen_at_utc=(self.read('Experiment_frozen.json', 'Experiment_frozen')['frozen_at_utc']
                if (self.directory/'Experiment_frozen.json').exists() else datetime.now(timezone.utc).isoformat()))
        expected = seal(dict(kind='Experiment_frozen', mode=self.config.mode, context=self.context, **fields))
        if (self.directory/'Experiment_frozen.json').exists():
            if self.read('Experiment_frozen.json', 'Experiment_frozen') != expected:
                raise ValueError('frozen experiment changed')
            return expected
        atomic_json(self.directory/'Experiment_frozen.json', expected)
        self.progress('EXPERIMENT_FROZEN')
        return expected

    def test(self):
        self.assert_development_stage('test')
        # No client()/secret/environment/provider construction in this phase.
        frozen = self.read('Experiment_frozen.json', 'Experiment_frozen')
        if self.freeze() != frozen:
            raise ValueError('test freeze mismatch')
        self.dataset.verify('test', context=self.context, gate=frozen)
        H, members = self.h_asset()
        if (self.directory/'Test_complete.json').exists():
            result = self.read('Test_complete.json', 'Test_complete')
            if result['freeze_hash'] != frozen['artifact_sha256']:
                raise ValueError('test belongs to another freeze')
            return result
        entries = []
        for entry in frozen['selection']['entries']:
            if entry['selection_status'] != 'selected':
                entries.append({**entry, 'test_result': None})
                continue
            star = self.read(f'r{entry["seed"]}/{entry["arm"]}/U_star.json', 'U_star')
            result = self.stage_eval(checked_candidate(star['row']['candidate'], 'U'), members, 'test', frozen)
            entries.append({**entry, 'test_result': result})
        fixed = frozen['selection']['fixed_h']
        fixed_result = (self.stage_eval(checked_candidate(H['members'][fixed['member_id']]['candidate'], 'h'),
                                       (), 'test', frozen) if fixed else None)
        result = self.write('Test_complete.json', 'Test_complete', freeze_hash=frozen['artifact_sha256'],
            dataset_hash=self.dataset.key, entries=entries, fixed_h_result=fixed_result)
        self.progress('TEST_COMPLETE')
        return result
