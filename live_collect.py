"""Daily live collection: fresh files from all states -> rebuild warn_notices ->
new notice_ids are written into the seen table with first_seen_at = the time of this run.

First run (seen is empty) — the baseline: all existing records are marked
first_seen_at = NULL, because we do not know when they appeared on the site."""
import datetime as dt
import sys
import traceback
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CFG, REPORTS, db, get_logger  # noqa: E402
from collectors import ca, nj, ny, ny_tableau, tx, wa  # noqa: E402
from parse import build  # noqa: E402

COLLECTORS = {"CA": ca, "WA": wa, "TX": tx, "NY": ny, "NY_TABLEAU": ny_tableau, "NJ": nj}
log = get_logger("live")


def main():
    now = dt.datetime.now().isoformat(timespec="seconds")
    status = {}
    for st, mod in COLLECTORS.items():
        if not CFG["states"][st.split("_")[0]]["enabled"]:
            continue
        try:
            status[st] = f"ok, new files {mod.main(live=True)}"
        except Exception as e:  # one failed state must not bring down the others
            status[st] = f"FAIL {type(e).__name__}: {e}"
            log.error("%s\n%s", st, traceback.format_exc())
    df, _ = build.main()

    con = db()
    baseline = con.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 0
    known = {r[0] for r in con.execute("SELECT notice_id FROM seen")}
    new = df[~df.notice_id.isin(known)]
    # a "new" record with an old date is a re-parse (notice_id changed), not an appearance on the site
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=30)
    # the date of appearance on the site, if the state provides it (NY publishes 40+ days after the notice)
    ref = new.posted_date.fillna(new.notice_date).fillna(new.month_posted)
    fresh = ref.isna() | (ref >= cutoff)
    con.executemany("INSERT INTO seen VALUES (?,?,?)",
                    [(r.notice_id, r.state, None if baseline or not f else now)
                     for r, f in zip(new.itertuples(), fresh)])
    con.commit()
    con.close()
    if not baseline and len(new):
        build.main()  # so that first_seen_at gets into the parquet

    if not baseline:
        new = new[fresh.values]
    by_state = new.groupby("state").size().to_dict()
    msg = (f"{now} {'BASELINE' if baseline else 'live'}: new records {len(new)} {by_state}; "
           + "; ".join(f"{k}: {v}" for k, v in status.items()))
    log.info(msg)
    with open(REPORTS / "live_log.md", "a", encoding="utf-8") as f:
        f.write(f"- {msg}\n")
    if not baseline and len(new):
        cols = ["state", "company_raw", "notice_date", "employees", "layoff_type"]
        log.info("\n%s", new[cols].to_string(index=False))


if __name__ == "__main__":
    main()
