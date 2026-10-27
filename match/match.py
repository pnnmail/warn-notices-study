"""Stage 2: notice_groups -> data/events.parquet (event + CIK + ticker + match method and confidence)
and match/review_*.csv for manual labelling. Precision matters more than recall.

Methods (by priority):
  fein         NY: the FEIN from the notice = the company's EIN in EDGAR (NY 2023–03.2025 only)
  exact        the normalised legal entity/part = the name of a public company valid on the event date
  alias        a manual brand table match/aliases.csv ("Amazon", "Google", "UPS")
  exact_parent "X, a subsidiary of Y": Y = a public company
  exact_sub    the normalised legal entity = a subsidiary from Exhibit 21 (a single parent)
  dba          only the trade name (d/b/a) matched -> manual review
  fuzzy        rapidfuzz -> automatic only for public company names and at very high similarity
To manual review (flags): a franchise brand as the legal entity, a one-word subsidiary or one made of generic words only,
a subsidiary differing by words like Group/Management, a fuzzy match with a subsidiary, a preferred-share ticker,
a subsidiary that first appeared in EX-21 much later than the event (possibly acquired after it).
Rejections: a franchise brand in d/b/a, a subsidiary of several parents, a name that belonged to the company at a different time."""
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CFG, DATA, REPORTS, ROOT, TODAY, get_logger  # noqa: E402
from match.normalize import is_franchise, norm, norm_light, variants  # noqa: E402

log = get_logger("match")
MATCH_DIR = ROOT / "match"
LABELS = MATCH_DIR / "labels.csv"   # manual labels: group_id, cik, label (1/0), sample, note

FUZZY_AUTO = 96      # auto-accept a fuzzy match (if the name is not short)
FUZZY_REVIEW = 88    # below this — not considered
MIN_TOKENS_AUTO = 2  # one-word subsidiary names — manual review only
SUB_COMMON_DF = 150  # a subsidiary whose every word occurs in > 150 reference names is a "generic" name
SUB_LOOKBACK_DAYS = 450  # a 10-K describes the past year: a subsidiary from an EX-21 filed on date D is surely ours from ~D-15 months
PRIO = {"fein": 0, "exact": 1, "alias": 1, "exact_parent": 2, "exact_sub": 3, "dba": 4, "fuzzy": 5}


def load_ref():
    ref = pd.read_parquet(DATA / "sec_names.parquet")
    for c in ("valid_from", "valid_to", "sub_first_filed"):
        ref[c] = pd.to_datetime(ref[c], errors="coerce")
    return ref


def token_df(ref):
    """In how many distinct reference names a word occurs — a measure of "genericness"."""
    cnt = Counter()
    for n in ref.name_norm.unique():
        cnt.update(set(n.split()))
    return cnt


def ein_norm(x):
    d = re.sub(r"\D", "", str(x or ""))
    return d if len(d) == 9 else None


def load_aliases(ref):
    a = pd.read_csv(MATCH_DIR / "aliases.csv")
    by_ticker = ref.drop_duplicates("cik").set_index("ticker").cik
    a["cik"] = a.ticker.map(by_ticker)
    missing = a[a.cik.isna()]
    if len(missing):
        log.warning("aliases without a CIK (ticker not on NYSE/Nasdaq?): %s", missing.ticker.tolist())
    return {norm(r.alias): int(r.cik) for r in a.dropna(subset=["cik"]).itertuples()}


def valid_at(rows, date, slack_days=30):
    """Names valid on the event date (a former name of another company must not match)."""
    s = pd.Timedelta(days=slack_days)
    ok = ((rows.valid_from.isna() | (rows.valid_from - s <= date))
          & (rows.valid_to.isna() | (rows.valid_to + s >= date)))
    return rows[ok]


def cand(cik, method, score, matched, vkind, variant, mkind=None, flags=()):
    return dict(cik=cik, method=method, score=score, matched_name=matched, variant_kind=vkind, variant=variant,
                matched_kind=mkind, flags=list(flags))


def candidates_for(group, ref_by_name, ein_map, aliases, tdf):
    out = []
    date = group.public_date
    fein = ein_norm(group.fein)
    if fein and fein in ein_map:
        for cik in ein_map[fein]:
            out.append(cand(cik, "fein", 100.0, f"EIN {fein}", "fein", group.fein))
    for raw in group.company_variants:
        for kind, text, n in variants(raw):
            flags = ["franchise_brand"] if is_franchise(n) and kind != "dba" else []
            if n in aliases and kind in ("legal", "part", "parent"):
                out.append(cand(aliases[n], "alias", 99.0, n, kind, text, "alias", flags))
            hits = ref_by_name.get(n)
            if hits is None:
                continue
            all_parents = hits[hits.kind.isin(["parent", "former"])]
            parents = valid_at(all_parents, date)
            if len(all_parents) and not len(parents):
                out.append(cand(None, "reject_name_not_valid_then", 0.0, all_parents.name.iloc[0], kind, text))
            subs = hits[hits.kind == "sub"]
            if kind == "dba":
                if is_franchise(n):
                    out.append(cand(None, "reject_franchise", 0.0, n, kind, text))
                    continue
                for r in parents.drop_duplicates("cik").itertuples():
                    out.append(cand(r.cik, "dba", 90.0, r.name, kind, text, r.kind))
                continue
            if kind == "parent":
                for r in parents.drop_duplicates("cik").itertuples():
                    out.append(cand(r.cik, "exact_parent", 98.0, r.name, kind, text, r.kind))
                continue
            if len(parents):
                for r in parents.drop_duplicates("cik").itertuples():
                    out.append(cand(r.cik, "exact", 100.0, r.name, kind, text, r.kind, flags))
            elif len(subs):
                ciks = subs.cik.unique()
                if len(ciks) > 1:
                    out.append(cand(None, "reject_ambiguous_sub", 0.0, f"{len(ciks)} parents", kind, text))
                    continue
                f = list(flags)
                if not (subs.name_light == norm_light(text)).any():
                    f.append("sub_light_mismatch")      # «AG Management Group» vs «AG Management Limited»
                toks = n.split()
                if len(toks) < MIN_TOKENS_AUTO:
                    f.append("sub_single_token")        # «Sunpower» (AMETEK) vs SunPower Corp
                if min(tdf.get(w, 0) for w in toks) > SUB_COMMON_DF:
                    f.append("sub_generic_words")       # «Primary Health»
                first = subs.sub_first_filed.min()
                if pd.notna(first) and date < first - pd.Timedelta(days=SUB_LOOKBACK_DAYS):
                    f.append("sub_maybe_acquired_later")  # Berry Global (2023) is in Amcor's EX-21 only from 2025
                out.append(cand(ciks[0], "exact_sub", 97.0, subs.name.iloc[0], kind, text, "sub", f))
    return out


_FUZZY_CACHE = {}


def fuzzy_candidates(n, choices, fz, date):
    if n not in _FUZZY_CACHE:  # the same name occurs in many events
        _FUZZY_CACHE[n] = process.extract(n, choices, scorer=fuzz.token_sort_ratio, limit=5,
                                          score_cutoff=FUZZY_REVIEW)
    res = _FUZZY_CACHE[n]
    out = []
    for name, score, idx in res:
        r = fz.iloc[idx]
        if r.kind in ("parent", "former") and not len(valid_at(fz.iloc[[idx]], date)):
            continue
        a, b = set(n.split()), set(name.split())  # guard against "generic" matches: share of common words
        if not a or len(a & b) / max(len(a), len(b)) < 0.5:
            continue
        flags = [] if r.kind in ("parent", "former") else ["fuzzy_sub"]
        out.append(cand(r.cik, "fuzzy", float(score), r["name"], "legal", n, r.kind, flags))
    return out


def main():
    groups = pd.read_parquet(DATA / "notice_groups.parquet")
    groups = groups[groups.state != "NJ"]
    ref = load_ref()
    tdf = token_df(ref)
    aliases = load_aliases(ref)
    ref_by_name = {k: v for k, v in ref.groupby("name_norm")}
    ein_map = (ref.dropna(subset=["ein"]).assign(e=lambda d: d.ein.map(ein_norm)).dropna(subset=["e"])
               .groupby("e").cik.unique().to_dict())
    tick = ref.drop_duplicates("cik").set_index("cik")[["ticker", "exchange", "parent_name"]]
    # for fuzzy — public company names and subsidiaries that have a single parent
    sub_owner = ref[ref.kind == "sub"].groupby("name_norm").cik.nunique()
    fz = ref[ref.kind.isin(["parent", "former"])
             | ((ref.kind == "sub") & ref.name_norm.map(sub_owner).eq(1))].drop_duplicates(["cik", "name_norm"])
    fz = fz.reset_index(drop=True)
    choices = fz.name_norm.tolist()

    rows = []
    for g in groups.itertuples():
        cands = candidates_for(g, ref_by_name, ein_map, aliases, tdf)
        accepted = [c for c in cands if c["cik"] is not None]
        rejects = [c for c in cands if c["cik"] is None]
        hard_reject = any(r["method"] in ("reject_franchise", "reject_ambiguous_sub", "reject_name_not_valid_then")
                          for r in rejects)
        if not accepted and not hard_reject:
            legal = [n for k, _, n in (v for raw in g.company_variants for v in variants(raw))
                     if k in ("legal", "part")]
            for n in dict.fromkeys(legal):
                accepted += fuzzy_candidates(n, choices, fz, g.public_date)
        base = dict(group_id=g.group_id, state=g.state, company_raw=g.company_raw, public_date=g.public_date,
                    employees=g.employees, layoff_type=g.layoff_type)
        if not accepted:
            r0 = rejects[0] if rejects else None
            rows.append(dict(base, cik=None, method=r0["method"] if r0 else "none", match_score=0.0,
                             matched_name=r0["matched_name"] if r0 else None, n_candidates=0, flags=""))
            continue
        accepted.sort(key=lambda c: (PRIO[c["method"]], -c["score"]))
        best = accepted[0]
        n_ciks = len({c["cik"] for c in accepted if PRIO[c["method"]] == PRIO[best["method"]]})
        rows.append(dict(base, cik=int(best["cik"]), method=best["method"], match_score=best["score"],
                         matched_name=best["matched_name"], matched_kind=best["matched_kind"],
                         variant_kind=best["variant_kind"], variant=best["variant"], n_candidates=n_ciks,
                         flags=",".join(best["flags"])))
    ev = pd.DataFrame(rows)
    ev = ev.join(tick, on="cik")
    ev["status"] = ev.apply(status, axis=1)
    ev["status_auto"] = ev.status  # the matcher's decision before manual labelling — precision is computed on it
    ev = apply_labels(ev)
    ev.to_parquet(DATA / "events_all.parquet", index=False)
    ev[ev.status.isin(["auto", "confirmed"])].to_parquet(DATA / "events.parquet", index=False)
    write_review(ev)
    report(ev)
    log.info("events: %d; statuses %s", len(ev), ev.status.value_counts().to_dict())
    return ev


def status(r):
    if pd.isna(r.cik):
        return "rejected" if str(r.method).startswith("reject") else "unmatched"
    if r.n_candidates > 1 or r["flags"]:
        return "review"
    if re.search(r"-P[A-Z]?$", str(r.ticker)):  # a preferred-share ticker (SCE-PG) — not the right security
        return "review"
    if r.method in ("fein", "exact", "alias", "exact_parent", "exact_sub"):
        return "auto"
    if r.method == "fuzzy" and r.match_score >= FUZZY_AUTO and len(norm(r.variant).split()) >= MIN_TOKENS_AUTO:
        return "auto"
    return "review"


def apply_labels(ev):
    """Manual labels win: label=1 -> confirmed, 0 -> rejected_manual (if the CIK is the same)."""
    if not LABELS.exists():
        return ev
    lab = pd.read_csv(LABELS, dtype={"group_id": str})
    lab = lab.dropna(subset=["label"]).drop_duplicates("group_id", keep="last").set_index("group_id")
    for i, r in ev.iterrows():
        if r.group_id in lab.index:
            L = lab.loc[r.group_id]
            same = pd.notna(r.cik) and pd.notna(L.cik) and int(L.cik) == int(r.cik)
            if int(L.label) == 1 and same:
                ev.at[i, "status"] = "confirmed"
            elif int(L.label) == 0 and same:
                ev.at[i, "status"] = "rejected_manual"
    return ev


def write_review(ev):
    cols = ["group_id", "state", "company_raw", "employees", "public_date", "method", "match_score", "flags",
            "variant", "matched_name", "parent_name", "ticker", "cik", "n_candidates", "status"]
    ev[ev.status == "review"][cols].sort_values("match_score", ascending=False) \
        .to_csv(MATCH_DIR / "review_borderline.csv", index=False, encoding="utf-8-sig")
    # a random sample of automatic matches — for estimating precision
    auto = ev[ev.status.isin(["auto", "confirmed"])]
    auto.sample(min(len(auto), 200), random_state=7)[cols] \
        .to_csv(MATCH_DIR / "review_auto_sample.csv", index=False, encoding="utf-8-sig")


def precision_from_labels(ev):
    """Precision on a labelled random sample of automatic matches (sample == auto)."""
    if not LABELS.exists():
        return None
    lab = pd.read_csv(LABELS, dtype={"group_id": str}).dropna(subset=["label"])
    if "sample" in lab:
        lab = lab[lab["sample"] == "auto"]
    # we evaluate the current set: only events that are still auto-accepted with the same CIK
    cur = ev[ev.status_auto == "auto"][["group_id", "cik"]].dropna()
    cur["cik"] = cur.cik.astype(int)
    lab = lab.assign(cik=lab.cik.astype(int)).merge(cur, on=["group_id", "cik"])
    if not len(lab):
        return None
    return lab.label.astype(int).mean(), len(lab), lab


def report(ev):
    th = CFG["thresholds"]
    ok = ev[ev.status.isin(["auto", "confirmed"])]
    L = [f"# Stage 2 — matching to tickers ({TODAY})", "",
         f"Input events (excluding NJ): **{len(ev)}**. Matched to a public company (NYSE/Nasdaq): "
         f"**{len(ok)}** ({len(ok) / len(ev):.1%}), unique tickers {ok.ticker.nunique()}.", "",
         "| Status | Events |", "|---|---|"]
    for s, n in ev.status.value_counts().items():
        L.append(f"| {s} | {n} |")
    L += ["", "| Method (accepted) | Events |", "|---|---|"]
    for s, n in ok.method.value_counts().items():
        L.append(f"| {s} | {n} |")
    L += ["", "| State | Events | Public | Share |", "|---|---|---|---|"]
    for st, d in ev.groupby("state"):
        k = d.status.isin(["auto", "confirmed"]).sum()
        L.append(f"| {st} | {len(d)} | {k} | {k / len(d):.1%} |")
    rej = ev[ev.status.str.startswith("rejected")]
    flags = ev.loc[ev.status == "review", "flags"].fillna("").str.split(",").explode().replace("", "n_candidates/fuzzy/dba")
    L += ["", f"Rejected: {len(rej)} ({rej.method.value_counts().to_dict()}).",
          f"Under manual review: {(ev.status == 'review').sum()} (reasons: {flags.value_counts().to_dict()})."]
    pr = precision_from_labels(ev)
    if pr:
        p, n, _ = pr
        L += ["", f"**Precision on a random sample of automatic matches:** {p:.1%} (n = {n}). "
              f"Threshold: {th['stage2_min_precision']:.0%}."]
    n_ok, need = len(ok), th["stage2_min_public_notices"]
    L += ["", f"**Stage 2 criterion:** ≥ {need} notices from public companies — {n_ok} "
          f"({'met' if n_ok >= need else 'NOT met'}); precision ≥ {th['stage2_min_precision']:.0%} — "
          + (f"{pr[0]:.1%}" if pr else "no labels") + "."]
    (REPORTS / "stage2_match.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
