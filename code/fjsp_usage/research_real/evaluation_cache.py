"""Whole-batch durable evaluation reservation; uncertain work is never rerun."""

import json
from pathlib import Path

from fjsp_usage.research.events import atomic_json
from .assets import check_result


class EvaluationCache:
    def __init__(self, path, identity):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {
            'identity': identity, 'records': {}}
        if self.data['identity'] != identity:
            raise ValueError('evaluation cache context mismatch')

    def get(self, key, names, evaluate):
        records = self.data['records']
        if key in records:
            if records[key]['status'] == 'pending':
                records[key] = {'status': 'completed', 'result': {
                    'valid': False, 'fitness': None, 'total_instances': len(names),
                    'instances': [], 'error_type': 'InterruptedEvaluation',
                    'error': 'uncertain interrupted evaluation; no repeat'}}
                atomic_json(self.path, self.data)
            return check_result(records[key]['result'], names)
        records[key] = {'status': 'pending'}
        atomic_json(self.path, self.data)
        try:
            result = evaluate()
        except Exception as exc:
            result = {'valid': False, 'fitness': None, 'total_instances': len(names),
                      'instances': [], 'error_type': type(exc).__name__,
                      'error': 'local evaluator failed; inspect stage logs'}
        check_result(result, names)
        records[key] = {'status': 'completed', 'result': result}
        atomic_json(self.path, self.data)
        return result
