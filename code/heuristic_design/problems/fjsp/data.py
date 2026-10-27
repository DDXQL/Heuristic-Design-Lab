"""Existing FJSP parser only; no automatic split generation or holdout read."""
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, load_instance

__all__ = ['FJSPInstance', 'load_instance']
