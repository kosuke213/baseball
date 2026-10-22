from collections import Counter
from ..completion.records import Scorebook as PreviousScorebook, COVERAGE

class Scorebook(PreviousScorebook):
    def __init__(self,*args):
        super().__init__(*args);self.timing_sources=Counter();self.cancelled_outs=0;self.actual_results=Counter()
    def observe(self,before,applied):
        super().observe(before,applied)
        self.timing_sources[applied.timing_source]+=1;self.cancelled_outs+=len(applied.cancelled_out_ids)
        self.actual_results[applied.actual_result or applied.transition.plan.outcome]+=1
    def export(self,*args):
        r=super().export(*args)
        r['scoring_status'].update(coverage_version='stability-coverage-1',full_official_record=False)
        r['timing_provenance']={'actions':dict(self.timing_sources),'cancelled_outs_after_game_end':self.cancelled_outs,
                                'actual_result_counts':dict(self.actual_results)}
        return r
