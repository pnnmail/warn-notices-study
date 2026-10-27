# Stage 3 — public date (2026-10-06)

Events of public companies: **1213**. Lag — trading days from the notice appearing on the state's site (public_date) to first publicity; > 0 — the notice came first. "Nothing in window" — within ±60 days neither an 8-K nor a news item was found (publicity is later, the lag > 0 is censored).

## Spec variant: any mention of the company's layoffs (8-K or news)

| Slice | Events | Notice first | Same day | News first | Median lag, t.d. | of which "nothing in window" |
|---|---|---|---|---|---|---|
| **All** | 1213 | 513 (42%) | 43 | 657 (54%) | -17 | 359 |
| CA before 2024Q3 (EDD backlog) | 379 | 175 (46%) | 10 | 194 (51%) | -17 | 132 |
| CA from 2024Q3 | 456 | 192 (42%) | 16 | 248 (54%) | -11 | 126 |
| NY HTML (before 04.2025) | 75 | 26 (35%) | 2 | 47 (63%) | -18 | 21 |
| NY Tableau (from 04.2025) | 57 | 32 (56%) | 0 | 25 (44%) | -29 | 21 |
| TX | 128 | 60 (47%) | 2 | 66 (52%) | -8 | 42 |
| WA | 118 | 28 (24%) | 13 | 77 (65%) | -35 | 17 |

Source of first publicity: {'news': 672, 'nothing in window': 359, '8-K Item 2.05': 143, '8-K text': 39}

## "Site" variant: news with the site's city/county in the headline

| Slice | Events | Notice first | Same day | News first | Median lag, t.d. | of which "nothing in window" |
|---|---|---|---|---|---|---|
| **All** | 1213 | 1071 (88%) | 47 | 95 (8%) | 0 | 932 |
| CA before 2024Q3 (EDD backlog) | 379 | 348 (92%) | 2 | 29 (8%) | -3 | 326 |
| CA from 2024Q3 | 456 | 405 (89%) | 24 | 27 (6%) | 0 | 361 |
| NY HTML (before 04.2025) | 75 | 63 (84%) | 1 | 11 (15%) | -1 | 53 |
| NY Tableau (from 04.2025) | 57 | 53 (93%) | 0 | 4 (7%) | 2 | 47 |
| TX | 128 | 118 (92%) | 3 | 7 (5%) | 2 | 84 |
| WA | 118 | 84 (71%) | 17 | 17 (14%) | 0 | 61 |

## Stage 3 criterion

Need ≥ 150 events with a lag ≥ 1 trading day.
- per spec (any mention): **513** (of which with a later news/8-K found: 154) — met;
- by site: **1071** — met.

## Caveats

- News — Google News RSS search instead of GDELT (the GDELT DOC API answers 429 to non-browser requests); only headlines are used; the date is the publication day without time.
- 8-K: filing date without time; a filing after the close is counted as the same day (in favour of H0). 8-K text counts only in the context of an announcement (an action verb or a number affected); boilerplate — forward-looking statements, non-GAAP reconciliations, contract representations — is discarded; on a sample ~85% are real announcements, the remaining noise works in favour of H0.
- CA: public_date — the first Tue/Thu after the processing date (conservative, in favour of H0).
- For large companies layoff news comes out almost constantly — the "per spec" variant for them is almost always "news first", even if the specific site was never mentioned.
