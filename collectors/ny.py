"""NY DOL: archive pages for 2023, 2024 and the "retired database" (01.01–01.04.2025) with links
to PDF notice cards. Cards do not change — only new URLs are downloaded.
The period from 04.2025 (Tableau dashboard) is a separate task and is not collected here."""
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CFG, StateSession, have_url, save_raw  # noqa: E402

STATE = "NY"


def main(live=False):
    c = CFG["states"][STATE]
    s = StateSession(STATE)
    links = []
    for i, page_url in enumerate(c["archive_pages"]):
        r = s.get(page_url)
        save_raw(STATE, page_url, r.content, f"index_{i}_{page_url.rstrip('/').rsplit('/', 1)[1]}.html")
        found = [urljoin(page_url, h.strip()) for h in re.findall(r'href="\s*(/warn-[^"]+)"', r.text)]
        found = [u for u in found if not u.endswith(("/warn-dashboard", "/warn-notices",
                                                     "/warn-notice-pdf-instructions"))
                 and "worker-adjustment-and-retraining" not in u]
        s.log.info("%s: %d links", page_url, len(found))
        links += found
    links = list(dict.fromkeys(links))
    todo = [u for u in links if not have_url(STATE, u)]
    s.log.info("total cards %d, to download %d", len(links), len(todo))
    n_new = 0
    for k, u in enumerate(todo, 1):
        try:
            r = s.get(u)
        except Exception as e:  # a broken link must not bring down the whole collection
            s.log.warning("fail %s: %s", u, e)
            continue
        ext = ".pdf" if r.content[:4] == b"%PDF" else ".html"
        _, new = save_raw(STATE, u, r.content, u.rsplit("/", 1)[1][:150] + ext)
        n_new += new
        if k % 50 == 0:
            s.log.info("%d/%d", k, len(todo))
    s.log.info("new cards %d", n_new)
    return n_new


if __name__ == "__main__":
    main(live="--live" in sys.argv)
