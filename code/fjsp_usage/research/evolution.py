"""Bounded generational search, injectable transport/evaluator, durable resume.

All candidates come from one response each. Invalid/duplicate attempts consume
slots. A generation freezes parents until its single survival update. Interrupted
requests/evaluations become invalid, rather than being repeated or repaired.
"""

from dataclasses import asdict
import json
import math
from pathlib import Path
import random

from .candidates import Candidate, CandidateError, parse_response
from .events import Events, atomic_json
from .prompts import build_prompt
from .protocol import digest
from .requests import RequestJournal
from .sets import complementary_parents, complementary_survival, ranked


def _tuple_tree(value):
    return tuple(_tuple_tree(item) for item in value) if isinstance(value, list) else value


def select_parents(population, count, rng):
    pool = ranked(population)
    if count > len(pool):
        raise ValueError('not enough distinct parents')
    # Weights use ranks in the ORIGINAL frozen generation. Deleting selected
    # parents must not recompute ranks/N for those that remain.
    weights = [1 / (len(pool) + rank) for rank in range(len(pool))]
    chosen = []
    for _ in range(count):
        index = rng.choices(range(len(pool)), weights=weights, k=1)[0]
        chosen.append(pool.pop(index))
        weights.pop(index)
    return chosen


def operator_at(arm, index, attempts):
    if arm in ('B0', 'B1'):
        return ('E1', 'E2', 'M1', 'M2', 'M3')[index // (attempts // 5)]
    if arm == 'H':
        return 'E1' if index < attempts // 2 else 'M1'
    return 'CROSS' if index < attempts // 2 else 'MUTATE'


class Search:
    # The legacy default remains unchanged; explicit experiment subclasses can
    # install a versioned prompt pack without changing research_v1 semantics.
    _build_prompt = staticmethod(build_prompt)
    _parse_candidate = staticmethod(parse_response)

    def __init__(self, directory, *, arm, config, members, evaluator,
                 transport, context, kind='U', initial=None):
        if arm not in ('B0', 'B1', 'B2', 'P', 'H', 'INIT', 'A', 'B'):
            raise ValueError('unknown search arm')
        if (kind == 'h') != (arm == 'H'):
            raise ValueError('H search must use h candidates')
        self.directory = Path(directory)
        self.path = self.directory / 'checkpoint.json'
        self.arm, self.kind, self.config = arm, kind, config
        self.members, self.evaluator = tuple(members), evaluator
        self.events = Events(self.directory / 'events.jsonl')
        self.signature = digest({'arm': arm, 'kind': kind, 'config': asdict(config),
                                 'H': [m.key for m in members], 'context': context,
                                 'transport': transport.identity, 'initial': initial})
        self.rng = random.Random(config.seed)
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
            if self.state['signature'] != self.signature:
                raise ValueError('resume rejected: source, data, H, initial population or protocol changed')
            self.rng.setstate(_tuple_tree(self.state['rng']))
        else:
            if initial is not None and len(initial) != config.population_size:
                raise ValueError('shared initial population must contain exactly N members')
            population = list(initial or [])
            self.state = {'signature': self.signature, 'population': ranked(population),
                          'children': [], 'generation': 0, 'cursor': 0, 'init_cursor': 0,
                          'phase': 'evolution' if initial is not None else 'initialization',
                          'inflight': None, 'seen': {p['candidate']['key']: p['id'] for p in population},
                          'evaluations': {}, 'attempts': [], 'rng': self.rng.getstate()}
            self._save()
        self.initial_requests = RequestJournal(self.directory / 'initial_requests.json',
            cap=config.initialization_cap, transport=transport, identity=transport.identity)
        self.evolution_requests = RequestJournal(self.directory / 'evolution_requests.json',
            cap=config.generations * config.attempts_per_generation,
            transport=transport, identity=transport.identity)

    def _save(self):
        self.state['rng'] = self.rng.getstate()
        atomic_json(self.path, self.state)

    def _evaluate_once(self, identifier, candidate):
        cache = self.state['evaluations']
        if identifier in cache:
            if cache[identifier]['status'] == 'pending':
                cache[identifier] = {'status': 'completed', 'result': {
                    'valid': False, 'fitness': None, 'error_type': 'InterruptedEvaluation',
                    'error': 'uncertain interrupted evaluation; no repeat'}}
                self._save()
            return cache[identifier]['result']
        cache[identifier] = {'status': 'pending'}
        self._save()
        try:
            result = self.evaluator(candidate)
        except Exception as exc:
            result = {'valid': False, 'fitness': None, 'error_type': type(exc).__name__,
                      'error': str(exc)[:500]}
        if result.get('valid'):
            records = result.get('instances', [])
            if (len(records) != result.get('total_instances') or not records
                    or not isinstance(result.get('fitness'), (int, float))
                    or not math.isfinite(result['fitness'])
                    or not all(math.isfinite(row['score']) for row in records)):
                raise ValueError('evaluator returned incomplete/nonfinite fitness')
        cache[identifier] = {'status': 'completed', 'result': result}
        self._save()
        return result

    def _attempt(self):
        pending = self.state['inflight']
        identifier = pending['id']
        journal = self.initial_requests if pending['initial'] else self.evolution_requests
        record = journal.request(identifier, pending['prompt'], kind=self.kind)
        outcome = {'id': identifier, 'operator': pending['operator'],
                   'parents': pending['parents'], 'status': record['status']}
        child = None
        if record['status'] == 'completed':
            try:
                candidate = self._parse_candidate(record['text'], kind=self.kind)
                previous = self._duplicate_of(candidate)
                if previous and previous != identifier:
                    outcome.update(status='duplicate', code_key=candidate.key,
                                   duplicate_of=previous)
                else:
                    self.state['seen'][candidate.key] = identifier
                    self._save()
                    result = self._evaluate_once(identifier, candidate)
                    outcome.update(status='valid' if result['valid'] else 'invalid',
                                   code_key=candidate.key, error_type=result.get('error_type'))
                    if result['valid']:
                        child = {'id': identifier, 'candidate': asdict(candidate),
                                 'fitness': result['fitness'],
                                 'scores': [r['score'] for r in result['instances']]}
            except CandidateError as exc:
                outcome.update(status='parse_or_constraint_error', error=str(exc))
        else:
            outcome['error'] = record.get('error')
        self.state['attempts'].append(outcome)
        if child:
            target = 'population' if pending['initial'] else 'children'
            self.state[target].append(child)
        if pending['initial']:
            self.state['init_cursor'] += 1
        else:
            self.state['cursor'] += 1
        self.state['inflight'] = None
        self._save()
        self.events.emit('candidate', arm=self.arm, **outcome)

    def _duplicate_of(self, candidate):
        """Default source-key policy; specialised initialisers may tighten it."""
        return self.state['seen'].get(candidate.key)

    def _initial_prompt(self, prompt, index):
        """Legacy and H initialisation retain their original prompt."""
        return prompt

    def _prepare(self, *, initial):
        if self.state['inflight'] is not None:
            return
        index = self.state['init_cursor'] if initial else self.state['cursor']
        operator = 'I1' if initial else operator_at(self.arm, index, self.config.attempts_per_generation)
        if initial:
            parents = []
        elif self.arm == 'H' and operator == 'E1':
            parents = complementary_parents(self.state['population'], self.rng)
        else:
            count = self.config.cross_parents if operator in ('E1', 'E2', 'CROSS') else 1
            parents = select_parents(self.state['population'], count, self.rng)
        prefix = 'init' if initial else f'g{self.state["generation"]:04d}'
        identifier = f'{self.arm}/{prefix}/{index:06d}'
        prompt = self._build_prompt('B0' if self.arm == 'INIT' else self.arm,
                              operator, parents, self.members, kind=self.kind)
        if initial:
            prompt = self._initial_prompt(prompt, index)
        self.state['inflight'] = {'id': identifier, 'operator': operator, 'prompt': prompt,
                                  'parents': [p['id'] for p in parents], 'initial': initial}
        self._save()

    def initialize(self, *, stop_after_attempts=None):
        if stop_after_attempts is not None and (type(stop_after_attempts) is not int or stop_after_attempts < 1):
            raise ValueError('initialization request window must be a positive integer')
        steps = 0
        while self.state['phase'] == 'initialization':
            if len(self.state['population']) == self.config.population_size:
                self.state['population'] = ranked(self.state['population'])
                self.state['phase'] = 'evolution'
                self._save()
                self.events.emit('initialized', arm=self.arm, count=len(self.state['population']))
                break
            if self.state['init_cursor'] >= self.config.initialization_cap:
                self.state['phase'] = 'initialization_failed'
                self._save()
                self.events.emit('initialization_failed', arm=self.arm,
                                 valid=len(self.state['population']), required=self.config.population_size)
                break
            if stop_after_attempts is not None and steps >= stop_after_attempts:
                self.events.emit('initialization_paused', arm=self.arm,
                                 requests_this_window=steps, cursor=self.state['init_cursor'])
                return None
            self._prepare(initial=True)
            self._attempt()
            steps += 1
        return self.state['phase'] != 'initialization_failed'

    def run(self, *, stop_after_attempts=None):
        if not self.initialize():
            return self.report()
        steps = 0
        while self.state['generation'] < self.config.generations:
            if stop_after_attempts is not None and steps >= stop_after_attempts:
                return self.report()
            if self.state['cursor'] < self.config.attempts_per_generation:
                self._prepare(initial=False)
                self._attempt()
                steps += 1
                continue
            combined = self.state['population'] + self.state['children']
            self.state['population'] = (complementary_survival(combined, self.config.population_size)
                                        if self.arm == 'H' else ranked(combined)[:self.config.population_size])
            self.state['children'] = []
            self.state['cursor'] = 0
            self.state['generation'] += 1
            self._save()
            self.events.emit('generation', arm=self.arm, generation=self.state['generation'],
                             population_ids=[p['id'] for p in self.state['population']])
        self.state['phase'] = 'completed'
        self._save()
        return self.report()

    def report(self):
        outcomes = self.state['attempts']
        return {'arm': self.arm, 'phase': self.state['phase'], 'generation': self.state['generation'],
                'initialization_requests': self.initial_requests.calls,
                'evolution_requests': self.evolution_requests.calls,
                'evaluations_reserved': len(self.state['evaluations']),
                'valid_attempts': sum(row['status'] == 'valid' for row in outcomes),
                'attempts': len(outcomes), 'population': self.state['population']}
