#!/usr/bin/env python3
"""Controlled-runtime source/target comparison on independent <=7-city toys."""
import argparse
import json
from pathlib import Path
import socket
import sys
from dataclasses import asdict

p=argparse.ArgumentParser();p.add_argument('--code-root',required=True);p.add_argument('--fixtures',required=True);p.add_argument('--out',required=True);a=p.parse_args()
root=Path(a.code_root).resolve();sys.path[:0]=[str(root),str(root/'code')]
def denied(*args,**kwargs):raise AssertionError('NO NETWORK IN TOY REGRESSION')
socket.socket.connect=denied;socket.create_connection=denied
from heuristic_design.problems.tsp.candidates import checked,compile_candidate,U_ARGS,H_ARGS
from heuristic_design.problems.tsp.solver import distances,construct,nearest_neighbor
import numpy
fixture=json.loads(Path(a.fixtures).read_text())
if tuple(fixture['fixture_runtime']['python_major_minor'])!=tuple(sys.version_info[:2]):raise ValueError('use the declared common runtime; do not reinterpret historical AST keys')
members=fixture['H'];k=len(members)
hs=[compile_candidate(checked(c,k),k) for c in members]
records=[]
for name,coordinates in fixture['coordinates'].items():
    matrix=distances(coordinates);nn_tour,nn_length=nearest_neighbor(matrix)
    for label,policy in fixture['policies'].items():
        u=compile_candidate(checked(policy,k),k)
        first=construct(matrix,hs,u);second=construct(matrix,hs,u);assert first==second
        records.append({'toy':name,'policy':label,'first':asdict(first),'recheck':asdict(second),'NN_tour':nn_tour,'NN_length':nn_length,'fitness':-first.length/nn_length})
result={'code_root':str(root),'runtime':{'python':sys.version.split()[0],'numpy':numpy.__version__},'semantics':{'U_ARGS':U_ARGS,'H_ARGS':H_ARGS,'records':records},'API_calls':0,'formal_instances':0}
Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
print(json.dumps({'code_root':str(root),'pairs':len(records),'cities':[len(c) for c in fixture['coordinates'].values()],'API_calls':0,'formal_instances':0}))
