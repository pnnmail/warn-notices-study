# WARN notices vs. stock prices

Do state **WARN layoff notices** reach the public before the company announces
the layoffs — and if so, does the stock fall afterwards?

Under the WARN Act an employer must notify the state 60 days before a mass
layoff or a site closure, and several states publish these notices on their
websites. If a notice shows up there before any press release or 8-K, it could
be an early, overlooked signal. This project tests that with a pre-registered,
stage-gated pipeline ([SPEC.md](SPEC.md)): each stage has a pass/fail
criterion, and the project stops at the first failure.

## Result

**Negative.** Notices often *do* come first, but the market does not react.

| Stage | What it checks | Criterion | Outcome |
|---|---|---|---|
| 0 · Sources | ≥ 3 of 5 states give parseable history since 2023 | ≥ 3 | **pass** — CA, WA, TX full, NY partial |
| 1 · Collection | one schema across states | — | 9,143 site rows → 5,215 events |
| 2 · Matching | notices of public companies, precision | ≥ 300, ≥ 95% | **pass** — 1,213 events, 412 tickers, 100% precision (n = 194) |
| 3 · Public date | events where the notice preceded all news | ≥ 150 | **pass** — 513 (42%) by the strict definition, 1,071 by site |
| 4 · Event study | CAR significantly negative, grows with layoff share | \|t\| ≥ 2 | **fail** |

Main sample A (notice before *any* public mention of layoffs, n = 351):

| Window | Mean CAR | Median | t | t BMP | t by date |
|---|---|---|---|---|---|
| [−5, −1] | −0.50% | −0.21% | −1.66 | −1.61 | −2.15 |
| [0, +5] | +0.01% | −0.19% | +0.04 | −0.54 | +1.00 |
| [0, +20] | +0.18% | −1.01% | +0.33 | −0.10 | +1.03 |

No slope on the share of the workforce laid off (t = −0.75 and +0.07), no
difference between closures and layoffs, none by market cap. Full tables:
[reports/stage4_event_study.md](reports/stage4_event_study.md).

![Cumulative abnormal return around the notice](reports/stage4_car.png)

## Findings along the way

- **California's "Notice Date" is a look-ahead trap.** It is the date on the
  company's letter, not when the state published it. In 2023 – early 2024 the
  lag to the state's received date had a median of 26 days (an EDD backlog;
  since 2024Q3 it is 0–1 day). Using Notice Date as day 0 would leak a month of
  information. The pipeline uses the received date and then shifts to the next
  Tuesday/Thursday, when the state's file is actually updated.
- **New York's publication delay grew** from 2–6 days (2023–24) to 40–90 days
  (2025–26), so for recent NY events the notice usually arrives after the news.
- Matching layoff notices to tickers is the hard part: franchise brands,
  subsidiaries from Exhibit 21, companies acquired after the event (Berry
  Global in Amcor's EX-21), former names valid at another time. Precision was
  favoured over recall, and a labelled random sample checks it.

## Pipeline

```
collectors/   CA (PDF + xlsx), WA (ASP.NET postbacks), TX (Playwright, AWS WAF),
              NY (PDF cards + Tableau bootstrapSession interception), NJ
parse/        one schema per site → events (company + state + public date)
match/        SEC reference with EINs, former names and Exhibit 21 subsidiaries;
              exact / alias / parent / subsidiary / fuzzy matching, manual labels
public_date/  first public mention: 8-K Item 2.05, 8-K text, Google News RSS
study/        yfinance prices, market-model event study (SPY, sector ETFs), BMP,
              date-clustered t
live_collect.py   daily live collector that records when each notice first appeared
```

Rules followed throughout: no captcha solving and no bypassing of bot
protection (a real browser is used only where a site requires JavaScript),
SEC rate limits respected, raw files stored unchanged with hashes.

Each stage writes its own report to [reports/](reports/), and
[sources.md](sources.md) documents every state's data source.

## Running

```bash
pip install -r requirements.txt
playwright install chromium
# set http.sec_user_agent in config.yaml to your contact email (required by SEC)
python -m collectors.ca      # … and the other states
python -m parse.build
python match/run.py
python -m public_date.edgar_8k && python -m public_date.news && python -m public_date.build
python -m study.prices && python -m study.event_study
```

Raw data and parquet outputs are not included in the repository.

## Caveats

- Prices from yfinance cover currently listed companies only, so delisted
  firms are missing (survivorship bias).
- Company headcount for the layoff-share slice is the current value, not as of
  the event date.
- News coverage uses Google News RSS headlines instead of GDELT (GDELT's API
  rejects non-browser clients).
