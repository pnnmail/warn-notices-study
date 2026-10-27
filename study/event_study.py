"""Stage 4: an event study around the WARN notice appearing on the state's site.

Samples:
  A (main, per spec) — events where the notice came before the first mention of layoffs of any kind (group_any);
  B (check)       — the notice came before news about the specific site (group_site);
  C (all events)    — for comparison.
Day 0 — the first trading day STRICTLY after public_date (the notice may have appeared after the close).
Market model on [−250, −30] trading days, market = SPY; check — return minus the sector ETF.
Filters: close on day −1 ≥ $5, ≥ 200 observations in the estimation window (of 221), no other 8-K
from the company in [−2, +2]. One company on one day 0 in several states — one event (employees are summed).
Significance: t across events; BMP (standardised CARs); t across same-date portfolios (clustering).
Report: reports/stage4_event_study.md, chart reports/stage4_car.png, data data/car.parquet."""
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CFG, DATA, REPORTS, TODAY, get_logger  # noqa: E402
from match.sec_reference import SEC, SUB_DIR, SecClient  # noqa: E402

log = get_logger("event_study")
EST = tuple(CFG["thresholds"]["estimation_window"])  # (-250, -30)
MIN_EST_OBS = 200
MIN_PRICE = CFG["thresholds"]["min_price"]
WINDOWS = {"[-5,-1]": (-5, -1), "[0,+5]": (0, 5), "[0,+20]": (0, 20)}
PATH = range(-10, 21)
SHARES_DIR = SEC / "shares"
SHARES_DIR.mkdir(exist_ok=True)


# ---------------- data ----------------
def load_prices():
    px = pd.read_parquet(DATA / "prices.parquet")
    adj = px.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    close = px.pivot(index="date", columns="ticker", values="close").sort_index()
    ret = adj.pct_change(fill_method=None)
    return ret, close


def eightk_dates(cik):
    p = SUB_DIR / f"{cik}.json"
    if not p.exists():
        return pd.DatetimeIndex([])
    rec = json.loads(p.read_text(encoding="utf-8"))["filings"]["recent"]
    return pd.DatetimeIndex([pd.Timestamp(d) for f, d in zip(rec["form"], rec["filingDate"]) if f.startswith("8-K")])


def shares_series(c, cik):
    """Shares outstanding by date (dei:EntityCommonStockSharesOutstanding from XBRL)."""
    p = SHARES_DIR / f"{cik}.json"
    if not p.exists():
        try:
            r = c.get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/EntityCommonStockSharesOutstanding.json")
        except RuntimeError as e:  # without a market cap the company simply drops out of this slice
            log.warning("shares %s: %s", cik, e)
            return None
        p.write_text(r.text if r is not None else "{}", encoding="utf-8")
    try:
        u = json.loads(p.read_text(encoding="utf-8")).get("units", {}).get("shares", [])
    except json.JSONDecodeError:
        u = []
    if not u:
        return None
    s = pd.DataFrame(u)
    s["end"] = pd.to_datetime(s["end"])
    return s.groupby("end").val.sum().sort_index()  # share classes are summed


# ---------------- events ----------------
def build_events(sample):
    pdt = pd.read_parquet(DATA / "public_dates.parquet")
    if sample == "A0":  # as worded in the spec: day 0 — after notice_date (the date received by the state)
        e = pdt[pdt.group_any == "notice_first"].copy()
        e["public_date"] = e.notice_date
        return e
    if sample == "A":
        e = pdt[pdt.group_any == "notice_first"]
    elif sample == "B":
        e = pdt[pdt.group_site == "notice_first"]
    else:
        e = pdt
    return e.copy()


def firm_day(e, cal):
    e = e.copy()
    i = np.searchsorted(cal.values, pd.to_datetime(e.public_date).values.astype("datetime64[ns]"), side="right")
    e = e[i < len(cal)].copy()
    e["d0_idx"] = i[i < len(cal)]
    e["day0"] = cal[e.d0_idx.values]
    agg = e.groupby(["ticker", "day0"]).agg(
        cik=("cik", "first"), d0_idx=("d0_idx", "first"), employees=("employees", "sum"),
        closure=("layoff_type", lambda s: s.fillna("").str.contains("closure").any()),
        states=("state", lambda s: ",".join(sorted(set(s)))), state=("state", "first"),
        lag_any=("lag_any", "min"), censored_any=("censored_any", "all"),
        company=("company_raw", "first"), group_ids=("group_id", list)).reset_index()
    return agg


def compute(ev, ret, close, cal, info, shares):
    mkt = ret["SPY"]
    rows, paths = [], []
    drop = {"no prices": 0, "price < $5": 0, "short history": 0, "8-K in [−2,+2]": 0}
    k8 = {}
    for r in ev.itertuples():
        t = r.ticker
        if t not in ret:
            drop["no prices"] += 1
            continue
        d0 = r.d0_idx
        if d0 + EST[0] < 0 or d0 + max(PATH) >= len(cal):
            drop["short history"] += 1
            continue
        pre = close[t].iloc[d0 - 1] if d0 >= 1 else np.nan
        if not (pre >= MIN_PRICE):
            drop["price < $5" if pd.notna(pre) else "no prices"] += 1
            continue
        est = slice(d0 + EST[0], d0 + EST[1] + 1)
        y, x = ret[t].iloc[est], mkt.iloc[est]
        ok = y.notna() & x.notna()
        if ok.sum() < MIN_EST_OBS:
            drop["short history"] += 1
            continue
        if r.cik not in k8:
            k8[r.cik] = eightk_dates(int(r.cik))
        lo, hi = cal[d0 - 2], cal[d0 + 2]
        if ((k8[r.cik] >= lo) & (k8[r.cik] <= hi)).any():
            drop["8-K in [−2,+2]"] += 1
            continue
        b, a = np.polyfit(x[ok], y[ok], 1)
        resid = y[ok] - (a + b * x[ok])
        sigma = resid.std(ddof=2)
        win = slice(d0 + min(PATH), d0 + max(PATH) + 1)
        ar = (ret[t].iloc[win] - (a + b * mkt.iloc[win])).values
        sec = info.get(t)
        ar_sec = (ret[t].iloc[win] - ret[sec].iloc[win]).values if sec in ret else np.full(len(ar), np.nan)
        rel = np.array(list(PATH))
        row = dict(ticker=t, day0=r.day0, cik=r.cik, state=r.state, states=r.states, employees=r.employees,
                   closure=r.closure, lag_any=r.lag_any, censored_any=r.censored_any, company=r.company,
                   sigma=sigma, beta=b)
        for name, (s0, s1) in WINDOWS.items():
            m = (rel >= s0) & (rel <= s1)
            row[f"car{name}"] = np.nansum(ar[m])
            row[f"scar{name}"] = np.nansum(ar[m]) / (sigma * np.sqrt(m.sum()))
            row[f"sec{name}"] = np.nansum(ar_sec[m]) if not np.isnan(ar_sec[m]).all() else np.nan
        # [0, until first publicity): only if publicity was found and came later
        if not r.censored_any and r.lag_any >= 1:
            L = int(min(r.lag_any - 1, max(PATH)))
            m = (rel >= 0) & (rel <= L)
            row["car[0,pub)"] = np.nansum(ar[m])
            row["scar[0,pub)"] = np.nansum(ar[m]) / (sigma * np.sqrt(m.sum()))
        # market cap on day −1
        sh = shares.get(r.cik)
        if sh is not None:
            past = sh[sh.index <= cal[d0 - 1]]
            if len(past):
                row["mcap"] = past.iloc[-1] * close[t].iloc[d0 - 1]
        rows.append(row)
        paths.append(np.nancumsum(ar))
    return pd.DataFrame(rows), np.array(paths), drop


# ---------------- statistics ----------------
def stats(df, col, scol=None):
    x = df[col].dropna()
    n = len(x)
    if n < 5:
        return dict(n=n)
    out = dict(n=n, mean=x.mean(), median=x.median(), neg=(x < 0).mean(), t=x.mean() / (x.std() / np.sqrt(n)))
    if scol and scol in df:
        s = df[scol].dropna()
        out["t_bmp"] = s.mean() / (s.std() / np.sqrt(len(s)))
    by_date = df.groupby("day0")[col].mean().dropna()
    if len(by_date) >= 5:
        out["t_date"] = by_date.mean() / (by_date.std() / np.sqrt(len(by_date)))
        out["n_dates"] = len(by_date)
    return out


def fmt(s):
    if s.get("n", 0) < 5:
        return f"| {s.get('n', 0)} | — | — | — | — | — | — |"
    return (f"| {s['n']} | {s['mean']:+.2%} | {s['median']:+.2%} | {s['neg']:.0%} | {s['t']:+.2f} | "
            f"{s.get('t_bmp', np.nan):+.2f} | {s.get('t_date', np.nan):+.2f} |")


def slope(df, xcol, ycol):
    d = df[[xcol, ycol]].dropna()
    if len(d) < 20:
        return np.nan, np.nan
    x, y = d[xcol].values, d[ycol].values
    X = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ beta
    # HC1 (heteroscedasticity-robust) standard errors
    XtXi = np.linalg.inv(X.T @ X)
    V = XtXi @ (X.T * e ** 2) @ X @ XtXi * len(x) / (len(x) - 2)
    return beta[1], beta[1] / np.sqrt(V[1, 1])


def run_sample(sample, ret, close, cal, info, shares, emp_total):
    ev = firm_day(build_events(sample), cal)
    df, paths, drop = compute(ev, ret, close, cal, info, shares)
    df["share"] = df.employees / df.ticker.map(emp_total)
    df["log_share"] = np.log(df.share.where(df.share > 0))
    df["sample"] = sample
    return ev, df, paths, drop


def main():
    ret, close = load_prices()
    cal = pd.DatetimeIndex(ret.index)
    ci = pd.read_parquet(DATA / "company_info.parquet")
    info = dict(zip(ci.ticker, ci.sector_etf))
    emp_total = dict(zip(ci.ticker, ci.employees_total))
    c = SecClient()
    shares = {int(k): shares_series(c, int(k)) for k in ci.cik.unique()}

    res = {}
    for s in ("A", "A0", "B", "C"):
        res[s] = run_sample(s, ret, close, cal, info, shares, emp_total)
        log.info("sample %s: events (firm-day) %d, computed %d, dropped %s", s, len(res[s][0]),
                 len(res[s][1]), res[s][3])
    pd.concat([r[1] for r in res.values()]).to_parquet(DATA / "car.parquet", index=False)
    plot(res)
    report(res)


def plot(res):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    names = {"A": "A: notice before any mention", "A0": "A0: same, day 0 from notice_date",
             "B": "B: before site news", "C": "C: all events"}
    for s, (_, df, paths, _) in res.items():
        if len(paths):
            m = paths.mean(axis=0)
            se = paths.std(axis=0) / np.sqrt(len(paths))
            x = list(PATH)
            # normalise so that CAR on day −1 is 0 (the [-10,-1] window shows pre-event drift)
            ax.plot(x, m * 100, label=f"{names[s]} (n={len(paths)})")
            if s == "A":
                ax.fill_between(x, (m - 1.96 * se) * 100, (m + 1.96 * se) * 100, alpha=0.2)
    ax.axvline(0, color="gray", lw=0.8)
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_xlabel("trading days relative to day 0")
    ax.set_ylabel("mean CAR from day −10, %")
    ax.set_title("WARN: cumulative abnormal return (market model, SPY)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(REPORTS / "stage4_car.png", dpi=130)


def report(res):
    th = CFG["thresholds"]["stage4_min_abs_t"]
    hdr = ["| Window | N | Mean CAR | Median | Share < 0 | t | t BMP | t by date |", "|---|---|---|---|---|---|---|---|"]
    L = [f"# Stage 4 — event study ({TODAY})", "",
         "Day 0 — the first trading day strictly after the notice appeared on the state's site (public_date). "
         "Market model on [−250, −30], SPY. Filters: price ≥ $5 on day −1, ≥ 200 days in the estimation window, "
         "no other 8-K in [−2, +2]. Event = company × day 0.", "", "![CAR](stage4_car.png)", ""]
    for s, title in (("A", "Sample A (main): notice before any mention of layoffs"),
                     ("A0", "Sample A0: same events, day 0 — after notice_date (the date received by the state, as in the spec)"),
                     ("B", "Sample B: notice before site news"), ("C", "Sample C: all events")):
        ev, df, _, drop = res[s]
        L += [f"## {title}", "", f"Events (company × day 0): {len(ev)}; computed: {len(df)}; dropped: {drop}.", ""]
        L += hdr
        for w in list(WINDOWS) + ["[0,pub)"]:
            if f"car{w}" in df:
                L.append(f"| {w} " + fmt(stats(df, f"car{w}", f"scar{w}")))
        L += ["", "Check — return minus the sector ETF:", ""] + hdr
        for w in WINDOWS:
            L.append(f"| {w} " + fmt(stats(df, f"sec{w}")))
        L.append("")
    # slices of the main sample
    _, df, _, _ = res["A"]
    L += ["## Slices (sample A)", ""]
    for w in ("[0,+5]", "[0,+20]"):
        col = f"car{w}"
        L += [f"### CAR {w}", "", "| Slice | Group | N | Mean CAR | t |", "|---|---|---|---|---|"]
        d = df.dropna(subset=["share"]).copy()
        if len(d) >= 15:
            d["q"] = pd.qcut(d.share, 3, labels=["T1 (small share)", "T2", "T3 (large share)"])
            for q, g in d.groupby("q", observed=True):
                s = stats(g, col)
                L.append(f"| layoff share | {q} (median {g.share.median():.2%}) | {s['n']} | "
                         f"{s.get('mean', np.nan):+.2%} | {s.get('t', np.nan):+.2f} |")
        for v, g in df.groupby("closure"):
            s = stats(g, col)
            L.append(f"| type | {'closure' if v else 'layoff/unspecified'} | {s['n']} | {s.get('mean', np.nan):+.2%} | "
                     f"{s.get('t', np.nan):+.2f} |")
        d = df.dropna(subset=["mcap"]).copy()
        if len(d) >= 15:
            d["q"] = pd.qcut(d.mcap, 3, labels=["small", "mid", "large"])
            for q, g in d.groupby("q", observed=True):
                s = stats(g, col)
                L.append(f"| market cap | {q} | {s['n']} | {s.get('mean', np.nan):+.2%} | {s.get('t', np.nan):+.2f} |")
        for st, g in df.groupby("state"):
            s = stats(g, col)
            L.append(f"| state | {st} | {s['n']} | {s.get('mean', np.nan):+.2%} | {s.get('t', np.nan):+.2f} |")
        b, tb = slope(df, "log_share", col)
        L += ["", f"Regression of CAR{w} on log(layoff share): slope {b:+.4f}, t = {tb:+.2f} "
              "(H2 expects a negative slope).", ""]
    # verdict
    sA = {w: stats(df, f"car{w}", f"scar{w}") for w in ("[0,+5]", "[0,+20]")}
    sig = {w: abs(s.get("t", 0)) >= th and s.get("mean", 0) < 0 for w, s in sA.items()}
    slopes = {w: slope(df, "log_share", f"car{w}") for w in ("[0,+5]", "[0,+20]")}
    grows = {w: (slopes[w][0] < 0 and abs(slopes[w][1]) >= th) for w in slopes}
    ok = any(sig[w] and grows[w] for w in sig)
    L += ["## Verdict on the stage 4 criterion", "",
          f"Condition: CAR [0,+5] or [0,+20] is significantly negative (|t| ≥ {th}) and grows in magnitude with the layoff share.", ""]
    for w in sig:
        s = sA[w]
        L.append(f"- {w}: mean {s.get('mean', np.nan):+.2%}, t = {s.get('t', np.nan):+.2f} "
                 f"(BMP {s.get('t_bmp', np.nan):+.2f}, by date {s.get('t_date', np.nan):+.2f}) — "
                 f"{'significant' if sig[w] else 'not significant'}; slope by share t = {slopes[w][1]:+.2f} — "
                 f"{'grows' if grows[w] else 'does not grow'}.")
    L += ["", f"**Result: {'condition met — grounds to expand the pilot' if ok else 'condition NOT met — per the spec the project closes, the live collector stays as a dataset'}.**",
          "", "## Caveats", "",
          "- The company's headcount is current (yfinance fullTimeEmployees), not as of the event date; "
          "it is not tagged in XBRL in the 10-K.",
          "- Only currently traded companies (the SEC reference by current tickers) — delisted ones dropped out.",
          "- Day 0 in CA is the first Tue/Thu after processing (conservative); the real appearance may have been earlier, "
          "in which case part of the reaction falls into [−5,−1].",
          "- The \"no 8-K in [−2,+2]\" filter cuts large companies the most (they file 8-Ks often)."]
    (REPORTS / "stage4_event_study.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
