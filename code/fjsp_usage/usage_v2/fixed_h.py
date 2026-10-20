"""Read-only frozen-H provenance for new local-budget protocols; no H search.

Use the existing native/conditional asset auditors in their ORIGINAL context.
Only a new wrapper is written; member rows, reviews and receipts are unchanged.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_seal, seal
from fjsp_usage.research_real.workflow import Workflow

VERSION = 'usage-frozen-H-source-v1'
CORE_FILES = ('code/fjsp_usage/offline_v2.py', 'code/fjsp_usage/research/scheduler.py',
    'code/llm4ad/task/optimization/fjsp_set/scheduler.py',
    'code/llm4ad/task/optimization/fjsp_set/instances.py',
    'code/fjsp_usage/research_real/runtime.py')


def validate_declaration(config):
    d = config.fixed_h_source
    if (config.request_budget is None or not isinstance(d, dict)
            or set(d) != {'version', 'directory', 'files_sha256'} or d['version'] != VERSION
            or not isinstance(d['directory'], str) or not Path(d['directory']).is_absolute()
            or not isinstance(d['files_sha256'], dict)
            or not {'protocol.json', 'H_frozen.json'} <= set(d['files_sha256'])):
        raise ValueError('fixed H requires a new local-budget protocol and explicit source file pins')
    for name, sha in d['files_sha256'].items():
        p = PurePosixPath(name)
        if (p.is_absolute() or '..' in p.parts or str(p) != name or not name.endswith('.json')
                or not isinstance(sha, str) or len(sha) != 64
                or any(c not in '0123456789abcdef' for c in sha)):
            raise ValueError('fixed-H pins must be relative JSON paths and SHA256')


def wrapper(config, context, source):
    return seal({'kind':'H_frozen', 'mode':config.mode, 'context':context,
        'member_count':source['member_count'], 'training_files':source['training_files'],
        'members':source['members'], 'source_hash':source['artifact_sha256'],
        'source_context':source['context'], 'fixed_h_source':config.fixed_h_source,
        'source_mechanism':'unchanged existing frozen H; original reviews/receipts retained; no generation or new review'})


def source_h(config, dataset, implementation, *, target=None, ancestors=(), check_writer=None):
    validate_declaration(config)
    if check_writer is None:
        check_writer = (getattr(config,'request_budget',None) or {}).get('version') != 'batch-api-attempts-v1'
    d = config.fixed_h_source; folder = Path(d['directory']).resolve()
    if folder in ancestors or len(ancestors) >= 8 or (target is not None and folder == Path(target).resolve()):
        raise ValueError('fixed-H source cycle or self-reference')
    if check_writer and (folder/'.writer.lock').exists():
        raise ValueError('fixed-H source has a writer lock')
    docs = {}
    for name, sha in d['files_sha256'].items():
        path = (folder/name).resolve()
        if not path.is_relative_to(folder):
            raise ValueError('fixed-H source path escape')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError('fixed-H source file changed: '+name)
        docs[name] = json.loads(raw)
    protocol = docs['protocol.json']; context = digest(protocol)
    asset = check_seal(docs['H_frozen.json'],kind='H_frozen',mode=config.mode,context=context)
    original = protocol['config']
    if (protocol['mode'] != config.mode or original['mode'] != config.mode
            or original['purpose'] != config.purpose or protocol['dataset'] != dataset.metadata
            or original['H_size'] != config.H_size or original['instance_timeout'] != config.instance_timeout
            or original['review_timeout'] != config.review_timeout):
        raise ValueError('fixed-H mode/scope, data, K or evaluation contract differs')
    old_impl = protocol['implementation']
    if (any(old_impl[k] != implementation[k] for k in ('version','python','platform','dependencies'))
            or any(not old_impl['files'].get(n) or old_impl['files'][n] != implementation['files'].get(n) for n in CORE_FILES)):
        raise ValueError('fixed-H scheduler/evaluator/runtime differs; cached results cannot be rebound')
    old = SimpleNamespace(**original)
    old.provider = SimpleNamespace(**original['provider'])
    old.payload = lambda: original

    def read(name, kind):
        if name not in docs:
            raise ValueError('missing fixed-H provenance pin: '+name)
        return check_seal(docs[name],kind=kind,mode=config.mode,context=context)

    if original.get('fixed_h_source'):
        parent, members = source_h(old,dataset,implementation,target=target,ancestors=(*ancestors,folder),check_writer=check_writer)
        if asset != wrapper(old,context,parent):
            raise ValueError('inherited fixed-H wrapper differs from its original members/provenance')
        return asset, members

    # A reader object, NOT Workflow.__init__: no source protocol, budget, cache
    # or checkpoint is created or rewritten when auditing an old asset.
    reader = SimpleNamespace(directory=folder, project_root=folder.parent.parent,
        config=old, dataset=dataset, context=context, read=read,check_source_writer=check_writer)
    if original.get('conditional_research'):
        if 'Conditional_H_reassessment.json' not in docs:
            raise ValueError('conditional H requires pinned reassessment and original scope approval')
        from fjsp_usage.research_real.conditional_research import h_asset
        # This checks the ORIGINAL scope approval, member order/rows, generated
        # ancestry, reviews and native response/ledger receipts. It never calls
        # history_summary, a supplier client or an account/billing query.
        return h_asset(reader)

    if any(original.get(k) for k in ('development_h_source','development_continuation_source','development_acceptance')):
        raise ValueError('development H requires its existing approved conditional frozen view; no promotion here')
    if not {'budget.json','H_candidates.json'} <= set(docs):
        raise ValueError('native H requires original candidates, ledger and request journal pins')
    budget = docs['budget.json']
    identity = digest({'config':original,'context':context})
    if budget.get('identity') != identity or budget.get('mode') != config.mode:
        raise ValueError('fixed-H original ledger identity mismatch')
    for row in asset['members']:
        record = budget['records'].get(row['receipt']['global_key'],{})
        phase = record.get('phase','')
        if not phase.startswith('H/'):
            raise ValueError('native frozen-H receipt is not an H generation record')
        journal = 'H/budgeted_'+('initial' if phase.endswith('/init') else 'evolution')+'_requests.json'
        if journal not in docs:
            raise ValueError('missing fixed-H request journal pin: '+journal)
    reader.ledger = SimpleNamespace(identity=identity,data=budget)
    reader.check_receipts = lambda rows: Workflow.check_receipts(reader,rows)
    return Workflow.h_asset(reader)


def bind(flow):
    flow.assert_current()
    source, members = source_h(flow.config,flow.dataset,flow.protocol['implementation'],target=flow.directory)
    expected = wrapper(flow.config,flow.context,source)
    path = flow.directory/'H_frozen.json'
    if path.exists():
        if flow.read('H_frozen.json','H_frozen') != expected:
            raise ValueError('bound fixed-H content/order/provenance changed')
    else:
        from fjsp_usage.research.events import atomic_json
        atomic_json(path,expected)
    return expected, members


def load(flow):
    if not flow.config.fixed_h_source:
        raise ValueError('new local-budget SELECT/MIX requires fixed_h_source and bind-h')
    if not (flow.directory/'H_frozen.json').exists():
        raise ValueError('fixed H not bound; run bind-h before initializing U')
    return bind(flow)
