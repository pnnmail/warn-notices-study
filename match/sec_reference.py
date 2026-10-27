"""Stage 2, SEC reference: companies with a ticker on NYSE/Nasdaq, their EIN, former names
and subsidiary legal entities from Exhibit 21 to the 10-K (the latest 10-K and the earliest since the start of the period).
Cache in raw/SEC/ — a re-run downloads only what is missing."""
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CFG, PERIOD_START, RAW, get_logger  # noqa: E402

SEC = RAW / "SEC"
SUB_DIR = SEC / "submissions"
EX21_DIR = SEC / "ex21"
for d in (SEC, SUB_DIR, EX21_DIR):
    d.mkdir(parents=True, exist_ok=True)
log = get_logger("sec_reference")
EXCHANGES = {"NYSE", "Nasdaq"}


class SecClient:
    """≤ sec_max_rps requests per second, retries on 429/5xx."""

    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = CFG["http"]["sec_user_agent"]
        self.min_gap = 1.0 / (CFG["http"]["sec_max_rps"] - 2)  # with a margin: 8/s
        self.lock = threading.Lock()
        self.last = 0.0

    def get(self, url):
        for i in range(5):
            with self.lock:
                wait = self.min_gap - (time.time() - self.last)
                if wait > 0:
                    time.sleep(wait)
                self.last = time.time()
            try:
                r = self.s.get(url, timeout=(5, 8))  # SEC occasionally "hangs" a response — faster to re-ask
            except requests.RequestException as e:
                log.warning("net %s: %s", url, type(e).__name__)
                time.sleep(1 + 2 * i)
                continue
            if r.status_code == 404:
                return None
            if r.status_code in (429, 503) or r.status_code >= 500:
                log.warning("HTTP %s %s", r.status_code, url)
                time.sleep(10 * (i + 1))
                continue
            r.raise_for_status()
            return r
        raise RuntimeError(f"SEC: failed {url}")


def load_universe(c):
    p = SEC / "company_tickers_exchange.json"
    if not p.exists():
        p.write_bytes(c.get("https://www.sec.gov/files/company_tickers_exchange.json").content)
    j = json.loads(p.read_text())
    f = j["fields"]
    rows = [dict(zip(f, r)) for r in j["data"]]
    out = {}
    for r in rows:  # one CIK can have several tickers (share classes) — take the first
        if r["exchange"] in EXCHANGES and r["cik"] not in out:
            out[r["cik"]] = r
    return out


def tenk_filings(sub):
    """List of 10-Ks (date, accession) from recent + the card's extra files."""
    rec = sub["filings"]["recent"]
    rows = [(d, a) for f, d, a in zip(rec["form"], rec["filingDate"], rec["accessionNumber"]) if f in ("10-K", "10-K/A")]
    return sorted(rows)


def pick_10k(rows):
    """The latest 10-K and the earliest one filed since the start of the period (if different)."""
    if not rows:
        return []
    main = [r for r in rows if r[0] >= str(PERIOD_START)] or rows[-1:]
    picks = [rows[-1]]
    if main[0] != rows[-1]:
        picks.append(main[0])
    return picks


def ex21_url(c, cik, acc):
    nodash = acc.replace("-", "")
    r = c.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{acc}-index.htm")
    if r is None:
        return None
    for tr in re.findall(r"<tr.*?</tr>", r.text, re.S | re.I):
        if re.search(r">\s*EX-21[\.\d]*\s*<", tr, re.I):
            m = re.search(r'href="([^"]+)"', tr)
            if m:
                return "https://www.sec.gov" + m.group(1)
    return None


def process(c, cik):
    sp = SUB_DIR / f"{cik}.json"
    if not sp.exists():
        r = c.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        if r is None:
            return
        sp.write_bytes(r.content)
    sub = json.loads(sp.read_text(encoding="utf-8"))
    for date, acc in pick_10k(tenk_filings(sub)):
        done = EX21_DIR / f"{cik}_{acc}.done"
        if done.exists():
            continue
        url = ex21_url(c, cik, acc)
        if url:
            r = c.get(url)
            if r is not None:
                ext = Path(url).suffix or ".htm"
                (EX21_DIR / f"{cik}_{acc}{ext}").write_bytes(r.content)
        done.write_text(url or "")


def main():
    c = SecClient()
    uni = load_universe(c)
    ciks = sorted(uni)
    log.info("NYSE/Nasdaq companies: %d", len(ciks))
    t0 = time.time()
    done = 0

    def one(cik):
        try:
            process(c, cik)
        except Exception as e:  # one company must not bring down the whole pass
            log.warning("cik %s: %s", cik, e)

    # 4 threads under a shared rate limiter (SecClient.get) — the SEC limit is respected
    with ThreadPoolExecutor(max_workers=4) as ex:
        for _ in ex.map(one, ciks):
            done += 1
            if done % 200 == 0:
                log.info("%d/%d, %.0f min", done, len(ciks), (time.time() - t0) / 60)
    log.info("done: %d companies", len(ciks))


if __name__ == "__main__":
    main()
