"""Reuse parent selection, ten slots and survival; only parser/prompt are new."""
from fjsp_usage.research.evolution import Search
from fjsp_usage.research.candidates import parse_response
from fjsp_usage.research_real.search import V5BudgetedSearch
from fjsp_usage.research_real.initialization import initialization_prompt
from .prompts import build_prompt,NOVELTY
from . import VERSION

class UsageSearch(V5BudgetedSearch):
    _build_prompt=staticmethod(build_prompt)
    def _parse_candidate(self,text,*,kind='U'):
        return parse_response(text,kind=kind,interface_version=VERSION,member_count=len(self.members))
    def _initial_prompt(self,prompt,index):
        return initialization_prompt(prompt,self.state['population'],index,
            instruction=NOVELTY,interface_version=VERSION)
    def _duplicate_of(self,candidate):
        return Search._duplicate_of(self,candidate)  # AST only; never old integer equivalence
