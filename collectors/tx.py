"""TX TWC: yearly xlsx files. The site is behind AWS WAF, so we enter with a real browser (Playwright)
and download files with requests from the same context. We do not solve captchas: if one appears, we fail."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CFG, PERIOD_START, StateSession, save_raw  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

STATE = "TX"


def main(live=False):
    c = CFG["states"][STATE]
    log = StateSession(STATE).log
    this_year = dt.date.today().year
    years = [this_year] if live else list(range(PERIOD_START.year, this_year + 1))
    if live and dt.date.today().month == 1:
        years.insert(0, this_year - 1)
    n_new = 0
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=CFG["http"]["user_agent"], accept_downloads=True)
        page = ctx.new_page()
        page.goto(c["page"], wait_until="networkidle", timeout=90000)
        if "captcha" in page.content().lower() and "warn-act-listings" not in page.content():
            raise RuntimeError("TX: WAF showed a captcha — not bypassing, manual handling needed")
        for y in years:
            url = c["xlsx_template"].format(year=y)
            page.wait_for_timeout(2500)
            r = ctx.request.get(url, timeout=90000)
            body = r.body()
            if r.status != 200 or not body.startswith(b"PK"):
                log.warning("%s: status %s, %d bytes, not xlsx", url, r.status, len(body))
                continue
            _, new = save_raw(STATE, url, body, f"warn-act-listings-{y}-twc.xlsx")
            n_new += new
            log.info("%s new=%s (%d bytes)", y, new, len(body))
        b.close()
    return n_new


if __name__ == "__main__":
    main(live="--live" in sys.argv)
