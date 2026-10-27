"""Stage 1: raw files -> data/warn_notices.parquet (per site) and data/notice_groups.parquet
(company + state + public date = one event). Writes reports/stage1_notices.md."""
import hashlib
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CFG, DATA, PERIOD_START, REPORTS, TODAY, db  # noqa: E402
from parse.states import PARSERS  # noqa: E402

SUFFIX = r"\b(incorporated|inc|llc|l\.l\.c|corporation|corp|company|co|lp|l\.p|llp|ltd|limited|plc|pllc|na|n\.a)\b\.?"


def norm_company(s):
    s = str(s or "").lower()
    s = re.sub(r"\(.*?\)", " ", s)              # TX: "Grunt Style, LLC (San Antonio)"
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(SUFFIX, " ", s)
    s = re.sub(r"\bthe\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def public_date(r):
    """An estimate of the day the record became visible on the state's site (before live collection)."""
    d = r.notice_date
    if r.state == "CA" and pd.notna(d):
        # the xlsx is updated on Tue/Thu; take the first Tue/Thu strictly after the processing date (conservative)
        days = CFG["states"]["CA"]["publish_weekdays"]
        for k in range(1, 8):
            x = d + pd.Timedelta(days=k)
            if x.weekday() in days:
                return x
    if r.state == "NY" and pd.notna(r.posted_date):
        # the index has typos in the year — take the later date (no look-ahead)
        return max(r.posted_date, d) if pd.notna(d) else r.posted_date
    return d


def make_id(r):
    # effective_date, not effective_raw: when a CA record moves from the xlsx to the yearly PDF only the format changes
    key = "|".join(str(r[c]) for c in ["company_raw", "notice_date", "letter_date", "address", "city",
                                       "employees", "effective_date"])
    if r.state == "NJ":  # in NJ the effective date is often text, and there are no notice dates
        key += f"|{r.month_posted}|{r.effective_raw}"
    return f"{r.state}-" + hashlib.sha1(key.encode()).hexdigest()[:12]


def link_amendments(df):
    df["original_notice_id"] = None
    base = df[~df.is_amendment]
    for i, r in df[df.is_amendment].iterrows():
        c = base[(base.state == r.state) & (base.company_norm == r.company_norm)
                 & (base.notice_date <= r.notice_date)
                 & (base.notice_date >= r.notice_date - pd.Timedelta(days=365))]
        if len(c):
            df.at[i, "original_notice_id"] = c.sort_values("notice_date").notice_id.iloc[0]
    return df


def groups(df):
    g = df[~df.is_amendment & ~df.is_rescinded & df.public_date.notna()].copy()
    g["group_id"] = g.apply(lambda r: f"{r.state}-G" + hashlib.sha1(
        f"{r.company_norm}|{r.public_date.date()}".encode()).hexdigest()[:10], axis=1)
    agg = g.groupby("group_id").agg(
        state=("state", "first"), company_norm=("company_norm", "first"),
        company_raw=("company_raw", lambda s: s.value_counts().index[0]),
        company_variants=("company_raw", lambda s: sorted(set(s))),
        public_date=("public_date", "first"), notice_date=("notice_date", "min"),
        letter_date=("letter_date", "min"), effective_date=("effective_date", "min"),
        employees=("employees", "sum"), n_sites=("notice_id", "size"),
        layoff_type=("layoff_type", lambda s: s.dropna().iloc[0] if s.dropna().nunique() == 1 else
                     ("closure+layoff" if s.dropna().nunique() > 1 else None)),
        fein=("fein", lambda s: s.dropna().iloc[0] if s.notna().any() else None),
        company_employees=("company_employees", "max"),
        first_seen_at=("first_seen_at", "min"),
        notice_ids=("notice_id", list)).reset_index()
    df = df.merge(g[["notice_id", "group_id"]], on="notice_id", how="left")
    return df, agg


def main():
    frames, raw_counts = [], {}
    for st, fn in PARSERS.items():
        if not CFG["states"][st]["enabled"]:
            continue
        d = fn()
        raw_counts[st] = len(d)
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    for c in ["state", "company_raw", "address", "city", "county", "letter_date", "notice_date", "posted_date",
              "effective_date", "effective_raw", "employees", "layoff_type", "is_amendment", "fein",
              "company_employees", "source_url", "raw_file", "month_posted", "source"]:
        if c not in df:
            df[c] = None
    for c in ["letter_date", "notice_date", "posted_date", "effective_date", "month_posted"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["is_amendment"] = df.is_amendment.astype("boolean").fillna(False).astype(bool)
    df["source"] = df.source.fillna(df.state.str.lower())
    df["is_rescinded"] = (df.get("is_rescinded", pd.Series(False, index=df.index)).astype("boolean").fillna(False).astype(bool)
                          | df.company_raw.str.contains(r"rescind", case=False, na=False)
                          | df.source_url.str.contains(r"rescind", case=False, na=False))
    df["employees"] = pd.to_numeric(df.employees, errors="coerce").astype("Int64")
    df["company_employees"] = pd.to_numeric(df.company_employees, errors="coerce").astype("Int64")
    df["effective_raw"] = df.effective_raw.astype(str)
    df["notice_id"] = df.apply(make_id, axis=1)
    n_before = len(df)
    df = df.drop_duplicates("notice_id")
    n_dupes = n_before - len(df)

    start = pd.Timestamp(PERIOD_START)
    in_period = df.notice_date.ge(start) | (df.state.eq("NJ") & df.month_posted.ge(start))
    n_out = int((~in_period).sum())
    df = df[in_period].copy()

    df["company_norm"] = df.company_raw.map(norm_company)
    df["public_date"] = df.apply(public_date, axis=1)
    con = db()
    seen = pd.read_sql("SELECT notice_id, first_seen_at FROM seen", con)
    con.close()
    df = df.merge(seen, on="notice_id", how="left")
    df["first_seen_at"] = pd.to_datetime(df.first_seen_at)
    df = link_amendments(df)
    df, agg = groups(df)

    cols = ["notice_id", "state", "company_raw", "company_norm", "address", "city", "county", "letter_date",
            "notice_date", "posted_date", "public_date", "month_posted", "effective_date", "effective_raw",
            "employees", "layoff_type", "is_amendment", "original_notice_id", "is_rescinded", "fein", "company_employees",
            "first_seen_at", "group_id", "source", "source_url", "raw_file"]
    df = df[cols].sort_values(["state", "notice_date"])
    df.to_parquet(DATA / "warn_notices.parquet", index=False)
    agg.to_parquet(DATA / "notice_groups.parquet", index=False)
    report(df, agg, raw_counts, n_dupes, n_out)
    return df, agg


def report(df, agg, raw_counts, n_dupes, n_out):
    L = [f"# Stage 1 — warn_notices ({TODAY})", "",
         f"Raw rows after parsing: {sum(raw_counts.values())} ({raw_counts}).",
         f"Exact duplicates removed: {n_dupes}. Outside the period (before {PERIOD_START}): {n_out}.",
         f"In warn_notices: **{len(df)}** rows (sites), in notice_groups: **{len(agg)}** events "
         "(company + state + public date, excluding amendments and rescinded ones).",
         f"Rescinded: {int(df.is_rescinded.sum())}.", "",
         "| State | Rows | Amendments | Amendments linked | Events | Min date | Max date | Empty: date | Empty: employees | Empty: type | Empty: address/city |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for st, d in df.groupby("state"):
        a = d[d.is_amendment]
        dcol = d.month_posted if st == "NJ" else d.notice_date
        loc = d.address.isna() & d.city.isna()
        L.append(f"| {st} | {len(d)} | {len(a)} | {a.original_notice_id.notna().sum()} | "
                 f"{(agg.state == st).sum()} | {dcol.min():%Y-%m-%d} | {dcol.max():%Y-%m-%d} | "
                 f"{d.notice_date.isna().mean():.0%} | {d.employees.isna().mean():.0%} | "
                 f"{d.layoff_type.isna().mean():.0%} | {loc.mean():.0%} |")
    ca = df[df.state == "CA"]
    lag = (ca.notice_date - ca.letter_date).dt.days
    L += ["", "## Dates", "",
          "- `notice_date` — date received by the state (CA: Received/Processed, TX: WFDD_RECEIVED_DATE, "
          "WA: Received Date, NY: Date of Notice or the amendment date). `letter_date` — the date of the company's letter.",
          "- `public_date` — an estimate of the day it appeared on the site: CA — the first Tue/Thu strictly after notice_date; "
          "NY — max(Date Posted from the index, notice_date); TX, WA — notice_date. NJ — none (month only).",
          f"- CA, lag notice_date − letter_date: median {lag.median():.0f} d., p75 {lag.quantile(.75):.0f}, "
          f"p90 {lag.quantile(.9):.0f}; > 30 days — {(lag > 30).mean():.0%}.",
          ]
    for src, ny in df[(df.state == "NY") & df.posted_date.notna()].groupby("source"):
        nl = (ny.posted_date - ny.notice_date).dt.days
        L.append(f"- NY ({src}), lag posted − notice: median {nl.median():.0f} d., p75 {nl.quantile(.75):.0f}, "
                 f"p90 {nl.quantile(.9):.0f}; rows {len(ny)}, posted {ny.posted_date.min():%Y-%m-%d}.."
                 f"{ny.posted_date.max():%Y-%m-%d}.")
    L.append("- NY (ny_tableau): for amendments Date Posted is overwritten with the amendment date — the original posting date "
             "is unknown, public_date may be later than the real one (an error on the safe side).")
    L += ["", "## Events by size", "",
          f"- n_sites > 1: {(agg.n_sites > 1).sum()} events; max {agg.n_sites.max()} sites.",
          f"- employees per event: median {agg.employees.median():.0f}, p90 {agg.employees.quantile(.9):.0f}.",
          f"- with a FEIN (NY only): {agg.fein.notna().sum()}."]
    (REPORTS / "stage1_notices.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
