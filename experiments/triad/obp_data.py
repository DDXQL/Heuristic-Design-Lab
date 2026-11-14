"""Import the exact published TRAINING asset after explicit adoption; never test."""
import hashlib
import importlib
import io
import json
from pathlib import Path
import pickle
import re
import numpy as np
from heuristic_design.core.storage import read,write,sha
from .problems import validate_obp_instance,obp_reference_details
TRAIN_SHA='6ef362b59973163225579e26e5e49f6196579287ff7a3eab0609693db4e25513'
TRAIN_BLOB='860afc93ecb15492b1d8c5f7781fc5d90adb0f47'


class _PublishedNumpyOnly(pickle.Unpickler):
    def find_class(self,module,name):
        allowed={('numpy','ndarray'),('numpy','dtype')}
        allowed|={(m,n) for m in ('numpy.core.multiarray','numpy._core.multiarray') for n in ('_reconstruct','scalar')}
        allowed|={(m,'_frombuffer') for m in ('numpy.core.numeric','numpy._core.numeric')}
        if (module,name) not in allowed:raise ValueError('unsupported published pickle global: '+module+'.'+name)
        return getattr(importlib.import_module(module),name)


def prepare(source,spec_path,output):
    spec=read(spec_path)
    if spec.get('adopted') is not True:raise PermissionError('OBP data split/reference recommendation is NOT adopted')
    if spec.get('source_kind')!='published_training_only' or spec.get('source_sha256')!=TRAIN_SHA or spec.get('source_git_blob')!=TRAIN_BLOB:raise ValueError('only the exact published training asset is accepted; test file is never opened')
    groups={name:spec[name+'_indices'] for name in ('train','validation')}
    all_ids=[i for values in groups.values() for i in values]
    if any(type(i) is not int or i<0 for i in all_ids) or len(all_ids)!=len(set(all_ids)) or sorted(all_ids)!=list(range(spec['expected_instances'])):raise ValueError('explicit disjoint complete natural instance split required')
    raw=Path(source).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=TRAIN_SHA or hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=TRAIN_BLOB:raise ValueError('published training SHA/Git blob mismatch; no repair or regeneration')
    dataset=_PublishedNumpyOnly(io.BytesIO(raw)).load();records={}
    def collect(value,path=()):
        if not isinstance(value,dict):return
        if 'capacity' in value and 'items' in value:
            match=re.fullmatch(r'instance_(\d+)',str(path[-1]) if path else '')
            if not match:raise ValueError('explicit instance_i source identity required')
            index=int(match.group(1))
            if index in records:raise ValueError('duplicate natural instance ID')
            records[index]=value;return
        for key,child in value.items():collect(child,path+(key,))
    collect(dataset)
    if sorted(records)!=list(range(spec['expected_instances'])):raise ValueError('source instance count / natural IDs differ; do not silently drop')
    prepared={};details={};dtypes={}
    for i,record in sorted(records.items()):
        array=np.asarray(record['items'])
        if array.ndim!=1 or array.dtype.kind not in 'iu':raise ValueError('one-dimensional integer arrivals required')
        count=next((record[k] for k in ('N','num_items','n_items') if k in record),None)
        if not isinstance(count,(int,np.integer)) or isinstance(count,(bool,np.bool_)) or int(count)!=len(array):raise ValueError('declared public N differs from items')
        capacity=record['capacity']
        if not isinstance(capacity,(int,np.integer)) or isinstance(capacity,(bool,np.bool_)):raise ValueError('integer capacity required')
        value={'N':int(count),'capacity':int(capacity),'items':[int(x) for x in array.tolist()]}
        validate_obp_instance(value);details[i]=obp_reference_details(value,spec['reference']);prepared[i]=value;dtypes[i]=str(array.dtype)
    out=Path(output)
    if out.exists():raise FileExistsError('new OBP data version directory required; preserve original')
    out.mkdir(parents=True)
    for split,ids in groups.items():
        rows=[]
        for i in ids:
            path=out/'instances'/f'instance_{i}.json';write(path,prepared[i]);rows.append({'file':f'instance_{i}','path':str(path.relative_to(out)),'sha256':sha(path),'source_instance_id':i,'source_items_dtype':dtypes[i],'reference_precheck':details[i]})
        write(out/(split+'.manifest.json'),{'problem':'obp','split':split,'instances':rows,'source_sha256':TRAIN_SHA,'source_git_blob':TRAIN_BLOB,'adopted_spec_sha256':sha(spec_path),'numeric_precheck_only':True,'no_method_scores':True})
    write(out/'exposure.json',{'training_source_read':True,'train_and_validation_numeric_reference_precheck':True,'H_or_U_called':False,'actual_solves':0,'test_file_opened_by_this_importer':False,
      'prior_test_access':'protocol page reported numeric/reference-only access to all 50 published test instances; no method evaluation; do not call test unseen'})
    return {'output':str(out),'train_manifest':str(out/'train.manifest.json'),'validation_manifest':str(out/'validation.manifest.json'),'prechecked_instances':len(records),'API_requests':0,'actual_solves':0,'H_executions':0}
