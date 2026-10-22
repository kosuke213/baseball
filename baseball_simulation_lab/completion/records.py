"""Supported official definitions are distinguished from simulator event counts."""
from ..fullgame.records import Scorebook as Stage8Scorebook

COVERAGE_VERSION = 'scoring-coverage-1'
COVERAGE = {
 'pa_ab': {'level':'B','condition':'complete windows; no mid-count batter replacement; OBR 9.02(a)'},
 'h_double_triple_hr': {'level':'B','condition':'source scorer credit or declared fixed advancement; limited walkoff 9.06(f)'},
 'bb_hbp_k': {'level':'B','condition':'complete PA credit; no mid-count attribution; OBR 9.14, 9.15'},
 'runs': {'level':'B','condition':'identified scorers and adjudicated/known timing; OBR 5.08, 9.02(a)'},
 'rbi': {'level':'B','condition':'per-scorer source flags or explicit unambiguous assumption; errors never inferred; OBR 9.04'},
 'pitching_outs_ip': {'level':'A','condition':'integer outs are authoritative; .1 means 1/3 inning; OBR 9.02(c)'},
 'hits_allowed': {'level':'B','condition':'verified hitter credits; OBR 9.02(c)'},
 'runs_allowed': {'level':'B','condition':'known inherited-runner responsibility, simple FC transfer; OBR 9.16(g)'},
 'earned_runs': {'level':'C','condition':'error-free inning reconstruction unimplemented'},
 'pitcher_win_loss': {'level':'B','condition':'starter five-inning rule, one reliever; discretionary relief cases remain manual; OBR 9.17'},
 'save_hold': {'level':'C','condition':'not implemented; hold is not a uniform OBR statistic'},
 'baserunning_stats': {'level':'C','condition':'runner identities tracked; full SB/CS/advancement official credits not implemented'},
}

class Scorebook(Stage8Scorebook):
    def export(self, frame, status):
        result=super().export(frame,status)
        result['scoring_status'].update(coverage_version=COVERAGE_VERSION,
            official_scope='MLB OBR reference definitions; experimental counts, not NPB-certified records')
        return result
