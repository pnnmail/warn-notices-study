"""WA ESD: ASP.NET GridView, sorted by Received Date descending (the default);
we page through with postbacks until we go past the start of the period."""
import datetime as dt
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CFG, PERIOD_START, StateSession, save_raw  # noqa: E402

STATE = "WA"
GRID = "ucPSW$gvMain"


def form_fields(t):
    f = {}
    for tag in re.findall(r"<input[^>]*>", t):
        n = re.search(r'name="([^"]+)"', tag)
        ty = re.search(r'type="([^"]+)"', tag)
        v = re.search(r'value="([^"]*)"', tag)
        if n and ty and ty.group(1) in ("hidden", "text"):
            f[n.group(1)] = html.unescape(v.group(1)) if v else ""
    return f


def received_dates(t):
    return [dt.datetime.strptime(d, "%m/%d/%Y").date()
            for d in re.findall(r'<td style="white-space:nowrap;">(\d{1,2}/\d{1,2}/\d{4})</td><td align="center">', t)]


def main(live=False):
    url = CFG["states"][STATE]["page"]
    s = StateSession(STATE)
    t = s.get(url).text
    max_pages = 3 if live else 2000
    page = 1
    n_new = 0
    while True:
        _, new = save_raw(STATE, f"{url}#page={page}", t.encode("utf-8"), f"page_{page:04d}.html")
        n_new += new
        dates = received_dates(t)
        if not dates:
            s.log.warning("page %d: no rows, stop", page)
            break
        s.log.info("page %d: %d rows, %s..%s", page, len(dates), max(dates), min(dates))
        if min(dates) < PERIOD_START or page >= max_pages:
            break
        nxt = page + 1
        if f"Page${nxt}" not in t:
            s.log.info("no link to page %d — end", nxt)
            break
        f = form_fields(t)
        f["__EVENTTARGET"] = GRID
        f["__EVENTARGUMENT"] = f"Page${nxt}"
        t = s.post(url, data=f, headers={"Referer": url}).text
        page = nxt
    s.log.info("pages %d, new files %d", page, n_new)
    return n_new


if __name__ == "__main__":
    main(live="--live" in sys.argv)
