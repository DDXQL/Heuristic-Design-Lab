"""Small real integration acceptance, train only, never formal study assets.

Two independently generated h candidates -> real human review -> one U sample.
No handwritten H, evolution, validation/test, refill, repair or automatic retries.
Uses the same transport, ledger, parser, full-train evaluator and review guard.
"""

from dataclasses import asdict, dataclass, field, replace
import json
import math
import os
from pathlib import Path

from fjsp_usage.research.candidates import Candidate, CandidateError, parse_response
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from .assets import seal, check_seal, checked_candidate, check_receipt, check_result, make_receipt, review_member, validate_row
from .budget import BudgetLedger, BudgetJournal, BudgetStop
from .config import ProviderConfig, fingerprint, loopback_url
from .evaluation_cache import EvaluationCache
from .leafapi import provider as leaf_provider, MODEL, KEY_ENV
from .prompts import build_prompt, prompt_manifest
from .real_transport import JsonCandidateTransport
from .review_packet import write_review_packet


@dataclass(frozen=True)
class SmokeConfig:
    provider: ProviderConfig = field(default_factory=lambda: replace(leaf_provider(),
        max_output_tokens=2048, max_prompt_bytes=16384, input_token_reservation=32768,
        expected_response_model=MODEL))
    mode: str = 'real'
    real_requests_authorized: bool = False
    total_request_cap: int = 20
    total_token_cap: int | None = None
    cost_cap_estimate: float | None = 5.0
    unpriced_requests_authorized: bool = False
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    price_currency: str = 'CNY'
    price_verified: bool = False
    price_source: str | None = None
    h_candidates: int = 2
    instance_timeout: float = 3.0
    review_timeout: float = 3.0

    def __post_init__(self):
        if not isinstance(self.provider, ProviderConfig):
            raise ValueError('explicit provider required')
        if self.mode not in ('real','synthetic'):
            raise ValueError('explicit smoke mode required')
        if self.mode == 'synthetic' and (not loopback_url(self.provider.endpoint) or self.provider.api_key_env):
            raise ValueError('synthetic smoke must be local, without credentials')
        if any(type(v) is not bool for v in (self.real_requests_authorized, self.price_verified,
                                            self.unpriced_requests_authorized)):
            raise ValueError('authorization/price verification must be bool')
        if type(self.total_request_cap) is not int or not 1 <= self.total_request_cap <= 20:
            raise ValueError('smoke request cap must be a built-in int in [1,20]')
        for value in (self.instance_timeout, self.review_timeout):
            if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
                raise ValueError('finite positive smoke cost/time limits required')
        if self.cost_cap_estimate is not None and (type(self.cost_cap_estimate) not in (int,float)
                or not math.isfinite(self.cost_cap_estimate) or not 0 < self.cost_cap_estimate <= 5):
            raise ValueError('smoke estimated-cost stop must be <=5 CNY')
        if self.price_currency != 'CNY':
            raise ValueError('smoke price currency must be CNY')
        if self.cost_cap_estimate is None and not self.unpriced_requests_authorized:
            raise ValueError('removing the cost stop requires explicit unpriced request authorization')
        if self.unpriced_requests_authorized and (self.mode != 'real' or self.total_request_cap > 3
                or self.cost_cap_estimate is not None or self.price_verified
                or self.input_price_per_million is not None or self.output_price_per_million is not None):
            raise ValueError('unpriced authorization permits at most three real smoke requests, without invented prices')
        if type(self.h_candidates) is not int or self.h_candidates != 2:
            raise ValueError('acceptance uses exactly two generated h, not a formal H')
        if self.total_token_cap is not None and (type(self.total_token_cap) is not int or self.total_token_cap <= 0):
            raise ValueError('positive built-in token cap required')
        prices = (self.input_price_per_million, self.output_price_per_million)
        if any(p is not None for p in prices) and any(type(p) not in (int,float) or not math.isfinite(p) or p <= 0 for p in prices):
            raise ValueError('both conservative positive token prices required')
        if self.price_verified and (None in prices or not isinstance(self.price_source,str) or not self.price_source.strip()):
            raise ValueError('verified CNY prices require an explicit source and both rates')

    def payload(self):
        return asdict(self)

    def phase_caps(self):
        return {'smoke/h': self.h_candidates, 'smoke/u': 1}

    def check_dispatch(self):
        if self.mode == 'real':
            if not self.real_requests_authorized:
                raise BudgetStop('small integration requests have not been authorized in this config')
            if (self.provider.endpoint != 'https://leafapi.cc/v1/chat/completions'
                    or self.provider.model != MODEL or self.provider.protocol != 'openai-chat-v1'
                    or self.provider.api_key_env != KEY_ENV or self.provider.expected_response_model != MODEL):
                raise BudgetStop('smoke requires the locked Leaf model/protocol/environment')
        if not self.price_verified and not self.unpriced_requests_authorized:
            raise BudgetStop('CNY price/group/conversion unverified; no paid dispatch')
        if self.provider.api_key_env and not os.environ.get(self.provider.api_key_env):
            raise BudgetStop('credential environment variable absent; no paid dispatch')

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        value['provider'] = ProviderConfig(**value['provider'])
        return cls(**value)


class SmokeJournal(BudgetJournal):
    def request(self, key, prompt, *, kind='U'):
        existed = key in self.data['requests']
        if not existed and self.ledger.data.get('smoke_stop_reason'):
            raise BudgetStop(self.ledger.data['smoke_stop_reason'])
        record = super().request(key, prompt, kind=kind)
        if record['status'] != 'completed' or record.get('usage') is None:
            self.ledger.data['smoke_stop_reason'] = 'transport failure/interruption or unknown usage; no further smoke requests'
            self.ledger.data['halted'] = True
            self.ledger.save()
        return record


class IntegrationSmoke:
    def __init__(self, directory, *, config, dataset, project_root):
        if dataset.mode != config.mode:
            raise ValueError('smoke data/mode mismatch')
        self.directory, self.config, self.dataset = Path(directory), config, dataset
        self.root = Path(project_root)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.protocol = {'kind':'Integration_smoke_protocol', 'scope':'integration acceptance only; not a research experiment',
            'mode':config.mode, 'config':config.payload(), 'dataset':dataset.metadata,
            'implementation':fingerprint(self.root), 'prompt_pack':prompt_manifest(),
            'holdout_access':'forbidden', 'planned_requests':3, 'human_H_review':'required; never automatic'}
        self.context = digest(self.protocol)
        path = self.directory/'protocol.json'
        if path.exists() and digest(json.loads(path.read_text())) != self.context:
            raise ValueError('smoke resume rejected: source/config/runtime/data changed; new directory required')
        atomic_json(path, self.protocol)
        self.ledger = BudgetLedger(self.directory/'budget.json', config, self.context)
        self.cache = EvaluationCache(self.directory/'evaluations.json', self.context)
        self._train = None

    def assert_current(self):
        if fingerprint(self.root) != self.protocol['implementation']:
            raise ValueError('source/runtime changed during smoke; new directory required')
        if digest(self.config.payload()) != digest(self.protocol['config']):
            raise ValueError('smoke configuration changed during run')
        from hashlib import sha256
        if sha256(self.dataset.path.read_bytes()).hexdigest() != self.dataset.metadata['manifest_sha256']:
            raise ValueError('manifest changed during smoke')

    def read(self, name, kind):
        return check_seal(json.loads((self.directory/name).read_text()), kind=kind,
                          mode=self.config.mode, context=self.context)

    def write(self, name, kind, **fields):
        result = seal({'kind':kind,'mode':self.config.mode,'context':self.context,
                       'scope':'integration acceptance only; not a formal result', **fields})
        atomic_json(self.directory/name,result)
        return result

    def report(self, stage, reason=None):
        summary = self.ledger.summary()
        return self.write('Smoke_status.json','Integration_smoke_status',stage=stage,reason=reason,
            budget=summary, price_currency='CNY', price_verified=self.config.price_verified,
            dataset_opened=[list(row) for row in self.dataset.opened],
            validation_test_opened=False, formal_H_frozen=False, research_conclusions=False)

    def _journal(self, phase):
        self.config.check_dispatch()
        return SmokeJournal(self.directory/(phase.split('/')[-1]+'_requests.json'),
            phase=phase, cap=self.config.phase_caps()[phase],
            transport=JsonCandidateTransport(self.config), ledger=self.ledger)

    def _row(self, journal, identifier, prompt, kind, members=()):
        record = journal.request(identifier, prompt, kind=kind)
        if record['status'] != 'completed' or record.get('usage') is None:
            raise BudgetStop('smoke response failed or usage unknown; no retry')
        candidate = parse_response(record['text'], kind=kind)
        self.dataset.verify('train')
        if self._train is None:
            self._train = self.dataset.load('train')
        result = self.cache.get(digest({'candidate':candidate.key,'H':[m.key for m in members]}),
            self.dataset.names['train'], lambda:self.dataset.evaluate(candidate,members,'train',
                timeout=self.config.instance_timeout,instances=self._train))
        if not result['valid']:
            raise ValueError('candidate failed complete train evaluation; diagnostic prefix retained, no partial fitness')
        return {'id':identifier,'candidate':asdict(candidate), 'training_result':result,
            'fitness':result['fitness'],'scores':[r['score'] for r in result['instances']],
            'receipt':make_receipt(candidate,record,self.ledger,self.config,journal.transport.identity)}

    def _check_rows(self, rows, kind):
        for row in rows:
            candidate = validate_row(row,self.dataset.names['train'],self.config.mode,kind)
            if 'origin' in row:
                if kind != 'h':
                    raise ValueError('only h acceptance samples may be explicitly imported')
                from .smoke_reuse import check_imported_row
                check_imported_row(self,row)
                continue
            receipt = row['receipt']
            expected_transport = digest({'provider':self.config.payload()['provider'],'mode':self.config.mode})
            charged = self.ledger.data['records'].get(receipt['global_key'])
            if (receipt['model'] != self.config.provider.model or receipt['protocol'] != self.config.provider.protocol
                    or receipt['transport_identity'] != expected_transport
                    or receipt['ledger_identity'] != self.ledger.identity or not charged
                    or charged['status'] != 'completed' or not charged['send_confirmed']
                    or charged['usage'] != receipt['usage'] or charged['prompt_key'] != receipt['prompt_key']):
                raise ValueError('smoke receipt not backed by this ledger')
            journal = json.loads((self.directory/('h_requests.json' if kind=='h' else 'u_requests.json')).read_text())
            record = journal['requests'].get(row['id'])
            if not record or record.get('text') != receipt['response_text']:
                raise ValueError('smoke source response changed')

    def import_h_samples(self, sources):
        from .smoke_reuse import import_h_samples
        return import_h_samples(self,sources)

    def generate_h_sample(self):
        """One real candidate/full train receipt; never assembles or approves H."""
        self.assert_current()
        name, kind = 'Smoke_h_sample.json', 'Integration_smoke_h_sample'
        try:
            self.dataset.verify('train')
            if (self.directory/name).exists():
                sample = self.read(name,kind)
                self._check_rows([sample['row']],'h')
            else:
                row = self._row(self._journal('smoke/h'),'h/0',
                    build_prompt('H','I1',(),(),kind='h'),'h')
                self.write(name,kind,row=row,training_files=list(self.dataset.names['train']))
        except (BudgetStop,ValueError) as exc:
            self.report('STOPPED',str(exc))
            raise
        return self.report('SINGLE_H_ACCEPTANCE_COMPLETE',
            'one generated h passed complete train; H assembly, human review and U acceptance remain pending')

    def generate_h(self):
        self.assert_current()
        name, kind = 'Smoke_h_candidates.json','Integration_smoke_h_candidates'
        try:
            if (self.directory/name).exists():
                self.dataset.verify('train')
                source = self.read(name,kind)
                self._check_rows(source['rows'],'h')
            else:
                journal = self._journal('smoke/h')
                rows = []
                for i in range(self.config.h_candidates):
                    row = self._row(journal,f'h/{i}',build_prompt('H','I1',(),(),kind='h'),'h')
                    if row['candidate']['key'] in {r['candidate']['key'] for r in rows}:
                        raise ValueError('duplicate h; no refill or repair')
                    rows.append(row)
                source = self.write(name,kind,rows=rows,training_files=list(self.dataset.names['train']))
            write_review_packet(self.directory,source['rows'],self.dataset.names['train'],mode=self.config.mode,
                context=self.context,source_hash=source['artifact_sha256'],timeout=self.config.review_timeout)
        except (BudgetStop,ValueError) as exc:
            self.report('STOPPED',str(exc))
            raise
        return self.report('HUMAN_REVIEW_REQUIRED','two generated h fully evaluated; fill review file before any U request')

    def review_h(self, reviews):
        self.assert_current()
        self.dataset.verify('train')
        source = self.read('Smoke_h_candidates.json','Integration_smoke_h_candidates')
        self._check_rows(source['rows'],'h')
        keys = {r['candidate']['key'] for r in source['rows']}
        if not isinstance(reviews,dict) or set(reviews) != keys or len(keys) != 2:
            raise ValueError('real human reviews must cover both generated h keys exactly')
        members = []
        for i,row in enumerate(source['rows']):
            fields = reviews[row['candidate']['key']]
            if not isinstance(fields,dict) or set(fields) != {'description','reviewer','method','note'}:
                raise ValueError('exact human review fields required')
            if not isinstance(fields['method'],str) or fields['method'].startswith('synthetic'):
                raise ValueError('automatic/synthetic review is not accepted, even for local smoke tests')
            review = review_member(checked_candidate(row['candidate'],'h'), **fields, timeout=self.config.review_timeout)
            members.append({**row,'member_id':i,'review':review})
        existing = self.directory/'Smoke_H_reviewed.json'
        fields = dict(members=members,source_hash=source['artifact_sha256'])
        expected = seal({'kind':'Integration_smoke_H_reviewed','mode':self.config.mode,'context':self.context,
                         'scope':'integration acceptance only; not a formal result',**fields})
        if existing.exists():
            if self.read(existing.name,'Integration_smoke_H_reviewed') != expected:
                raise ValueError('smoke H review already locked; do not overwrite')
        else:
            self.write(existing.name,'Integration_smoke_H_reviewed',**fields)
        return self.report('HUMAN_REVIEW_COMPLETE','reviewed smoke H; cannot be promoted into formal workflow')

    def generate_u(self):
        self.assert_current()
        try:
            self.dataset.verify('train')
            source = self.read('Smoke_h_candidates.json','Integration_smoke_h_candidates')
            H = self.read('Smoke_H_reviewed.json','Integration_smoke_H_reviewed')
            if H['source_hash'] != source['artifact_sha256'] or len(H['members']) != 2:
                raise ValueError('smoke reviewed H binding mismatch')
            if [{k:v for k,v in r.items() if k not in ('member_id','review')} for r in H['members']] != source['rows']:
                raise ValueError('reviewed smoke H differs from generated candidates')
            self._check_rows(H['members'],'h')
            members = []
            for index,row in enumerate(H['members']):
                candidate = checked_candidate(row['candidate'],'h')
                review = row['review']
                if type(row['member_id']) is not int or row['member_id'] != index or review['method'].startswith('synthetic'):
                    raise ValueError('invalid smoke member/review')
                expected = review_member(candidate,**{k:review[k] for k in ('description','reviewer','method','note')},
                                         timeout=self.config.review_timeout)
                if review != expected:
                    raise ValueError('smoke review samples/code changed')
                members.append(Candidate(review['description'],candidate.code,candidate.key,'h'))
            name = 'Smoke_U_sample.json'
            if (self.directory/name).exists():
                asset = self.read(name,'Integration_smoke_U_sample')
                if asset['H_hash'] != H['artifact_sha256']:
                    raise ValueError('smoke U belongs to another H')
                self._check_rows([asset['row']],'U')
            else:
                row = self._row(self._journal('smoke/u'),'u/0',build_prompt('B0','I1',(),members),'U',members)
                self.write(name,'Integration_smoke_U_sample',row=row,H_hash=H['artifact_sha256'])
        except (BudgetStop,ValueError,FileNotFoundError) as exc:
            self.report('STOPPED',str(exc))
            raise
        return self.report('INTEGRATION_ACCEPTANCE_COMPLETE','one U sample checked and evaluated on all train; no evolution/holdouts/conclusion')
