"""Frozen PCG64 uniform float64 coordinates with independent split seeds."""
from pathlib import Path
import numpy as np
from heuristic_design.core.storage import write,read,sha,digest

SPLITS={'train':(20,50,2026102601),'validation':(10,50,2026102602),'confirmation':(20,50,2026102603),'transfer':(10,100,2026102604)}


def generate(directory):
    directory=Path(directory)
    if directory.exists():raise ValueError('data directory must be new')
    directory.mkdir(parents=True);manifest={};seen=set()
    for split,(count,n,seed) in SPLITS.items():
        rng=np.random.Generator(np.random.PCG64(seed));rows=[]
        for i in range(count):
            coordinates=rng.random((n,2),dtype=np.float64).tolist();content=digest(coordinates)
            if content in seen:raise ValueError('duplicate coordinates')
            seen.add(content);name=f'{split}_{i:03d}.json';path=directory/split/name
            write(path,{'coordinates':coordinates})
            rows.append({'file':name,'path':str(path.relative_to(directory)),'sha256':sha(path),'coordinate_sha256':content,'cities':n,'seed':seed,'index':i})
        manifest[split]=rows
    write(directory/'Manifest.json',{'generator':'numpy PCG64 float64 uniform [0,1)','numpy':np.__version__,'splits':manifest,'unique_coordinate_sets':len(seen)})
    return manifest
