"""Budgeted adapter reusing the unchanged, tested generational Search engine."""

from fjsp_usage.research.evolution import Search
from .budget import BudgetJournal
from .assets import checked_candidate, make_receipt, check_result


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
