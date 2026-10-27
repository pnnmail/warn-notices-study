"""Stage 3, source 3: the first news item about the company's layoffs/closures within ±60 days.

The spec says GDELT, but its DOC API answers 429 to any non-browser request (from a browser on the same machine
it answers), and we will not bypass bot protection. The replacement is Google News RSS search (a feed for
programmatic reading, supports after:/before:), no more than 1 request per 3 s.

A news item counts if its HEADLINE contains the company name and a word about layoffs/closures —
otherwise there is a lot of noise ("Vons Chicken" ≠ Vons). The feed returns ≤ 100 entries by relevance, so the window
goes in 30-day chunks from earliest to latest; a chunk with 100 entries is split in half.
Cache: raw/NEWS/. Result: data/news_first.parquet."""
import hashlib
import html
import os
import re
import sys
import time
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import DATA, RAW, get_logger  # noqa: E402
from match.normalize import norm  # noqa: E402

log = get_logger("news")
CACHE = RAW / "NEWS"
CACHE.mkdir(exist_ok=True)
RSS = "https://news.google.com/rss/search"
UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "WARN_PILOT research contact@example.com")}
WINDOW, CHUNK, GAP_SEC = 60, 30, 3.0
TERMS = '(layoffs OR layoff OR "laid off" OR "job cuts" OR closing OR closure OR "shut down" OR "WARN notice")'
TERM = (r"(?:lay[\s-]?offs?|laid off|lay(?:s|ing)? off|job cuts?|cut(?:s|ting)? (?:\S+ ){0,2}jobs|"
        r"eliminat\w+ (?:\S+ ){0,2}(?:jobs|positions|roles)|workforce|headcount|WARN|furlough\w*|"
        r"(?:clos(?:e|es|ed|ing)|shutter\w*|shut(?:s|ting)? down)(?: \S+){0,4}? (?:stores?|plants?|factor(?:y|ies)|"
        r"facilit(?:y|ies)|offices?|locations?|sites?|cent(?:er|re)s?|campus|warehouses?|labs?|hubs?|"
        r"restaurants?|hospitals?|clinics?|mills?|mines?|branch(?:es)?|operations|headquarters)|closures?)")
TITLE_RX = re.compile(r"\b" + TERM + r"\b", re.I)


def relevant(title, names, places=None):
    """The name next to a layoff word (name…word ≤ 60 chars or word…name ≤ 25);
    for the "site" variant — also the site's city/county in the headline."""
    title = re.sub(r"\s+-\s+[^-]{2,80}$", "", title)  # the tail " - New York Post" is the publisher, not a place
    nm = "(?:" + "|".join(re.escape(n) for n in names) + ")"
    term = TERM.replace("|WARN|", "|(?-i:WARN)|")      # "warn tech companies" is not a WARN notice
    near = re.compile(r"(?<![\w&])" + nm + r"(?![\w&]).{0,60}?\b" + term + r"\b|\b" + term + r"\b.{0,25}?(?<![\w&])"
                      + nm + r"(?![\w&])", re.I)
    if not near.search(title):
        return False
    if places is not None:  # exactly the site's city/county (a WARN without a place may be about another state)
        pl = [re.escape(x) for x in places]
        return bool(pl) and re.search(r"\b(?:" + "|".join(pl) + r")\b", title, re.I) is not None
    return True


# in the news the company is called by its brand, not its legal entity
NEWS_NAME = {"GOOGL": ["Google", "Alphabet"], "META": ["Meta", "Facebook"], "IBM": ["IBM"],
             "BRK-B": ["Berkshire Hathaway"], "UPS": ["UPS"], "T": ["AT&T"], "JPM": ["JPMorgan", "Chase"],
             "AMZN": ["Amazon"], "CVS": ["CVS"], "GM": ["General Motors", "GM"], "PSKY": ["Paramount"],
             "WBD": ["Warner Bros"], "XYZ": ["Block", "Square", "Cash App"], "RTX": ["RTX", "Raytheon"],
             "LH": ["Labcorp"], "ACI": ["Albertsons"], "XOM": ["Exxon"], "EIX": ["Southern California Edison"],
             "WFC": ["Wells Fargo"], "C": ["Citi", "Citigroup", "Citibank"], "BAC": ["Bank of America"],
             "DIS": ["Disney"], "CMCSA": ["Comcast", "NBCUniversal"]}
GENERIC_TAIL = r"\b(com|technologies|technology|holdings|group|international|inc|corporation|services|company|co)$"


def short_name(s):
    """«INTERNATIONAL PAPER CO /NEW/» -> «International Paper»."""
    n = norm(s)
    for _ in range(2):
        n2 = re.sub(GENERIC_TAIL, "", n).strip()
        n = n2 if n2 else n
    return " ".join(w if w.isupper() else (w.capitalize() if len(w) > 3 else w.upper()) for w in n.split())


def names_for(ev):
    names = list(NEWS_NAME.get(ev.ticker, [])) or [short_name(ev.parent_name)]
    own = short_name(ev.variant if isinstance(ev.variant, str) and ev.variant else ev.company_raw)
    if own and all(norm(own) != norm(n) for n in names) and len(own) >= 4 and ev.method != "fein":
        names.append(own)  # subsidiary/trade name: "Vons", "Pixar"
    return [n for n in dict.fromkeys(names) if len(n) >= 2]


STREET = re.compile(r"(?:blvd|boulevard|drive|dr|ave|avenue|st|street|road|rd|way|lane|ln|pkwy|parkway|ct|court|"
                    r"place|pl|hwy|highway|circle|plaza|suite|ste|floor|fl|unit|bldg|building|#)\.?\s+\S*$", re.I)
STREET = re.compile(r"(?<![A-Za-z])" + STREET.pattern.lstrip("\x08"), re.I)  # word boundary without \b


def city_from_address(a):
    """«16130 Sherman Way Van Nuys CA 91406» -> «Van Nuys»; «686 Broadway  New York, NY, 10012» -> «New York»."""
    a = str(a or "")
    m = re.search(r"^(.*?)[,\s]+(?:CA|NY|TX|WA)[,\s]+\d{5}", a)
    if not m:
        return None
    head = m.group(1).strip(" ,")
    if "  " in head:
        return head.split("  ")[-1].strip(" ,") or None
    if "," in head:
        return head.split(",")[-1].strip() or None
    w = head.split()
    for i in range(len(w) - 1, 0, -1):  # words after the last "street" word
        if STREET.search(" ".join(w[:i]) + " x"):
            return " ".join(w[i:]) or None
    return " ".join(w[-2:]) if len(w) >= 2 else None


def places_for(notices):
    out = []
    for r in notices.itertuples():
        for c in re.split(r"[,/;]| and ", str(r.city or "")):
            if c.strip() and c.strip().lower() not in ("none", "statewide"):
                out.append(c.strip())
        c = city_from_address(r.address)
        if c:
            out.append(c)
        if r.county:
            out.append(re.sub(r"\s+County$", "", str(r.county)).strip())
    return [p for p in dict.fromkeys(out) if len(p) >= 3][:6]


def name_rx(names):
    return re.compile(r"(?<![\w&])(" + "|".join(re.escape(n) for n in names) + r")(?![\w&])", re.I)


class News:
    def __init__(self):
        self.last = 0.0
        self.s = requests.Session()
        self.s.headers.update(UA)

    def search(self, q, start, end):
        key = hashlib.sha1(f"{q}|{start.date()}|{end.date()}".encode()).hexdigest()
        p = CACHE / f"{key}.xml"
        if not p.exists():
            for i in range(5):
                wait = GAP_SEC - (time.time() - self.last)
                if wait > 0:
                    time.sleep(wait)
                self.last = time.time()
                try:
                    r = self.s.get(RSS, params=dict(q=f"{q} after:{start.date()} before:{end.date()}",
                                                    hl="en-US", gl="US", ceid="US:en"), timeout=60)
                except requests.RequestException as e:
                    log.warning("net: %s", e)
                    time.sleep(15)
                    continue
                if r.status_code == 200:
                    p.write_text(r.text, encoding="utf-8")
                    break
                log.warning("HTTP %s, pausing", r.status_code)
                time.sleep(60 * (i + 1))
            else:
                raise RuntimeError("Google News RSS unavailable")
        out = []
        for it in re.findall(r"<item>(.*?)</item>", p.read_text(encoding="utf-8"), re.S):
            t = html.unescape(re.search(r"<title>(.*?)</title>", it, re.S).group(1))
            d = parsedate_to_datetime(re.search(r"<pubDate>(.*?)</pubDate>", it).group(1))
            link = re.search(r"<link>(.*?)</link>", it, re.S)
            src = re.search(r"<source[^>]*>(.*?)</source>", it, re.S)
            out.append(dict(date=pd.Timestamp(d).tz_convert(None).normalize(), title=t,
                            url=link.group(1) if link else None, source=html.unescape(src.group(1)) if src else None))
        return out

    def first_relevant(self, q, keep, start, end, depth=0):
        """The earliest relevant news item in [start, end]; a window with 100 results is split in half."""
        items = self.search(q, start, end)
        if len(items) >= 100 and depth < 4 and (end - start).days > 2:
            mid = start + (end - start) / 2
            return (self.first_relevant(q, keep, start, mid, depth + 1)
                    or self.first_relevant(q, keep, mid, end, depth + 1))
        rel = [x for x in items if keep(x["title"]) and start <= x["date"] <= end]
        return min(rel, key=lambda x: x["date"]) if rel else None


def earliest(nw, q, keep, d):
    # one request for the whole window; first_relevant splits the window in half itself if the feed hits 100 entries
    return nw.first_relevant(q, keep, d - pd.Timedelta(days=WINDOW), d + pd.Timedelta(days=WINDOW))


def main():
    ev = pd.read_parquet(DATA / "events.parquet")
    notices = pd.read_parquet(DATA / "warn_notices.parquet")
    by_group = {g: d for g, d in notices.groupby("group_id")}
    nw = News()
    rows = []
    for k, r in enumerate(ev.itertuples(), 1):
        names = names_for(r)
        places = places_for(by_group.get(r.group_id, notices.iloc[:0]))
        d = pd.Timestamp(r.public_date)
        ors = "(" + " OR ".join(f'"{n}"' for n in names) + ")"
        # any news about layoffs at the company (the spec's definition)
        q_any = f"{ors} {TERMS}"
        h_any = earliest(nw, q_any, lambda t: relevant(t, names), d)
        # news about this particular site: city/county or WARN in the headline
        h_site = None
        if places:
            q_site = ors + " (" + " OR ".join(f'"{p}"' for p in places) + ' OR WARN) ' + TERMS
            h_site = earliest(nw, q_site, lambda t: relevant(t, names, places), d)
        rows.append(dict(group_id=r.group_id, names="|".join(names), places="|".join(places),
                         any_date=h_any["date"] if h_any else pd.NaT, any_title=h_any["title"] if h_any else None,
                         any_url=h_any["url"] if h_any else None, any_outlet=h_any["source"] if h_any else None,
                         site_date=h_site["date"] if h_site else pd.NaT,
                         site_title=h_site["title"] if h_site else None, site_url=h_site["url"] if h_site else None,
                         site_outlet=h_site["source"] if h_site else None))
        if k % 50 == 0:
            df = pd.DataFrame(rows)
            log.info("%d/%d, news: any %d, about the site %d", k, len(ev), df.any_date.notna().sum(),
                     df.site_date.notna().sum())
            df.to_parquet(DATA / "news_first.parquet", index=False)
    df = pd.DataFrame(rows)
    df.to_parquet(DATA / "news_first.parquet", index=False)
    log.info("done: %d events; company news for %d, site news for %d", len(df),
             df.any_date.notna().sum(), df.site_date.notna().sum())


if __name__ == "__main__":
    main()
