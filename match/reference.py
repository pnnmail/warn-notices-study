"""Stage 2: a name reference for matching -> data/sec_names.parquet.
Row = (normalised name, CIK, ticker, kind): parent (current name), former (former name),
sub (a subsidiary from Exhibit 21), sub_dba (a subsidiary's trade name from EX-21)."""
import html
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import DATA, PERIOD_START, get_logger  # noqa: E402
from match.normalize import is_junk_name, norm, norm_light  # noqa: E402
from match.sec_reference import EX21_DIR, SEC, SUB_DIR, load_universe  # noqa: E402

log = get_logger("reference")
CORP = re.compile(r"\b(inc|llc|l\.l\.c|corp|corporation|company|co|ltd|limited|lp|l\.p|llp|plc|gmbh|s\.a|"
                  r"b\.v|n\.v|ag|sarl|s\.r\.l|pty|pte|holdings?|group|trust|partners|bank)\b\.?", re.I)


def _text(fragment):
    x = re.sub(r"(?i)<br\s*/?>", " ", fragment)
    x = html.unescape(re.sub(r"<[^>]+>", " ", x))
    return re.sub(r"[\s​\xa0]+", " ", x).strip(" |*†‡")


def parse_ex21(raw: str):
    """Legal entity names from Exhibit 21: tables (all "name" cells) or lines of text."""
    names = []
    t = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", raw)
    rows = re.findall(r"(?is)<tr.*?</tr>", t)
    if len(rows) >= 3:
        for tr in rows:
            cells = [_text(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
            cells = [c for c in cells if c and not re.fullmatch(r"[\d\.\-%()\s]+", c)]
            for i, c in enumerate(cells):
                if i == 0 or CORP.search(c):
                    names.append(c)
    else:
        x = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr)>", "\n", t)
        x = html.unescape(re.sub(r"<[^>]+>", " ", x))
        for line in x.splitlines():
            line = re.sub(r"[\s​\xa0]+", " ", line).strip(" -–|*•")
            if not line or len(line) > 160:
                continue
            line = re.split(r"\s+\(|\t| {2,}| – | - |, a (?=[A-Z])", line)[0]
            if CORP.search(line) or len(line.split()) >= 2:
                names.append(line)
    out = []
    for n in names:
        n = re.sub(r"^\d+[\.\)]\s*", "", n).strip()
        out.append(n)
        m = re.search(r"\b(?:d/?b/?a|doing business as)\b[:\s]*(.+)", n, re.I)
        if m:  # "X d/b/a Y" inside EX-21
            out.append(m.group(1))
    return out


def main():
    uni = load_universe(None) if (SEC / "company_tickers_exchange.json").exists() else None
    if uni is None:
        raise SystemExit("run match/sec_reference.py first")
    rows = []
    for cik, u in uni.items():
        base = dict(cik=cik, ticker=u["ticker"], exchange=u["exchange"], parent_name=u["name"])
        sp = SUB_DIR / f"{cik}.json"
        ein, cur_from = None, None
        if sp.exists():
            sub = json.loads(sp.read_text(encoding="utf-8"))
            ein = sub.get("ein")
            former = sub.get("formerNames") or []
            # the current name is valid from the end of the last former one (otherwise — always)
            tos = [f["to"][:10] for f in former if f.get("to")]
            cur_from = max(tos) if tos else None
            rows.append(dict(base, name=sub.get("name") or u["name"], kind="parent", valid_from=cur_from, valid_to=None))
            for fn in former:
                # former names valid within the period or slightly before
                if (fn.get("to") or "9999")[:10] >= str(PERIOD_START.replace(year=PERIOD_START.year - 2)):
                    rows.append(dict(base, name=fn["name"], kind="former",
                                     valid_from=(fn.get("from") or "")[:10] or None, valid_to=(fn.get("to") or "")[:10] or None))
        rows.append(dict(base, name=u["name"], kind="parent", valid_from=cur_from, valid_to=None))
        filed = {}
        if sp.exists():
            rec = sub["filings"]["recent"]
            filed = dict(zip(rec["accessionNumber"], rec["filingDate"]))
        for f in EX21_DIR.glob(f"{cik}_*"):
            if f.suffix == ".done":
                continue
            try:
                raw = f.read_bytes().decode("utf-8", errors="replace")
            except OSError:
                continue
            acc = f.stem.split("_")[1]
            for n in parse_ex21(raw):
                rows.append(dict(base, name=n, kind="sub", valid_from=None, valid_to=None, acc=acc,
                                 filed=filed.get(acc)))
        uni[cik]["ein"] = ein
    df = pd.DataFrame(rows)
    df["ein"] = df.cik.map(lambda c: uni[c].get("ein"))
    df["name_norm"] = df.name.map(norm)
    df["name_light"] = df.name.map(norm_light)
    df = df[~df.name_norm.map(is_junk_name)]
    # the first date of a 10-K whose EX-21 contains the subsidiary: before it (with a margin) the subsidiary may have belonged to someone else —
    # e.g. before an acquisition (Berry Global -> Amcor in 2025)
    df["sub_first_filed"] = df.groupby(["cik", "name_norm", "kind"]).filed.transform("min")
    df = df.drop_duplicates(["cik", "name_norm", "kind"])
    df.to_parquet(DATA / "sec_names.parquet", index=False)
    log.info("names: %d; by kind %s; companies with EX-21: %d; with EIN: %d", len(df), df.kind.value_counts().to_dict(),
             df[df.kind == "sub"].cik.nunique(), df.drop_duplicates("cik").ein.notna().sum())
    return df


if __name__ == "__main__":
    main()
