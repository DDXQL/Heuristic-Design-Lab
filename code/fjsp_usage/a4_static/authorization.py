"""Current turn creates no approval. A later human authorization is required."""
from . import VERSION,SEARCH_SEEDS,QUERIES,LOGICAL_EVALUATIONS,SOLVE_PASSES


def require_approval(value):
    expected={'approved':True,'version':VERSION,'allow_new_FJSP':True,'LLM_API_cap':0,
        'queries_per_repeat':QUERIES,'search_seeds':list(SEARCH_SEEDS),'solve_seed':501,
        'new_evaluation_cap':LOGICAL_EVALUATIONS,'new_solve_pass_cap':SOLVE_PASSES,
        'instance_result_seconds':30,'wall_launch_budget_seconds':21600}
    if any(type(value.get(k)) is not type(v) or value[k]!=v for k,v in expected.items()):
        raise PermissionError('Future explicit A4 authorization for exact scope is required; no historical approval inherited')
    if not isinstance(value.get('user_instruction_reference'),str) or not value['user_instruction_reference'].strip():
        raise PermissionError('Actual future human instruction reference required')
    return value
