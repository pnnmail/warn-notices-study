"""Stage 3: the date of first publicity for each event and the lag to the notice.

Two definitions of "first publicity":
  any  (per spec) — the first mention of the company's layoffs: an 8-K (Item 2.05 or text) or news
                 about the company's layoffs/closures, within ±60 days of public_date;
  site — the first news item about this particular site (company + the site's city/county in the headline).
If there is nothing in the window, publicity came no earlier than 60 days later (the lag is censored, > 0).

lag = trading days from public_date (an estimate of the notice appearing on the state's site, no look-
ahead) to first publicity; > 0 — the notice came before the news. Also lag_notice — from notice_date
(the date received by the state), as worded in the spec. Result: data/public_dates.parquet, stage 3 report."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CFG, DATA, REPORTS, TODAY, get_logger  # noqa: E402

log = get_logger("stage3")
WINDOW = 60


def trading_days():
    p = DATA / "spy.parquet"
    if not p.exists() or pd.Timestamp(pd.read_parquet(p).index.max()) < pd.Timestamp(TODAY) - pd.Timedelta(days=7):
        spy = yf.download("SPY", start="2022-06-01", auto_adjust=True, progress=False)
        spy.columns = [c[0] if isinstance(c, tuple) else c for c in spy.columns]
        spy.to_parquet(p)
    return pd.DatetimeIndex(pd.read_parquet(p).index).normalize()


def tday_index(cal, dates):
    """Trading day number; a non-trading date -> the next trading day."""
    d = pd.to_datetime(dates).values.astype("datetime64[ns]")
    return np.searchsorted(cal.values.astype("datetime64[ns]"), d, side="left").astype(float)


def main():
    ev = pd.read_parquet(DATA / "events.parquet")
    groups = pd.read_parquet(DATA / "notice_groups.parquet")[["group_id", "notice_date", "letter_date"]]
    ev = ev.merge(groups, on="group_id", how="left")
    em = pd.read_parquet(DATA / "edgar_mentions.parquet")
    news = pd.read_parquet(DATA / "news_first.parquet")
    ev = ev.merge(news, on="group_id", how="left")

    # the first mention in an 8-K within ±60 days
    em_by = {c: d.sort_values("date") for c, d in em.groupby("cik")}
    e_date, e_src, e_url, e_snip = [], [], [], []
    for r in ev.itertuples():
        d = pd.Timestamp(r.public_date)
        m = em_by.get(int(r.cik))
        if m is not None:
            m = m[(m.date >= d - pd.Timedelta(days=WINDOW)) & (m.date <= d + pd.Timedelta(days=WINDOW))]
        if m is not None and len(m):
            x = m.iloc[0]
            e_date.append(x.date); e_src.append(x.source); e_url.append(x.url); e_snip.append(x.snippet)
        else:
            e_date.append(pd.NaT); e_src.append(None); e_url.append(None); e_snip.append(None)
    ev["edgar_date"], ev["edgar_source"], ev["edgar_url"], ev["edgar_snippet"] = e_date, e_src, e_url, e_snip

    # "any": the earliest of the 8-K and the company news
    cand = ev[["edgar_date", "any_date"]]
    ev["first_public_date"] = cand.min(axis=1)
    ev["first_public_source"] = np.where(ev.first_public_date.isna(), None,
                                         np.where(ev.edgar_date.notna() & (ev.edgar_date <= ev.any_date.fillna(pd.Timestamp.max)),
                                                  ev.edgar_source, "news"))
    ev["first_public_url"] = np.where(ev.first_public_source == "news", ev.any_url, ev.edgar_url)

    cal = trading_days()
    i0 = tday_index(cal, ev.public_date)
    for k, col in (("any", "first_public_date"), ("site", "site_date")):
        lag = tday_index(cal, ev[col]) - i0
        ev[f"lag_{k}"] = np.where(ev[col].isna(), np.nan, lag)
        ev[f"censored_{k}"] = ev[col].isna()  # nothing in the window: publicity > 60 days later
        ev[f"group_{k}"] = np.select([ev[col].isna() | (ev[f"lag_{k}"] > 0), ev[f"lag_{k}"] == 0],
                                     ["notice_first", "same_day"], "news_first")
    ev["lag_notice_any"] = np.where(ev.first_public_date.isna(), np.nan,
                                    tday_index(cal, ev.first_public_date) - tday_index(cal, ev.notice_date))
    ev.to_parquet(DATA / "public_dates.parquet", index=False)
    report(ev)
    return ev


def dist(d, k):
    g = d[f"group_{k}"].value_counts()
    n = len(d)
    lead = d[(d[f"group_{k}"] == "notice_first")]
    return (f"{n} | {g.get('notice_first', 0)} ({g.get('notice_first', 0) / n:.0%}) | "
            f"{g.get('same_day', 0)} | {g.get('news_first', 0)} ({g.get('news_first', 0) / n:.0%}) | "
            f"{d[f'lag_{k}'].median():.0f} | {lead[f'censored_{k}'].sum()}")


def report(ev):
    need = CFG["thresholds"]["stage3_min_lead_events"]
    ev = ev.copy()
    ev["period"] = np.select(
        [(ev.state == "CA") & (ev.public_date < "2024-07-01"), ev.state == "CA",
         (ev.state == "NY") & (ev.public_date < "2025-04-01"), ev.state == "NY"],
        ["CA before 2024Q3 (EDD backlog)", "CA from 2024Q3", "NY HTML (before 04.2025)", "NY Tableau (from 04.2025)"], ev.state)
    hdr = ["| Slice | Events | Notice first | Same day | News first | Median lag, t.d. | of which \"nothing in window\" |",
           "|---|---|---|---|---|---|---|"]
    L = [f"# Stage 3 — public date ({TODAY})", "",
         f"Events of public companies: **{len(ev)}**. Lag — trading days from the notice appearing on the state's site "
         "(public_date) to first publicity; > 0 — the notice came first. \"Nothing in window\" — within ±60 days neither "
         "an 8-K nor a news item was found (publicity is later, the lag > 0 is censored).", "",
         "## Spec variant: any mention of the company's layoffs (8-K or news)", ""] + hdr
    L.append(f"| **All** | {dist(ev, 'any')} |")
    for p, d in ev.groupby("period"):
        L.append(f"| {p} | {dist(d, 'any')} |")
    L += ["", "Source of first publicity: " + str(ev.first_public_source.fillna("nothing in window").str.split(" \\(").str[0]
                                                   .value_counts().to_dict()), "",
          "## \"Site\" variant: news with the site's city/county in the headline", ""] + hdr
    L.append(f"| **All** | {dist(ev, 'site')} |")
    for p, d in ev.groupby("period"):
        L.append(f"| {p} | {dist(d, 'site')} |")
    n_any = int((ev.group_any == "notice_first").sum())
    n_site = int((ev.group_site == "notice_first").sum())
    n_any_obs = int(((ev.group_any == "notice_first") & ~ev.censored_any).sum())
    L += ["", "## Stage 3 criterion", "",
          f"Need ≥ {need} events with a lag ≥ 1 trading day.",
          f"- per spec (any mention): **{n_any}** (of which with a later news/8-K found: {n_any_obs}) — "
          f"{'met' if n_any >= need else 'NOT met'};",
          f"- by site: **{n_site}** — {'met' if n_site >= need else 'NOT met'}.", "",
          "## Caveats", "",
          "- News — Google News RSS search instead of GDELT (the GDELT DOC API answers 429 to non-browser requests); "
          "only headlines are used; the date is the publication day without time.",
          "- 8-K: filing date without time; a filing after the close is counted as the same day (in favour of H0). "
          "8-K text counts only in the context of an announcement (an action verb or a number affected); "
          "boilerplate — forward-looking statements, non-GAAP reconciliations, contract representations — is discarded; on a sample ~85% are "
          "real announcements, the remaining noise works in favour of H0.",
          "- CA: public_date — the first Tue/Thu after the processing date (conservative, in favour of H0).",
          "- For large companies layoff news comes out almost constantly — the \"per spec\" variant for them "
          "is almost always \"news first\", even if the specific site was never mentioned."]
    (REPORTS / "stage3_public_date.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
