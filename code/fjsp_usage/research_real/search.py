"""Budgeted adapter reusing the unchanged, tested generational Search engine."""

from fjsp_usage.research.evolution import Search
from .budget import BudgetJournal
from .assets import checked_candidate, make_receipt, check_result
from .prompts import build_prompt as build_v5_prompt
from .initialization import initialization_prompt, selector_signature
from .state_diagnostics import static_diagnostics


class BudgetedSearch(Search):
    def __init__(self, directory, *, init_phase, search_phase, ledger, experiment,
                 training_names, **kwargs):
        self.training_names = tuple(training_names)
        self.experiment = experiment
        self.ledger = ledger
        super().__init__(directory, **kwargs)
        self.initial_requests = BudgetJournal(self.directory / 'budgeted_initial_requests.json',
            phase=init_phase, cap=self.config.initialization_cap, transport=kwargs['transport'], ledger=ledger)
        self.evolution_requests = BudgetJournal(self.directory / 'budgeted_evolution_requests.json',
            phase=search_phase, cap=self.config.generations * self.config.attempts_per_generation,
            transport=kwargs['transport'], ledger=ledger)

    def _evaluate_once(self, identifier, candidate):
        result = super()._evaluate_once(identifier, candidate)
        if not result.get('valid') and 'total_instances' not in result:
            result.update(total_instances=len(self.training_names), instances=[])
            self._save()
        check_result(result, self.training_names)
        return result

    def export_rows(self):
        rows = []
        for row in self.state['population']:
            # Shared initial rows already carry their own source receipt/results;
            # they are not reattributed to a request in this arm.
            if 'receipt' in row and 'training_result' in row:
                rows.append(row)
                continue
            candidate = checked_candidate(row['candidate'], self.kind)
            journal = self.initial_requests if '/init/' in row['id'] else self.evolution_requests
            record = journal.data['requests'][row['id']]
            receipt = make_receipt(candidate, record, self.ledger, self.experiment, journal.transport.identity)
            result = self.state['evaluations'][row['id']]['result']
            check_result(result, self.training_names)
            rows.append({**row, 'receipt': receipt, 'training_result': result})
        return rows


class V5BudgetedSearch(BudgetedSearch):
    """New staged experiments use the current V5 pack; DeepSeek pilot stays v1."""

    _build_prompt = staticmethod(build_v5_prompt)

    def _attempt(self):
        # Metadata only: superclass alone consumes the slot, validates/evaluates
        # and updates the population. No diagnostics enter selection or prompts.
        pending = dict(self.state['inflight'])
        super()._attempt()
        outcome = self.state['attempts'][-1]
        status = outcome['status']
        category = {'valid':'valid','invalid':'runtime_failure',
                    'failed':'api_failure','interrupted':'interrupted_request',
                    'parse_or_constraint_error':'parse_failure'}.get(status,status)
        journal = self.initial_requests if pending['initial'] else self.evolution_requests
        record = journal.data['requests'][pending['id']]
        if record['status'] == 'completed':
            from fjsp_usage.research.candidates import parse_response, CandidateError
            try:
                candidate = self._parse_candidate(record['text'], kind=self.kind)
            except CandidateError as exc:
                # Envelope errors and validated-code/interface errors are kept
                # separate; neither is charged as a runtime/evaluation failure.
                try:
                    import re
                    match = re.fullmatch(r'\s*\{([^{}]+)\}\s*```python\s*\n(.*?)\n```\s*',
                                         record['text'], flags=re.DOTALL)
                except (TypeError, ValueError):
                    match = None
                category = 'interface_or_code_constraint_failure' if match and not (
                    'description must' in str(exc) or 'response must' in str(exc)) else 'parse_failure'
            else:
                if status == 'duplicate':
                    category = 'code_duplicate' if candidate.key in self.state['seen'] else 'narrow_equivalence_duplicate'
                if self.kind == 'U':
                    outcome['selector_diagnostics'] = static_diagnostics(candidate.code, len(self.members),
                        interface_version=getattr(candidate, 'interface_version', None))
        outcome['category'] = category
        self._save()

    def _initial_prompt(self, prompt, index):
        if self.kind == 'U' and self.arm == 'INIT':
            return initialization_prompt(prompt, self.state['population'], index)
        return prompt

    def _duplicate_of(self, candidate):
        previous = super()._duplicate_of(candidate)
        if previous or self.kind != 'U' or self.arm != 'INIT':
            return previous
        if not self.state['inflight']['initial']:
            return None
        signature = selector_signature(candidate.code)
        for row in self.state['population']:
            if selector_signature(row['candidate']['code']) == signature:
                return row['id']
        return None
