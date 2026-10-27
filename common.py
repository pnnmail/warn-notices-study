"""Shared WARN_PILOT utilities: config, HTTP with pauses, raw file storage, a service SQLite DB."""
import datetime as dt
import hashlib
import logging
import random
import sqlite3
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
DATA = ROOT / "data"
LOGS = ROOT / "logs"
REPORTS = ROOT / "reports"
META_DB = DATA / "meta.sqlite"

CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
TODAY = dt.date.today().isoformat()
PERIOD_START = dt.date.fromisoformat(str(CFG["period"]["start"]))

for d in (RAW, DATA, LOGS, REPORTS):
    d.mkdir(exist_ok=True)


def get_logger(name):
    log = logging.getLogger(name)
    if not log.handlers:
        log.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        fh = logging.FileHandler(LOGS / f"{name}.log", encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(fh)
        log.addHandler(sh)
    return log


def db():
    con = sqlite3.connect(META_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS raw_files (
        sha256 TEXT, state TEXT, url TEXT, path TEXT, fetched_at TEXT,
        PRIMARY KEY (state, url, sha256))""")
    con.execute("""CREATE TABLE IF NOT EXISTS seen (
        notice_id TEXT PRIMARY KEY, state TEXT, first_seen_at TEXT)""")
    return con


class StateSession:
    """requests.Session with a 2–3 s pause between requests and retries."""

    def __init__(self, state):
        h = CFG["http"]
        self.s = requests.Session()
        self.s.headers["User-Agent"] = h["user_agent"]
        self.delay = h["state_delay_sec"]
        self.retries = h["retries"]
        self.last = 0.0
        self.log = get_logger(f"collect_{state}")

    def _wait(self):
        pause = random.uniform(*self.delay) - (time.time() - self.last)
        if pause > 0:
            time.sleep(pause)
        self.last = time.time()

    def request(self, method, url, **kw):
        kw.setdefault("timeout", 60)
        for i in range(self.retries + 1):
            self._wait()
            try:
                r = self.s.request(method, url, **kw)
                if r.status_code < 500 and r.status_code != 429:
                    r.raise_for_status()
                    return r
                self.log.warning("HTTP %s %s", r.status_code, url)
            except requests.RequestException as e:
                if i == self.retries:
                    raise
                self.log.warning("retry %d %s: %s", i + 1, url, e)
            time.sleep(5 * (i + 1))
        r.raise_for_status()
        return r

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)


def save_raw(state, url, content: bytes, name: str):
    """Saves a file to raw/{state}/{date}/name. If the same file (url+hash) already exists, does not write.
    Returns (path, is_new)."""
    sha = hashlib.sha256(content).hexdigest()
    con = db()
    row = con.execute("SELECT path FROM raw_files WHERE state=? AND url=? AND sha256=?",
                      (state, url, sha)).fetchone()
    if row:
        con.close()
        return ROOT / row[0], False
    d = RAW / state / TODAY
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    if p.exists():  # same name today, but different content
        p = d / f"{p.stem}_{sha[:8]}{p.suffix}"
    p.write_bytes(content)
    con.execute("INSERT INTO raw_files VALUES (?,?,?,?,?)",
                (sha, state, url, str(p.relative_to(ROOT)), dt.datetime.now().isoformat(timespec="seconds")))
    con.commit()
    con.close()
    return p, True


def have_url(state, url):
    """Whether at least one saved version of this URL exists (for immutable archives)."""
    con = db()
    row = con.execute("SELECT 1 FROM raw_files WHERE state=? AND url=?", (state, url)).fetchone()
    con.close()
    return row is not None


def latest_raw(state):
    """The latest version of each URL for a state: {url: path}."""
    con = db()
    rows = con.execute("""SELECT url, path FROM raw_files WHERE state=?
                          ORDER BY fetched_at""", (state,)).fetchall()
    con.close()
    out = {}
    for url, path in rows:
        out[url] = ROOT / path
    return out
