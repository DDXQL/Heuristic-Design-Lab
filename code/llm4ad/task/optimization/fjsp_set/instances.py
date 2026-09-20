"""Read the local EvoFlow/Brandimarte-style FJSP text format."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Operation:
    # Machine indices are zero-based internally; durations are positive integers.
    alternatives: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class FJSPInstance:
    name: str
    machine_count: int
    jobs: tuple[tuple[Operation, ...], ...]

    @property
    def operation_count(self) -> int:
        return sum(len(job) for job in self.jobs)

    @property
    def lower_bound(self) -> int:
        shortest_by_job = [sum(min(duration for _, duration in op.alternatives)
                               for op in job) for job in self.jobs]
        total = sum(shortest_by_job)
        return max(max(shortest_by_job), (total + self.machine_count - 1) // self.machine_count)


def load_instance(path: str | Path) -> FJSPInstance:
    """Load one instance; reject malformed or ambiguous operation records."""
    path = Path(path)
    lines = [line.strip() for line in path.read_text(encoding='utf-8').splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    try:
        section_index = lines.index('JOB_SECTION')
        header = {}
        for line in lines[:section_index]:
            key, value = line.split(':', 1)
            if key in header:
                raise ValueError(f'duplicate header {key}')
            header[key] = value.strip()
        if header['TYPE'] != 'FJSP':
            raise ValueError('TYPE must be FJSP')
        job_count = int(header['JOBS'])
        machine_count = int(header['MACHINES'])
        if job_count < 1 or machine_count < 1:
            raise ValueError('JOBS and MACHINES must be positive')
        job_lines = lines[section_index + 1:]
        if len(job_lines) != job_count:
            raise ValueError(f'expected {job_count} job records, got {len(job_lines)}')

        jobs = []
        for job_index, line in enumerate(job_lines):
            tokens = [int(value) for value in line.split()]
            if not tokens or tokens[0] < 1:
                raise ValueError(f'job {job_index} has no operations')
            operation_count = tokens[0]
            cursor = 1
            operations = []
            for _ in range(operation_count):
                if cursor >= len(tokens):
                    raise ValueError(f'job {job_index} ends before all operations')
                alternative_count = tokens[cursor]
                cursor += 1
                if alternative_count < 1 or cursor + 2 * alternative_count > len(tokens):
                    raise ValueError(f'job {job_index} has invalid alternatives')
                alternatives = []
                for _ in range(alternative_count):
                    machine_number, duration = tokens[cursor:cursor + 2]
                    cursor += 2
                    if not 1 <= machine_number <= machine_count or duration < 1:
                        raise ValueError(f'job {job_index} has invalid machine or duration')
                    alternatives.append((machine_number - 1, duration))
                if len({machine for machine, _ in alternatives}) != len(alternatives):
                    raise ValueError(f'job {job_index} repeats a machine')
                operations.append(Operation(tuple(sorted(alternatives))))
            if cursor != len(tokens):
                raise ValueError(f'job {job_index} has trailing data')
            jobs.append(tuple(operations))
        return FJSPInstance(header.get('NAME', path.stem), machine_count, tuple(jobs))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f'invalid FJSP instance {path}: {exc}') from exc
