"""Reuse paid h responses for acceptance only, with a fresh full-train evaluation.

Old requests keep their original protocol/ledger/receipt. They are never charged
to the new ledger, silently retried, or promoted to formal EoH-S assets.
"""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from fjsp_usage.research.candidates import parse_response
from fjsp_usage.research.protocol import digest
from .assets import make_receipt
from .budget import validate_usage
from .review_packet import write_review_packet

FILES = ('protocol.json', 'budget.json', 'h_requests.json')


def read_bundle(directory):
    payload, hashes, raw = {}, {}, {}
    for name in FILES:
        data = (Path(directory)/name).read_bytes()
        if len(data) > 2_097_152:
            raise ValueError('source acceptance file too large')
        payload[name] = json.loads(data)
        hashes[name], raw[name] = sha256(data).hexdigest(), data
    return payload, hashes, raw


def generation(payload, request_id, *, mode, dataset, provider):
    from .integration_smoke import SmokeConfig
    try:
        protocol, ledger, journal = (payload[n] for n in FILES)
        config = SmokeConfig.from_dict(protocol['config'])
        context = digest(protocol)
        # Historical configs lacking newly added default fields retain their
        # exact recorded identity, rather than being rewritten to today's schema.
        identity = digest({'config':protocol['config'],'context':context})
        transport = digest({'provider':protocol['config']['provider'],'mode':mode})
        if (protocol['kind'] != 'Integration_smoke_protocol' or protocol['mode'] != mode
                or config.mode != mode or protocol['dataset'] != dataset
                or ledger['mode'] != mode or ledger['identity'] != identity):
            raise ValueError('source mode, data or ledger binding mismatch')
        if mode == 'real' and not config.real_requests_authorized:
            raise ValueError('source real request was not authorized')
        for name in ('endpoint','model','protocol','api_key_env'):
            if getattr(config.provider,name) != getattr(provider,name):
                raise ValueError('source provider/model/protocol mismatch')
        expected_journal = digest({'transport':transport,'phase':'smoke/h',
            'cap':config.phase_caps()['smoke/h'],'ledger':identity})
        if journal['identity'] != expected_journal:
            raise ValueError('source journal identity mismatch')
        record = journal['requests'][request_id]
        global_key = 'smoke/h/'+request_id
        charged = ledger['records'][global_key]
        prompt_key = digest({'prompt':record['prompt'],'kind':'h'})
        usage = validate_usage(record['usage'])
        if (record['kind'] != 'h' or record['status'] != 'completed'
                or record['global_key'] != global_key or record['prompt_key'] != prompt_key
                or charged['phase'] != 'smoke/h' or charged['prompt_key'] != prompt_key
                or charged['status'] != 'completed' or charged['send_confirmed'] is not True
                or usage is None or charged['usage'] != usage):
            raise ValueError('source generation is not backed by a completed known-usage request')
        if mode == 'real' and record.get('response_metadata',{}).get('model') != config.provider.model:
            raise ValueError('source response model mismatch')
        candidate = parse_response(record['text'],kind='h')
        receipt = make_receipt(candidate,record,SimpleNamespace(data=ledger,identity=identity),config,transport)
        return {'candidate':asdict(candidate),'receipt':receipt}
    except (KeyError,TypeError) as exc:
        raise ValueError('incomplete source generation evidence') from exc


def check_imported_row(flow, row):
    origin = row['origin']
    folder = (flow.directory/origin['snapshot']).resolve()
    if not folder.is_relative_to((flow.directory/'imported_sources').resolve()):
        raise ValueError('source snapshot path escape')
    payload, hashes, _ = read_bundle(folder)
    if hashes != origin['file_sha256']:
        raise ValueError('source snapshot changed')
    original = generation(payload,origin['request_id'],mode=flow.config.mode,
        dataset=flow.dataset.metadata,provider=flow.config.provider)
    if original['candidate'] != row['candidate'] or original['receipt'] != row['receipt']:
        raise ValueError('imported candidate or original receipt changed')


def import_h_samples(flow, sources):
    """Exactly two independent paid h responses; no LLM, holdout or review approval."""
    flow.assert_current()
    if len(sources) != 2:
        raise ValueError('two explicit generated h sources required')
    prepared = []
    for index,(directory, request_id) in enumerate(sources):
        payload, hashes, raw = read_bundle(directory)
        original = generation(payload,request_id,mode=flow.config.mode,
            dataset=flow.dataset.metadata,provider=flow.config.provider)
        prepared.append({**original,'id':f'imported/h/{index}',
            'origin':{'source_run':str(Path(directory).resolve()),'request_id':request_id,
                      'snapshot':f'imported_sources/{index}','file_sha256':hashes},'raw':raw})
    if len({r['candidate']['key'] for r in prepared}) != 2:
        raise ValueError('duplicate source h; no paid refill or silent reduction')
    plan_rows = [{k:v for k,v in r.items() if k != 'raw'} for r in prepared]
    plan_path = flow.directory/'H_import_plan.json'
    if plan_path.exists():
        if flow.read(plan_path.name,'Integration_smoke_H_import_plan')['rows'] != plan_rows:
            raise ValueError('source import plan changed; use a new acceptance directory')
    else:
        for r in prepared:
            folder = flow.directory/r['origin']['snapshot']
            folder.mkdir(parents=True,exist_ok=True)
            for name,data in r['raw'].items():
                path = folder/name
                if path.exists() and path.read_bytes() != data:
                    raise ValueError('existing source snapshot differs; not overwritten')
                if not path.exists():
                    path.write_bytes(data)
        flow.write(plan_path.name,'Integration_smoke_H_import_plan',rows=plan_rows,
            notice='Original generation evidence only; all train is re-evaluated here; human review remains pending.')
    if (flow.directory/'h_requests.json').exists():
        raise ValueError('do not mix fresh h requests and imported sources in one acceptance run')
    flow.dataset.verify('train')
    rows = []
    from .assets import checked_candidate
    for base in plan_rows:
        check_imported_row(flow,base)
        candidate = checked_candidate(base['candidate'],'h')
        if flow._train is None:
            flow._train = flow.dataset.load('train')
        result = flow.cache.get(digest({'candidate':candidate.key,'H':[]}),flow.dataset.names['train'],
            lambda:flow.dataset.evaluate(candidate,(),'train',timeout=flow.config.instance_timeout,instances=flow._train))
        if not result['valid']:
            flow.report('STOPPED','imported h failed fresh complete train; old failure/evidence remains unchanged')
            raise ValueError('imported h failed fresh complete train; no partial fitness or automatic retry')
        row = {**base,'training_result':result,'fitness':result['fitness'],
               'scores':[r['score'] for r in result['instances']]}
        rows.append(row)
        flow.write('H_import_progress.json','Integration_smoke_H_import_progress',rows=rows,
            required_members=2,human_review_completed=False)
    flow._check_rows(rows,'h')
    name = 'Smoke_h_candidates.json'
    if (flow.directory/name).exists():
        source = flow.read(name,'Integration_smoke_h_candidates')
        if source['rows'] != rows:
            raise ValueError('existing H candidates differ; not overwritten')
    else:
        source = flow.write(name,'Integration_smoke_h_candidates',rows=rows,
            training_files=list(flow.dataset.names['train']))
    write_review_packet(flow.directory,rows,flow.dataset.names['train'],mode=flow.config.mode,
        context=flow.context,source_hash=source['artifact_sha256'],timeout=flow.config.review_timeout)
    return flow.report('HUMAN_REVIEW_REQUIRED',
        'two original generated h re-evaluated on all train; no new requests; actual human review required before U')
