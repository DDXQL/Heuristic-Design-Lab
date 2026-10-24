"""Independent Baseline-A supplemental T30; no historical mutations."""
VERSION = 'Baseline-A-Supplemental-T30-complete-receive-v1-20261024'
ORDER = ('H0_H1_WS','H0_H4_WS','H4_H5_WS','H0','H4_H6_WS',
         'H4_H7_WS','H0_H3_WS','H5_H6_WS','H5_H7_WS')


def specs():
    from fjsp_usage.baseline_a.policies import specs as original
    rows = {s['id']:s for s in original()}
    return [rows[n] for n in ORDER]
