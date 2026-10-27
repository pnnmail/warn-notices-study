"""NJ DOL: a combined xlsx by year. Not used for history (publication month only), needed for live collection."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CFG, StateSession, save_raw  # noqa: E402

STATE = "NJ"


def main(live=False):
    c = CFG["states"][STATE]
    s = StateSession(STATE)
    r = s.get(c["xlsx"])
    _, new = save_raw(STATE, c["xlsx"], r.content, "WARN_Notice_Archive.xlsx")
    s.log.info("xlsx new=%s", new)
    return int(new)


if __name__ == "__main__":
    main(live="--live" in sys.argv)
