"""Compatibility with original rank sampling; generic result completeness."""
import random
import unittest
from heuristic_design.core.search import select_parents, survive
from heuristic_design.core.results import validate_complete
from fjsp_usage.research.evolution import select_parents as legacy


class Tests(unittest.TestCase):
    def test_selection_matches_original_random_stream(self):
        pop=[{'id':str(i),'fitness':float(i//2)} for i in range(5)]
        for seed in range(20):
            a,b=random.Random(seed),random.Random(seed)
            for n in (2,1,5,3):self.assertEqual(select_parents(pop,n,a),legacy(pop,n,b))
            self.assertEqual(a.getstate(),b.getstate())
        self.assertEqual([r['id'] for r in survive(pop,[],2)],['4','2'])

    def test_partial_never_gets_full_fitness(self):
        instances=[{'file':'a'},{'file':'b'}]
        r={'valid':True,'fitness':-1.,'total_instances':2,'instances':[{'file':'a','score':-1.}]}
        with self.assertRaises(ValueError):validate_complete(r,instances)
        r.update(valid=False,fitness=None);validate_complete(r,instances)
