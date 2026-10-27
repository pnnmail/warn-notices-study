"""CA EDD: PDF archives by fiscal year (FY22-23 and later) + the current year's xlsx."""
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CFG, PERIOD_START, StateSession, have_url, save_raw  # noqa: E402

STATE = "CA"


def fy_start_year(href):
    """'warn-report-for-7-1-2023-to-06-30-2024.pdf' -> 2023; '7-1-25-to-6-30-26' -> 2025."""
    m = re.search(r"7-1-(\d{2,4})", href)
    if not m:
        return None
    y = int(m.group(1))
    return y + 2000 if y < 100 else y


def main(live=False):
    c = CFG["states"][STATE]
    s = StateSession(STATE)
    page = s.get(c["page"]).text
    hrefs = sorted(set(re.findall(r'href="([^"]+\.pdf)"', page)))
    pdfs = [urljoin(c["page"], h) for h in hrefs if "warn-report" in h.lower() or "warnreport" in h.lower()]
    # The FY that contains the start of the period: 2023-01-01 -> FY 2022-23
    first_fy = PERIOD_START.year if PERIOD_START.month >= 7 else PERIOD_START.year - 1
    n_new = 0
    for url in pdfs:
        fy = fy_start_year(url)
        if fy is None or fy < first_fy:
            continue
        if live or have_url(STATE, url):  # archives of closed years do not change
            continue
        r = s.get(url)
        _, new = save_raw(STATE, url, r.content, url.rsplit("/", 1)[1])
        n_new += new
        s.log.info("pdf %s new=%s", url, new)
    r = s.get(c["current_xlsx"])
    _, new = save_raw(STATE, c["current_xlsx"], r.content, "warn_report1.xlsx")
    n_new += new
    s.log.info("xlsx new=%s; total new files %d", new, n_new)
    return n_new


if __name__ == "__main__":
    main(live="--live" in sys.argv)
