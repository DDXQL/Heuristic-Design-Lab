"""Batch fitness for EoH-S constructive FJSP heuristics."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable, Sequence

from llm4ad.base import Evaluation

from .instances import FJSPInstance, load_instance
from .scheduler import Schedule, construct_schedule
from .template import task_description, template_program


class FJSPSetEvaluation(Evaluation):
    def __init__(self, instance_paths: Sequence[str | Path], *, timeout_seconds: int = 60):
        if not instance_paths:
            raise ValueError('training batch must contain at least one instance')
        super().__init__(template_program=template_program,
                         task_description=task_description,
                         timeout_seconds=timeout_seconds)
        self.instance_paths = tuple(str(Path(path).resolve()) for path in instance_paths)
        if len(set(self.instance_paths)) != len(self.instance_paths):
            raise ValueError('training batch contains duplicate paths')
        self._datasets = tuple(load_instance(path) for path in self.instance_paths)

    @property
    def instances(self) -> tuple[FJSPInstance, ...]:
        return self._datasets

    @staticmethod
    def score_makespan(instance: FJSPInstance, makespan: int) -> float:
        if makespan < 1 or instance.lower_bound < 1:
            raise ValueError('makespan and lower bound must be positive')
        score = -float(makespan) / instance.lower_bound
        if not math.isfinite(score):
            raise ValueError('non-finite instance score')
        return score

    def evaluate_instance(self, instance: FJSPInstance,
                          priority: Callable[..., float]) -> tuple[Schedule, float]:
        schedule = construct_schedule(instance, priority)
        return schedule, self.score_makespan(instance, schedule.makespan)

    def evaluate(self, priority: Callable[..., float]) -> list[float]:
        return [self.evaluate_instance(instance, priority)[1] for instance in self._datasets]

    def evaluate_program(self, program_str: str, callable_func: Callable[..., float],
                         **kwargs) -> Any | None:
        try:
            return self.evaluate(callable_func)
        except Exception as exc:
            print(f'FJSP candidate invalid: {type(exc).__name__}: {exc}', flush=True)
            return None
