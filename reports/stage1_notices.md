# Stage 1 — warn_notices (2026-10-08)

Raw rows after parsing: 11962 ({'CA': 6693, 'WA': 409, 'TX': 1086, 'NY': 1388, 'NJ': 2386}).
Exact duplicates removed: 300. Outside the period (before 2023-01-01): 2519.
In warn_notices: **9143** rows (sites), in notice_groups: **5215** events (company + state + public date, excluding amendments and rescinded ones).
Rescinded: 14.

| State | Rows | Amendments | Amendments linked | Events | Min date | Max date | Empty: date | Empty: employees | Empty: type | Empty: address/city |
|---|---|---|---|---|---|---|---|---|---|---|
| CA | 6124 | 2 | 0 | 3489 | 2023-01-03 | 2026-10-07 | 0% | 0% | 0% | 0% |
| NJ | 442 | 0 | 0 | 0 | 2023-01-01 | 2026-10-01 | 100% | 0% | 100% | 0% |
| NY | 1326 | 126 | 94 | 668 | 2023-01-04 | 2026-10-02 | 0% | 0% | 0% | 6% |
| TX | 859 | 0 | 0 | 675 | 2023-01-05 | 2026-10-06 | 0% | 0% | 100% | 0% |
| WA | 392 | 0 | 0 | 383 | 2023-01-03 | 2026-10-07 | 0% | 0% | 0% | 0% |

## Dates

- `notice_date` — date received by the state (CA: Received/Processed, TX: WFDD_RECEIVED_DATE, WA: Received Date, NY: Date of Notice or the amendment date). `letter_date` — the date of the company's letter.
- `public_date` — an estimate of the day it appeared on the site: CA — the first Tue/Thu strictly after notice_date; NY — max(Date Posted from the index, notice_date); TX, WA — notice_date. NJ — none (month only).
- CA, lag notice_date − letter_date: median 3 d., p75 15, p90 36; > 30 days — 15%.
- NY (ny_html), lag posted − notice: median 5 d., p75 11, p90 29; rows 530, posted 2023-01-11..2025-03-31.
- NY (ny_tableau), lag posted − notice: median 40 d., p75 68, p90 123; rows 795, posted 2025-04-02..2026-10-06.
- NY (ny_tableau): for amendments Date Posted is overwritten with the amendment date — the original posting date is unknown, public_date may be later than the real one (an error on the safe side).

## Events by size

- n_sites > 1: 795 events; max 178 sites.
- employees per event: median 62, p90 231.
- with a FEIN (NY only): 388.
