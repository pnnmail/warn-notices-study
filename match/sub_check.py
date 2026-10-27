"""Stage 2, checking subsidiaries from Exhibit 21: was the "subsidiary" a separate public
company on the event date (before the acquisition)? Example: Berry Global (WARN 01.2023) is in Amcor's EX-21 from 2025, but in 2023 it
itself traded as BERY — it must not be matched to Amcor.

Criterion: EDGAR has a separate registration with the same name (a different CIK) that filed a DEF 14A
(a proxy — only companies with public shares file one; bond-only subsidiaries do not), and the event
falls between its first proxy (−1 year) and delisting (form 25/15). Then the match -> rejected.
Request cache: raw/SEC/sub_check/. After the check it recomputes the statuses and the stage 2 report."""
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import DATA, get_logger  # noqa: E402
from match.match import apply_labels, report, status, write_review  # noqa: E402
from match.normalize import norm  # noqa: E402
from match.sec_reference import SEC, SUB_DIR, SecClient  # noqa: E402

log = get_logger("sub_check")
CACHE = SEC / "sub_check"
CACHE.mkdir(exist_ok=True)


def search_ciks(c, name):
    """CIKs of EDGAR registrants by the prefix of the normalised name (the name is verified via the card)."""
    n = norm(name)
    key = re.sub(r"[^a-z0-9]+", "_", n)[:80]
    p = CACHE / f"search_{key}.txt"
    if not p.exists():
        r = c.get(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={quote_plus(n)}"
                  f"&type=&dateb=&owner=include&count=40&output=atom")
        p.write_text(r.text if r is not None else "", encoding="utf-8")
    return {int(x) for x in re.findall(r"<cik>(\d+)</cik>", p.read_text(encoding="utf-8"))}


def submissions(c, cik):
    p = SUB_DIR / f"{cik}.json"
    if not p.exists():
        r = c.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        p.write_bytes(r.content if r is not None else b"{}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def names_of(sub):
    return {norm(sub.get("name"))} | {norm(f.get("name")) for f in sub.get("formerNames") or []}


DELIST = {"25", "25-NSE", "15-12B", "15-12G", "15-15D"}


def public_window(sub):
    """The period when the registrant had its own public shares: from the first DEF 14A (−1 year)
    to delisting (form 25/15 after the last DEF 14A) or to this day."""
    rec = (sub.get("filings") or {}).get("recent") or {}
    forms = list(zip(rec.get("form", []), rec.get("filingDate", [])))
    proxies = sorted(pd.Timestamp(d) for f, d in forms if f == "DEF 14A")
    if not proxies:
        return None
    ends = sorted(pd.Timestamp(d) for f, d in forms if f in DELIST and pd.Timestamp(d) >= proxies[-1])
    return proxies[0] - pd.Timedelta(days=365), (ends[0] if ends else pd.Timestamp.max)


def main():
    c = SecClient()
    ev = pd.read_parquet(DATA / "events_all.parquet")
    # flags from the previous run of this check are reset so that a re-run gives the same result
    ev["flags"] = ev["flags"].fillna("").map(
        lambda s: ",".join(f for f in s.split(",") if f and not f.startswith("sub_separately_public")))
    todo = ev[ev.method.isin(["exact_sub", "fuzzy"]) & ev.cik.notna()]
    log.info("checking subsidiaries: %d events, %d unique names", len(todo), todo.matched_name.nunique())
    hits = {}
    for (name, parent), g in todo.groupby(["matched_name", "cik"]):
        try:
            found = search_ciks(c, name) - {int(parent)}
        except RuntimeError as e:
            log.warning("search %s: %s", name, e)
            continue
        for oc in found:
            try:
                sub = submissions(c, oc)
            except RuntimeError as e:
                log.warning("card %s: %s", oc, e)
                continue
            if norm(name) not in names_of(sub):
                continue
            w = public_window(sub)
            if w:
                hits[(name, int(parent))] = (oc, w)
    n_flag = 0
    for i, r in todo.iterrows():
        h = hits.get((r.matched_name, int(r.cik)))
        if h and h[1][0] <= r.public_date <= h[1][1]:
            ev.at[i, "flags"] = ",".join(filter(None, [r["flags"], f"sub_separately_public:{h[0]}"]))
            n_flag += 1
    log.info("subsidiaries that were separately public on the event date: %d", n_flag)
    ev["status"] = ev.apply(status, axis=1)
    ev.loc[ev["flags"].str.contains("sub_separately_public"), "status"] = "rejected"
    ev["status_auto"] = ev.status
    ev = apply_labels(ev)
    ev.to_parquet(DATA / "events_all.parquet", index=False)
    ev[ev.status.isin(["auto", "confirmed"])].to_parquet(DATA / "events.parquet", index=False)
    write_review(ev)
    report(ev)
    print(ev[ev["flags"].str.contains("sub_separately_public")][["company_raw", "public_date", "parent_name", "flags"]]
          .to_string())


if __name__ == "__main__":
    main()
