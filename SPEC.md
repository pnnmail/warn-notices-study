# Spec: WARN_PILOT — layoff notices and stocks
Oct 5, 2026 · @j

## Goal and hypothesis
Test whether filing a WARN notice with a state precedes public news of layoffs, and whether this moves the stock price. Under the WARN Act an employer must notify the state 60 days before a mass layoff or a site closure. States publish these notices on their websites, often before the company announces anything itself.

- **H1.** Among public companies there is a noticeable share of events where the notice appeared at the state at least 1 trading day before the first public news.
- **H2.** For such events there is a negative abnormal return after the notice date, and it is stronger the larger the share of the company's headcount being laid off.
- **H0.** The market learns about layoffs at the same time as the filing or earlier, the lag is zero, there is no abnormal return.

## Pilot scope
| Parameter | Value |
|---|---|
| States | CA, TX, NY, NJ, WA |
| Period | January 2023 — now (deeper if the state provides an archive) |
| Companies | public, with a ticker on NYSE/NASDAQ, including subsidiaries via Exhibit 21 |
| Prices | daily, adjusted for splits and dividends |
| Benchmark | SPY; sector ETF as a check |

Expansion to other states — only after a positive verdict on the pilot.

## Stage 0 — source reconnaissance
For each state record in sources.md: the URL and direct file links; format; archive depth; fields (date received, layoff start date, address, number of people, type); update frequency and whether a publication date exists; quirks (amendments, duplicates, captcha, limits). The key question: which date marks the moment the notice became visible to the public. Result: sources.md and a decision per state. 1–2 evenings.

## Stage 1 — collection and a single schema
One collector per state, raw files in `raw/{state}/{download_date}/` unchanged, hash in the log, re-downloading the same file is skipped. Live daily collection from day one, writing `first_seen_at`.

Schema `warn_notices`: notice_id (state + hash of key fields), state, company_raw, address, city, county, notice_date (received by the state), effective_date, employees, layoff_type (closure / layoff / relocation), is_amendment, first_seen_at (live collection only), source_url, raw_file.

Cleaning: link amendments to the original notice; one company with several sites on one day is one event, employees are summed. Result: a table and a report (records, amendments, empty fields).

## Stage 2 — matching to tickers
1. Reference: SEC company_tickers.json + subsidiaries from Exhibit 21 to the 10-K, linked to the parent company's CIK.
2. Normalisation: lower case, without Inc/LLC/Corp/Co/LP and punctuation, "d/b/a" → two variants.
3. Exact match.
4. Fuzzy (rapidfuzz) with match_score.
5. Manual review of the borderline zone in a CSV (yes/no) — this is also the labelled set for estimating precision.
6. Traps — franchises, contractors, small firms with the same name — do not match.

Result: the `events` table (notice, CIK, ticker, match_score, method). The report shows the share of notices from public companies and the precision on the manual sample (target ≥ 95%).

## Stage 3 — public date
Sources in order: 8-K with Item 2.05 or 7.01/8.01 mentioning layoffs (EDGAR full-text search); press releases in 8-K Exhibit 99; GDELT by name + layoff/closure/WARN within ±60 days. Per event: first_public_date, source, link, lag_days in trading days. Groups: notice first (lag > 0), simultaneous (0), news first (< 0). Result: the distribution of lags by group and state — the first possible stopping point.

## Stage 4 — event study
CAR around the notice date for events with lag > 0.
- Market model, estimated on [−250, −30], market SPY; check — return minus the sector ETF.
- Day 0 — the first trading day after notice_date (for live collection — after first_seen_at).
- Windows: [−5, −1], [0, +5], [0, +20], [0, first_public_date].
- Significance: t across events + Patell or BMP; clustering by date.
- Slices: share of the company's headcount laid off (10-K) by tercile; closure vs layoff; market cap; state.
- Filters: price ≥ $5, 250 days of history, no other 8-K in [−2, +2].

Result: a CAR table by window and slice, a chart of mean CAR from −10 to +20, a conclusion on H1/H2.

## Stopping criteria
| After stage | Continue if | Otherwise |
|---|---|---|
| 0 | ≥ 3 of 5 states provide history since 2023 in a parseable form | close or change states |
| 2 | ≥ 300 notices from public companies, precision ≥ 95% | close |
| 3 | ≥ 150 events with a lag ≥ 1 trading day | close: no advantage |
| 4 | CAR [0,+5] or [0,+20] significant (\|t\| ≥ 2) and grows with the layoff share | close; keep the live collector as a dataset |

A positive verdict is a reason to expand to the other states and build a daily scanner.

## Technical requirements
Python 3.11+, data in Parquet, service tables in SQLite, each stage runs separately and can be re-run without breaking. Layout: sources.md, config.yaml, raw/, collectors/, parse/, match/, public_date/, study/, data/, reports/, logs/.
- SEC: User-Agent with a contact, ≤ 10 requests/s.
- State sites: pauses and retries, no more than 1 request per 2–3 s.
- Each stage writes a report to reports/: input, output, what was dropped and why.
- The live collector is a separate script run by cron once a day, writing only new records with first_seen_at.
- Price source — yfinance.
