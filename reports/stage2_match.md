# Stage 2 — matching to tickers (2026-10-06)

Input events (excluding NJ): **5198**. Matched to a public company (NYSE/Nasdaq): **1213** (23.3%), unique tickers 412.

| Status | Events |
|---|---|
| unmatched | 3672 |
| auto | 893 |
| confirmed | 320 |
| rejected_manual | 250 |
| rejected | 63 |

| Method (accepted) | Events |
|---|---|
| exact | 702 |
| exact_sub | 319 |
| alias | 121 |
| fuzzy | 33 |
| fein | 27 |
| exact_parent | 10 |
| dba | 1 |

| State | Events | Public | Share |
|---|---|---|---|
| CA | 3473 | 835 | 24.0% |
| NY | 669 | 132 | 19.7% |
| TX | 674 | 128 | 19.0% |
| WA | 382 | 118 | 30.9% |

Rejected: 313 ({'fuzzy': 202, 'exact_sub': 64, 'reject_ambiguous_sub': 29, 'reject_franchise': 8, 'reject_name_not_valid_then': 7, 'dba': 2, 'exact': 1}).
Under manual review: 0 (reasons: {}).

**Precision on a random sample of automatic matches:** 100.0% (n = 194). Threshold: 95%.

**Stage 2 criterion:** ≥ 300 notices from public companies — 1213 (met); precision ≥ 95% — 100.0%.
