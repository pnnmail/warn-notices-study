"""Stage 3, sources 1–2: the company's 8-Ks that publicly mention layoffs.
  a) 8-Ks with Item 2.05 (costs associated with exit or disposal activities / layoffs) — from the EDGAR card;
  b) 8-Ks (including Exhibit 99 — press releases) whose text mentions layoffs.
     Candidates come from a broad EDGAR full-text search query, then the document text is checked
     with our own regular expressions (phrasing in 8-Ks is too varied for an exact search).
Result: data/edgar_mentions.parquet (cik, date, source, url, snippet). Cache: raw/SEC/fts, raw/SEC/8k."""
import gzip
import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import DATA, PERIOD_START, TODAY, get_logger  # noqa: E402
from match.sec_reference import SEC, SUB_DIR, SecClient  # noqa: E402

log = get_logger("edgar_8k")
FTS_DIR, DOC_DIR = SEC / "fts", SEC / "8k"
FTS_DIR.mkdir(exist_ok=True)
DOC_DIR.mkdir(exist_ok=True)
START = (pd.Timestamp(PERIOD_START) - pd.Timedelta(days=90)).date()  # the ±60 d. window around the first events

FTS_TERMS = ["workforce", "headcount", "layoff", "layoffs", "jobs", "positions", "employees",
             "closure", "closures", "restructuring", '"laid off"', '"WARN Act"']

# a mention of layoffs/closures in 8-K text
# between the verb and the object — only service words and numbers ("reduce our overall workforce by 10,000 jobs")
_FILL = (r"(?:(?:the|our|its|their|a|an|total|overall|global|worldwide|corporate|approximately|about|roughly|"
         r"nearly|up|to|some|number|of|by|certain|several|salaried|hourly|full-time|employee|union|"
         r"\d[\d,\.]*%?|percent|one|two|three|four|five|six|seven|eight|nine|ten)\s+){0,6}")
LAYOFF_RX = re.compile(
    r"\b(lay[\s-]?offs?|laid off|reductions? in (?:force|workforce)|workforce reductions?|reductions? of "
    + _FILL + r"(?:workforce|headcount|employees|staff|positions|jobs)|"
    r"reduc(?:e|es|ed|ing)\s+" + _FILL + r"(?:workforce|headcount|employees|staff|positions|jobs|roles)|"
    r"eliminat(?:e|es|ed|ing|ion of)\s+" + _FILL + r"(?:positions|jobs|roles|employees)|job cuts|"
    r"headcount reductions?|"
    r"(?:clos(?:e|es|ed|ing|ure of|ures of)|shut(?:s|ting)? down|wind(?:s|ing)? down)\s+"
    r"(?:(?:the|our|its|a|an|one|two|three|four|five|\d+|of|certain|several|its|underperforming|"
    r"manufacturing|distribution|retail|production|fulfillment|\w+)\s+){0,3}"
    r"(?:facility|facilities|plant|plants|distribution cent(?:er|re)s?|stores|warehouses?|offices)|"
    r"WARN Act|Item 2\.05)\b", re.I)


def item_205(cik):
    """Dates of 8-Ks with Item 2.05 from the company card (recent + extra files, if recent is shorter than the period)."""
    p = SUB_DIR / f"{cik}.json"
    if not p.exists():
        return []
    sub = json.loads(p.read_text(encoding="utf-8"))
    rec = sub["filings"]["recent"]
    rows = list(zip(rec["form"], rec["filingDate"], rec.get("items", [""] * len(rec["form"])),
                    rec["accessionNumber"], rec["primaryDocument"]))
    out = []
    for form, d, items, acc, doc in rows:
        if form.startswith("8-K") and "2.05" in (items or "") and d >= str(START):
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
            out.append(dict(cik=cik, date=d, source="8-K Item 2.05", url=url, snippet="Item 2.05"))
    return out


def fts_hits(c, cik):
    """All of the company's 8-Ks for the period via a broad query (paged, cached)."""
    p = FTS_DIR / f"{cik}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    q = quote(" OR ".join(FTS_TERMS))
    hits, frm = [], 0
    while True:
        r = c.get(f"https://efts.sec.gov/LATEST/search-index?q={q}&forms=8-K&dateRange=custom"
                  f"&startdt={START}&enddt={TODAY}&ciks={cik:010d}&from={frm}")
        if r is None:
            break
        j = r.json()
        page = j.get("hits", {}).get("hits", [])
        for h in page:
            s = h["_source"]
            adsh, fname = h["_id"].split(":", 1)
            hits.append(dict(date=s.get("file_date"), adsh=adsh, file=fname, items=s.get("items"),
                             ftype=s.get("file_type")))
        total = j.get("hits", {}).get("total", {}).get("value", 0)
        frm += len(page)
        if not page or frm >= total or frm >= 1000:
            break
    p.write_text(json.dumps(hits), encoding="utf-8")
    return hits


def doc_text(c, cik, adsh, fname):
    p = DOC_DIR / f"{cik}_{adsh}_{re.sub(r'[^A-Za-z0-9._-]', '_', fname)}.txt.gz"
    if p.exists():
        return gzip.decompress(p.read_bytes()).decode("utf-8", errors="replace")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{fname}"
    r = c.get(url)
    raw = r.text if r is not None else ""
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"\s+", " ", t)
    p.write_bytes(gzip.compress(t.encode("utf-8")))
    return t


# announcement context: an action verb or a specific number affected
ANNOUNCE_RX = re.compile(
    r"(announc\w+|approv\w+|committed to|decided to|plans? to|planned|intends? to|will (?:reduce|eliminate|close|"
    r"cease|exit|lay off|shut)|is (?:reducing|eliminating|closing)|has (?:begun|initiated|commenced)|"
    r"(?:approximately|about|roughly|nearly) [\d,]+ (?:employees|positions|jobs|roles|people)|"
    r"[\d,]{2,} (?:employees|positions|jobs|roles)|by (?:approximately |about )?\d+(?:\.\d+)? ?(?:%|percent))", re.I)
# boilerplate: forward-looking statements, non-GAAP reconciliations, risk factors, contract representations, tax disclaimers
BOILER_RX = re.compile(
    r"(forward-looking|non-gaap|reconciliation|risk factors?|could (?:result|cause)|may (?:result|include)|"
    r"such as|has not (?:effectuated|implemented)|have not (?:effectuated|implemented)|no (?:plant closing|mass layoff)|"
    r"as defined in the WARN|representations? and warrant|Section \d|pursuant to|excludes?|excluding|adjusted|"
    r"implement or announce|shall not|covenant|in each case|expectations (?:related|relating) to|"
    r"lookback date|none of the compan|\(i[vx]?\)|\(x{1,3}[iv]*\)|affecting a group of|anticipated (?:costs|benefits))", re.I)


def announcement(t):
    """The first layoff phrase that stands in an announcement context rather than boilerplate."""
    for m in LAYOFF_RX.finditer(t):
        if m.group(0).lower().startswith("item 2.05"):
            return m
        ctx = t[max(0, m.start() - 250):m.end() + 250]
        if ANNOUNCE_RX.search(ctx) and not BOILER_RX.search(ctx):
            return m
    return None


def scan_cik(c, cik):
    out = item_205(cik)
    for h in fts_hits(c, cik):
        if not str(h["file"]).lower().endswith((".htm", ".html", ".txt")):
            continue
        t = doc_text(c, cik, h["adsh"], h["file"])
        m = announcement(t)
        if m:
            a, b = max(0, m.start() - 150), min(len(t), m.end() + 150)
            out.append(dict(cik=cik, date=h["date"], source=f"8-K text ({h['ftype'] or 'doc'})",
                            url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{h['adsh'].replace('-', '')}/{h['file']}",
                            snippet=t[a:b]))
    return out


def main():
    ev = pd.read_parquet(DATA / "events.parquet")
    ciks = sorted(ev.cik.dropna().astype(int).unique())
    c = SecClient()
    log.info("companies: %d", len(ciks))
    rows, done = [], 0

    def one(cik):
        try:
            return scan_cik(c, cik)
        except Exception as e:  # one company must not bring down the pass
            log.warning("cik %s: %s", cik, e)
            return []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(one, ciks):
            rows += res
            done += 1
            if done % 25 == 0:
                log.info("%d/%d, mentions %d", done, len(ciks), len(rows))
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df.date)
    df = df.sort_values(["cik", "date"]).drop_duplicates(["cik", "date", "url"])
    df.to_parquet(DATA / "edgar_mentions.parquet", index=False)
    log.info("done: %d mentions at %d companies; by source %s", len(df), df.cik.nunique(),
             df.source.str.split(" \\(").str[0].value_counts().to_dict())


if __name__ == "__main__":
    main()
