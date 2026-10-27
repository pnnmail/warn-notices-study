# WARN_PILOT — stage 0: source reconnaissance

Reconnaissance date: 2026-10-05. Everything below was verified with live requests, not from memory.

## Summary

| State | Format | History from | Exact date for the "moment of publicity" | Script without a browser | Verdict |
|---|---|---|---|---|---|
| CA | PDF by fiscal year + current xlsx | 2014-07 | Received/Processed Date (≠ Notice Date!) | yes | **take** |
| WA | ASP.NET table + letter PDFs | 2004-01 | Received Date | yes (postback) | **take** |
| TX | xlsx by calendar year | 2020 | WFDD_RECEIVED_DATE (usually = NOTICE_DATE) | **no**, AWS WAF | **take**, download via a browser |
| NY | 2023–03.2025: PDF per notice; from 04.2025: Tableau | 2023 | Date Posted (HTML index / Tableau) | Tableau — via a browser | **take** (publication delay since 2025 — 1–3 months) |
| NJ | xlsx + PDF by year | 2004 | publication **month** only | yes | **not used for history**, live collection only |

**Stage 0 criterion** ("≥ 3 of 5 states provide history since 2023 in a parseable form"): **met** — CA, WA, TX fully, NY partially (2023 — March 2025).

## The key finding about look-ahead

**CA:** the reports have three dates: Notice Date (the date of the company's letter), Received/Processed Date (when EDD received and processed it), Effective Date.
For FY 2023-24 (1,814 rows) the lag Received − Notice: **median 26 days**, 25% ≥ 40 days, 10% ≥ 53; > 7 days — 73.5% of rows, > 30 days — 43.8%.
**Clarification after stage 1** (all years): this was a temporary EDD backlog. Median lag by quarter: 2023Q1 — 6 days, Q2 — 17, Q3 — 35, Q4 — 37, 2024Q1 — 16, Q2 — 5, from 2024Q3 until now — 0–1 day.
So using Notice Date as "day 0" in 2023 — early 2024 gives strong look-ahead: by the time it appears in the report, workers (and often the press) have known about the layoff for a month. Since mid-2024 the difference has almost disappeared, but the rule is the same.
→ `notice_date` in CA = **Received/Processed Date**, and Notice Date goes into a separate `letter_date` field.
Even Received Date is a lower bound: the file is updated on Tuesdays and Thursdays, so actual publication is 0–5 days later. For history, day 0 is shifted to the next reporting day (Tue/Thu) after Received Date. Live collection (`first_seen_at`) removes the question.

**Consequence for H1:** in 2023 — the first half of 2024 the letter to workers went out noticeably earlier than the state published the notice, so in CA in this period the "lead over news" may turn out smaller than expected; at stage 3 look at lags separately before and after 2024Q3. This is checked at stage 3, but worth keeping in mind in advance.

**In other states:** TX — NOTICE_DATE and WFDD_RECEIVED_DATE coincide in the sample (the date received by the state). WA — only Received Date. NY — the PDF has Date of Notice, and HTML-era URLs contain "date posted" (the date of posting on the site, exactly what is needed). NJ — month only.

---

## CA — Employment Development Department

1. **URL:** https://edd.ca.gov/en/jobs_and_training/Layoff_Services_WARN/
   - current fiscal year (xlsx): `https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx` (sheet `Detailed WARN Report `, header in row 2; currently 07/01/26–09/30/2026, 337 rows)
   - PDF archive: `.../warn/warn-report-for-7-1-2022-to-06-30-2023.pdf`, `...-2023-to-06-30-2024.pdf`, `...-2024-to-06-30-2025.pdf`, `warn-report-for-7-1-25-to-6-30-26.pdf` and so on back to FY 2014-15. **File names are irregular**: take links from the page, do not build them from a template.
2. **Format:** PDF with a text layer, `pdfplumber.extract_tables()` parses cleanly (checked on 4 files); xlsx.
3. **Depth:** from 07.2014. For the pilot period: FY22-23 — 1,424 rows, FY23-24 — 1,814, FY24-25 — 1,506, FY25-26 — 1,593.
4. **Fields:** Notice Date, Received Date (in the xlsx — Processed Date), Effective Date, Company, County, No. Of Employees, Layoff/Closure Type (Layoff/Closure × Permanent/Temporary), Address (one line, city and ZIP inside); the xlsx also has Related Industry (NAICS-2).
5. **Updates:** on Tuesdays and Thursdays (stated in the xlsx itself). There is no publication date on the site.
6. **Quirks:** one row = one site (David's Bridal — dozens of rows), must be collapsed into an event. HTML entities in names (`&rsquo;`). Amendments are not flagged separately. There is a "Call Center Relocations" sheet — a separate law, not included in the pilot. No captcha.

## WA — Employment Security Department

1. **URL:** https://esd.wa.gov/employer-requirements/layoffs-and-employee-notifications/worker-adjustment-and-retraining-notification-warn-layoff-and-closure-database → iframe `https://fortress.wa.gov/esd/file/WARN/Public/SearchWARN.aspx`
   - a letter for each notice: `/esd/file/WARN/Public/DownloadFile.aspx?file={guid}.pdf&download=1`
2. **Format:** ASP.NET GridView, 15 rows per page, pagination and sorting via `__doPostBack` (`ucPSW$gvMain`, `Page$N` / `Sort$ReceivedDate`). There is a name search (`ucPSW$txtSearch`). Verified: a postback with `__VIEWSTATE`/`__EVENTVALIDATION` via `requests.Session` works.
3. **Depth:** from 01.2004 (sorting by Received Date ascending → the first record is 1/12/2004).
4. **Fields:** Company, Location (city or county), Layoff Start Date, # of Workers, Closure/Layoff, Type of Layoff (Permanent/Temporary), Received Date, a link to the letter PDF. No address: only the city; the full address is in the PDF.
5. **Updates:** on business days (a fresh record from 10/5/2026 is already on the site). No publication date.
6. **Quirks:** a pass over all pages is needed: for 2023+ roughly 60–100 pages, with a 2–3 s pause that is minutes. Brands separated by "/" (`Maverick Washington LLC / Chips Casino`) — split for matching. Amendments are not flagged separately. No captcha.

## TX — Texas Workforce Commission

1. **URL:** https://www.twc.texas.gov/data-reports/warn-notice
   - `https://www.twc.texas.gov/sites/default/files/oei/docs/warn-act-listings-{YYYY}-twc.xlsx`, YYYY = 2020…2026
2. **Format:** xlsx, a single sheet `Sheet1`, a clean table.
3. **Depth:** 2020+. 2023 — 225 rows, 2026 (to Oct 2) — 107.
4. **Fields:** NOTICE_DATE, JOB_SITE_NAME, COUNTY_NAME, WDA_NAME, TOTAL_LAYOFF_NUMBER, LayOff_Date, WFDD_RECEIVED_DATE, CITY_NAME. **No** type (closure/layoff) and no address.
5. **Updates:** the current year's file is appended to (last record 10/2/26). No publication date.
6. **Quirks:** **AWS WAF** — `curl`/`requests` get a `202` with a JS challenge, both for the page and the xlsx. In an ordinary browser everything opens. We do not bypass captchas: the collector downloads via a headless browser (Playwright), without solving captchas. If WAF starts showing a captcha to the browser too, TX drops out of live collection. The site name sometimes has a city suffix: `Grunt Style, LLC (San Antonio)` — strip it. Typos: `Masonite Coorporation`, `ComericA`. Few events, a small contribution to the sample.

## NY — Department of Labor

1. **URL:**
   - current: https://dol.ny.gov/warn-dashboard → Tableau Public `WorkerAdjustmentRetrainingNotificationWARN/WARN`
   - "retired database" (01.01–01.04.2025): https://dol.ny.gov/warn-notices (70 notices)
   - archives: https://dol.ny.gov/2023-warn-notices (211), https://dol.ny.gov/2024-warn-notices (277). There are no `/2025-…`, `/2022-…` pages.
   - each notice is a separate URL that returns a **PDF**, e.g. `/warn-pfizer-hudson-valley-2023-0169-12-22-2023`.
2. **Format:** 2023 — 03.2025: a PDF card per notice with a text layer. From 04.2025: only the Tableau dashboard.
3. **Depth:** 01.2023 — 04.2025 reliably; 04.2025 — now via Tableau.
4. **Fields (PDF):** Company + headquarters address, **FEIN**, Industry (NAICS-2), Reason (Economic/Insolvency/…), Total Affected, Total Employees (company/site), Start/End Date, Event Number (`2023-0169`), site address, **Date of Notice**, Region, County, union. The URL has "date posted" (2025) or a date (2023-2024); "amended" ones are marked.
5. **Updates:** the dashboard — continuously. The posting date is in HTML-era URLs.
6. **Quirks:**
   - **FEIN is the best matching key** (checked against `ein` in the EDGAR submissions API). No other state has a FEIN.
   - There is a "Total Number of Employees" per site — useful, but the H2 slice needs the whole company's headcount from the 10-K.
   - Tableau (**solved 2026-10-06**, `collectors/ny_tableau.py`): CSV export of the workbook is disabled (404), the table is drawn as images. On the `WARNList` sheet with the `:render=true` parameter the `bootstrapSession` response (~17 MB) contains a data dictionary with all rows of the `A_Excel_Table___` sheet; Playwright intercepts the response via `page.route`. The year filter does not apply to this sheet: all 918 sites posted since 02.01.2025 arrive. Fields: Date Posted, Date of WARN Notice, Business Legal Name, address, county, WDA, industry, Layoff/Closure, Permanent/Temporary, Reason, start date, number of workers. **No FEIN.**
   - **The publication delay has grown.** Median Date Posted − Date of Notice by quarter: 2023–2024 — 2–6 days, 2025Q1 — 15, Q2 — 18, Q3 — 34, Q4 — 40, 2026Q1 — 91, Q2 — 68, Q3 — 57. For H1 in NY since 2025 this is bad: the notice comes out 1–3 months later, often after the news.
   - For amendments the dashboard keeps one row, and its Date Posted is the date of the last amendment; the original posting date is lost. An error on the safe side: the public date comes out later, not earlier.
   - Joining with HTML: everything posted before 01.04.2025 is taken from the HTML (exact dates + FEIN). Tableau rows that match an HTML-era notice (name + notice date) are dropped: they are repeated postings of amendments.
   - Amendments are marked in the URL (`amended`) — a plus.

## NJ — Department of Labor

1. **URL:** https://www.nj.gov/labor/business-services/layoffs-and-closing/file-warn-notice/
   - `https://www.nj.gov/labor/assets/PDFs/WARN/WARN_Notice_Archive.xlsx` (sheets by year 2004–2026)
   - `.../WARN/{YYYY}_WARN_Notice_Archive.pdf` (before 2020 — with spaces in the name)
2. **Format:** xlsx, 5 columns.
3. **Depth:** 2004+. 2023–2026: ~105–115 notices a year.
4. **Fields:** Company, City, **Month Posted**, Effective Date (often text: `4/24/25, 7/3/25, …`), Workforce Affected. No notice date, address or type.
5. **Updates:** monthly. Publication date — month only.
6. **Quirks:** without a daily date an event study on history is impossible. Reconstructing the date as Effective − 90 days (since 2023 NJ requires 90 days' notice) is too crude. **Decision:** NJ is not included in the historical sample; it is included in the live collector (`first_seen_at` gives the exact date), the page is checked daily. A small data quirk: the City field sometimes contains a whole paragraph (`JoAnn Stores … Company Location: Hudson, OH`).

---

## Third-party sources (for cross-checking, not as a basis)

- **biglocalnews/warn-scraper** (PyPI `warn-scraper`, last release 2026-09-03): ready-made scrapers for ~40 states, including our five. Use as a parsing reference, not as a dependency: their schema loses the Notice/Received distinction in CA, which is key for us.

## Decision per state

| | History (stages 1–4) | Live collection |
|---|---|---|
| CA | yes, day 0 = Received Date + up to the nearest Tue/Thu | yes |
| WA | yes | yes |
| TX | yes, via Playwright | yes, if WAF lets headless through |
| NY | 01.2023–03.2025 (PDF) + 04.2025+ (Tableau) | yes |
| NJ | no (monthly precision) | yes |

Expected volume of notices for 2023 — 10.2026 across CA+WA+TX+NY: CA ~5.5k rows (before collapsing sites), TX ~700, NY ~560 (without the Tableau period), WA — to be estimated during collection. That should comfortably cover the ≥ 300 notices from public companies required at stage 2, if matching yields at least 10–15%.

## Open questions

1. ~~NY from 04.2025~~ — solved via Tableau, see the NY section.
2. Price source: **yfinance**. Downside: no delisted tickers — survivorship bias for closures and bankruptcies; note it in the stage 4 report.
3. System Python is 3.14 (spec: 3.11+, OK). Installed `openpyxl`, `pdfplumber`, `rapidfuzz`; TX/NY will need `playwright`.
