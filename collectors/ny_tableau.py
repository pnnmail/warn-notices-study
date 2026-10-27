"""NY DOL, a Tableau Public dashboard (notices from 2025-01). CSV export is disabled for the workbook,
the table is rendered as images; with client-side rendering (:render=true) the bootstrapSession response
contains a data dictionary with all rows of the A_Excel_Table sheet. We intercept this response
with an ordinary browser and parse it. Raw: the table CSV (+ gzip of the response) — only if the table changed."""
import gzip
import io
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CFG, StateSession, save_raw  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

STATE = "NY"
SHEET = "A_Excel_Table___"


def fetch_bootstrap(url):
    got = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=CFG["http"]["user_agent"])

        def grab(route):
            resp = route.fetch(timeout=120000)
            got["body"] = resp.body()
            route.fulfill(response=resp)
        pg.route("**/bootstrapSession/**", grab)
        pg.goto(url, wait_until="load", timeout=120000)
        for _ in range(60):
            if "body" in got:
                break
            pg.wait_for_timeout(1000)
        b.close()
    if "body" not in got:
        raise RuntimeError("NY Tableau: bootstrapSession did not arrive (WAF/captcha?) — not bypassing")
    return got["body"]


def extract_table(body: bytes) -> pd.DataFrame:
    raw = body.decode("utf-8")
    parts, i = [], 0
    while i < len(raw):  # format: "<length>;<json><length>;<json>"
        j = raw.index(";", i)
        n = int(raw[i:j])
        parts.append(json.loads(raw[j + 1:j + 1 + n]))
        i = j + 1 + n
    pm = parts[1]["secondaryInfo"]["presModelMap"]
    dd = {}
    for seg in pm["dataDictionary"]["presModelHolder"]["genDataDictionaryPresModel"]["dataSegments"].values():
        for c in seg["dataColumns"]:
            dd.setdefault(c["dataType"], []).extend(c["dataValues"])
    z = pm["vizData"]["presModelHolder"]["genPresModelMapPresModel"]["presModelMap"][SHEET]
    pcd = z["presModelHolder"]["genVizDataPresModel"]["paneColumnsData"]
    pane = pcd["paneColumnsList"][0]["vizPaneColumns"]
    out = {}
    for c in pcd["vizDataColumns"]:
        cap = (c.get("fieldCaption") or "").strip()
        if not cap or cap.startswith("AGG("):
            continue
        pc, dt = pane[c["columnIndices"][0]], c["dataType"]
        al = pc.get("aliasIndices") or []
        out[cap] = ([dd["cstring"][-a - 1] if a < 0 else dd[dt][a] for a in al] if al
                    else [dd[dt][v] for v in pc["valueIndices"]])
    df = pd.DataFrame(out)
    df.columns = [c.replace("MIN(", "").replace(")", "").strip() for c in df.columns]
    return df


def main(live=False):
    url = CFG["states"][STATE]["dashboard"]
    log = StateSession(STATE).log
    body = fetch_bootstrap(url)
    df = extract_table(body)
    need = {"Business Legal Name", "Date Posted", "Date of WARN Notice", "Number of Affected Workers"}
    if not need <= set(df.columns) or len(df) < 100:
        raise RuntimeError(f"NY Tableau: unexpected structure {list(df.columns)}, rows {len(df)}")
    csv = df.to_csv(index=False).encode("utf-8")
    _, new = save_raw(STATE, url + "#table", csv, "tableau_warn_list.csv")
    if new:
        gz = io.BytesIO()
        with gzip.GzipFile(fileobj=gz, mode="wb") as f:
            f.write(body)
        save_raw(STATE, url + "#bootstrap", gz.getvalue(), "tableau_bootstrap.txt.gz")
    log.info("Tableau: %d rows, posted %s..%s, new=%s", len(df), df["Date Posted"].min(),
             df["Date Posted"].max(), new)
    return int(new)


if __name__ == "__main__":
    main(live="--live" in sys.argv)
