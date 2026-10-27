"""Parsing each state's raw files into rows of a single schema (per site).
Each function returns a DataFrame with the SITE_COLS columns."""
import datetime as dt
import html
import re
import sys
import warnings
from pathlib import Path

import pandas as pd
import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ROOT, db, latest_raw  # noqa: E402

warnings.filterwarnings("ignore", module="openpyxl")

SITE_COLS = ["state", "company_raw", "address", "city", "county", "letter_date", "notice_date",
             "posted_date", "effective_date", "effective_raw", "employees", "layoff_type",
             "is_amendment", "fein", "company_employees", "source_url", "raw_file"]


def _d(x, fmt=None):
    """A date or NaT. Years outside 1990–2100 (typos like 0001-07-17) — NaT."""
    if x is None or x is pd.NaT or (isinstance(x, float) and pd.isna(x)):
        return pd.NaT
    try:
        if isinstance(x, (dt.date, pd.Timestamp)):
            ts = pd.Timestamp(x)
        else:
            x = str(x).strip()
            if not x:
                return pd.NaT
            ts = pd.to_datetime(x, format=fmt) if fmt else pd.to_datetime(x)
    except (ValueError, TypeError, OverflowError, pd.errors.OutOfBoundsDatetime):
        return pd.NaT
    if pd.isna(ts) or not 1990 <= ts.year <= 2100:
        return pd.NaT
    return pd.Timestamp(ts.date()).as_unit("ns")


def _first_date(s):
    """The first date of the form m/d/yy(yy) in a string."""
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", str(s or ""))
    return _d(m.group(1)) if m else pd.NaT


def _int(x):
    m = re.search(r"\d[\d,]*", str(x or ""))
    return int(m.group(0).replace(",", "")) if m else None


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(str(s or ""))).strip()


def _ltype(s):
    s = str(s or "").lower()
    if "reloc" in s:
        return "relocation"
    if "plant closing" in s or "closure" in s or "closing" in s:
        return "closure"
    if "mass layoff" in s:
        return "layoff"
    if "layoff" in s or "reduc" in s:
        return "layoff"
    return None


def _rel(p):
    return str(Path(p).relative_to(ROOT))


# ---------------- CA ----------------
def parse_ca():
    rows = []
    for url, p in latest_raw("CA").items():
        if p.suffix == ".pdf":
            with pdfplumber.open(p) as pdf:
                for pg in pdf.pages:
                    for t in pg.extract_tables():
                        for r in t:
                            if not r or not r[0] or not re.match(r"\d", r[0]) or len(r) < 8:
                                continue
                            rows.append(dict(letter_date=_d(r[0], "%m/%d/%Y"), notice_date=_d(r[1], "%m/%d/%Y"),
                                             effective_date=_d(r[2], "%m/%d/%Y"), effective_raw=r[2],
                                             company_raw=_clean(r[3]), county=_clean(r[4]), employees=_int(r[5]),
                                             type_raw=_clean(r[6]), address=_clean(r[7]),
                                             source_url=url, raw_file=_rel(p)))
        elif p.suffix == ".xlsx":
            x = pd.read_excel(p, sheet_name=None, header=1)
            sh = next(v for k, v in x.items() if k.strip().lower() == "detailed warn report")
            sh.columns = [re.sub(r"\s+", " ", str(c)).strip().lower() for c in sh.columns]
            for _, r in sh.iterrows():
                if pd.isna(r.get("company")):
                    continue
                rows.append(dict(letter_date=_d(r["notice date"]), notice_date=_d(r["processed date"]),
                                 effective_date=_d(r["effective date"]), effective_raw=str(r["effective date"]),
                                 company_raw=_clean(r["company"]), county=_clean(r["county/parish"]),
                                 employees=_int(r["no. of employees"]), type_raw=_clean(r["layoff/ closure"]),
                                 address=_clean(r["address"]), source_url=url, raw_file=_rel(p)))
    df = pd.DataFrame(rows)
    df["state"] = "CA"
    df["layoff_type"] = df.type_raw.map(_ltype)
    df["city"] = None
    df["is_amendment"] = df.company_raw.str.contains(r"amend", case=False)
    return df


# ---------------- WA ----------------
def parse_wa():
    con = db()
    files = [ROOT / r[0] for r in con.execute("SELECT path FROM raw_files WHERE state='WA'")]
    con.close()
    rows = []
    for p in files:
        t = p.read_text(encoding="utf-8")
        for tr in re.findall(r"<tr>\s*<td>.*?</tr>", t, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(tds) < 8:
                continue
            c = [_clean(re.sub("<[^>]+>", "", x)) for x in tds]
            link = re.search(r"href='([^']+DownloadFile[^']+)'", tr)
            rows.append(dict(company_raw=c[0], city=c[1], effective_date=_d(c[2]), effective_raw=c[2],
                             employees=_int(c[3]), type_raw=f"{c[4]} {c[5]}", notice_date=_d(c[6]),
                             source_url="https://fortress.wa.gov" + html.unescape(link.group(1)) if link else None,
                             raw_file=_rel(p)))
    df = pd.DataFrame(rows)
    df["state"] = "WA"
    df["layoff_type"] = df.type_raw.map(_ltype)
    df["is_amendment"] = df.company_raw.str.contains(r"amend|revis", case=False)
    # pages overlap between download days — exact duplicates are removed
    return df.drop_duplicates(["company_raw", "city", "notice_date", "employees", "effective_raw"])


# ---------------- TX ----------------
def parse_tx():
    rows = []
    for url, p in latest_raw("TX").items():
        x = pd.read_excel(p, dtype=str)
        x.columns = [c.strip().upper() for c in x.columns]
        for _, r in x.iterrows():
            if pd.isna(r.get("JOB_SITE_NAME")):
                continue
            rows.append(dict(company_raw=_clean(r["JOB_SITE_NAME"]), county=_clean(r["COUNTY_NAME"]),
                             city=_clean(r["CITY_NAME"]), employees=_int(r["TOTAL_LAYOFF_NUMBER"]),
                             letter_date=_d(r["NOTICE_DATE"]), notice_date=_d(r["WFDD_RECEIVED_DATE"]),
                             effective_date=_d(r["LAYOFF_DATE"]), effective_raw=r["LAYOFF_DATE"],
                             source_url=url, raw_file=_rel(p)))
    df = pd.DataFrame(rows)
    df["state"] = "TX"
    df["layoff_type"] = None
    df["is_amendment"] = df.company_raw.str.contains(r"amend|revis", case=False)
    # in TX the received date is sometimes empty — then the notice date is used
    df["notice_date"] = df.notice_date.fillna(df.letter_date)
    return df


# ---------------- NY ----------------
NY_DATE = r"([A-Z][a-z]+\.? \d{1,2}, ?\d{4}|\d{1,2}/\d{1,2}/\d{2,4})"


def _ny_index():
    out = {}
    for url, p in latest_raw("NY").items():
        if "index_" not in p.name:
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            a = re.search(r'href="\s*([^"]+)"', tr)
            if len(tds) != 4 or not a:
                continue
            c = [_clean(re.sub("<[^>]+>", " ", x)) for x in tds]
            href = "https://dol.ny.gov" + a.group(1).strip() if a.group(1).strip().startswith("/") else a.group(1).strip()
            out[href] = dict(company_idx=c[0], region=c[1], posted_date=_first_date(c[2]),
                             index_notice_date=_first_date(c[3]),
                             amended_date=_first_date(re.search(r"amend\w*\s*(.*)", c[3], re.I).group(1))
                             if re.search(r"amend", c[3], re.I) else pd.NaT)
    return out


def _ny_pdf(p):
    with pdfplumber.open(p) as pdf:
        txt = "\n".join((pg.extract_text() or "") for pg in pdf.pages)

    def grab(pat):
        m = re.search(pat, txt, re.I | re.S)
        return _clean(m.group(1)) if m else None
    comp = grab(r"Company:\s*\n(.+?)\n")
    eff = grab(r"(?:Start Date|Layoff Date|Closing Date)\s*:\s*(.+?)\n")
    total = _int(grab(r"(?:Total Number of Affected Workers|Number Affected)\s*:\s*([\d,]+)"))
    if total is None:  # otherwise — the sum over sites
        sites = [_int(x) for x in re.findall(r"Number of Affected Employees at Site:\s*([\d,]+)", txt)]
        total = sum(sites) if sites else None
    return dict(company_pdf=comp, fein=grab(r"FEIN\s*(?:NUM|#)?\s*:?\s*([\d\-]{9,11})"),
                employees=total,
                company_employees=_int(grab(r"Total (?:Number of )?Employees\s*:\s*([\d,]+)")),
                reason=grab(r"(?:Reason Stated for Filing|Classification)\s*:\s*(.+?)\n")
                or grab(r"Reason for (?:Layoff/Closure|Closure|Layoff)\s*:?\s*(.+?)\n"),
                type_hdr=grab(r"\n((?:Layoff|Closure|Plant Closing|Mass Layoff)[/A-Za-z ]*?) Start Date"),
                effective_raw=eff,
                pdf_notice_date=_d(grab(r"Date of Notice:\s*" + NY_DATE)),
                rescinded=bool(re.search(r"Rescission|rescind", txt, re.I)),
                address=grab(r"Address:\s*(.+?)\n"),
                county=grab(r"County:\s*([^|\n]+)"))


def parse_ny():
    idx = _ny_index()
    rows = []
    for url, p in latest_raw("NY").items():
        if p.suffix != ".pdf":
            continue
        try:
            d = _ny_pdf(p)
        except Exception as e:  # a broken PDF — skip it, it is visible in the report
            print("NY bad pdf", p.name, e)
            continue
        i = idx.get(url, {})
        eff = d.pop("effective_raw")
        posted = i.get("posted_date", pd.NaT)
        # typos in the PDF (notice date later than the posting date) — take the date from the index
        if pd.notna(d["pdf_notice_date"]) and pd.notna(posted) and d["pdf_notice_date"] > posted:
            d["pdf_notice_date"] = pd.NaT
        rows.append(dict(company_raw=i.get("company_idx") or d["company_pdf"], address=d["address"],
                         county=d["county"], fein=d["fein"], employees=d["employees"],
                         company_employees=d["company_employees"],
                         letter_date=d["pdf_notice_date"] if pd.notna(d["pdf_notice_date"]) else i.get("index_notice_date"),
                         posted_date=i.get("posted_date", pd.NaT),
                         effective_date=_first_date(eff) if eff and re.search(r"\d/", eff) else _d(_month_date(eff)),
                         is_rescinded=d["rescinded"] or bool(re.search(r"rescind", url, re.I)),
                         effective_raw=eff, type_raw=f"{d['type_hdr'] or ''} {d['reason'] or ''}",
                         is_amendment=bool(re.search(r"amend", url, re.I)) or pd.notna(i.get("amended_date", pd.NaT)),
                         amended_date=i.get("amended_date", pd.NaT), source_url=url, raw_file=_rel(p)))
    df = pd.DataFrame(rows)
    df["state"] = "NY"
    df["city"] = None
    # The date received by the state in NY = the notice date (for an amendment — the amendment date)
    df["notice_date"] = df.amended_date.where(df.is_amendment & df.amended_date.notna(), df.letter_date)
    df["layoff_type"] = df.type_raw.map(_ltype)
    df["source"] = "ny_html"
    return pd.concat([df, parse_ny_tableau(df)], ignore_index=True)


NY_HTML_END = pd.Timestamp("2025-04-01")  # the "retired database" covers postings up to this date


def _nkey(name, date):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())[:12] + "|" + str(pd.Timestamp(date).date() if pd.notna(date) else "")


def parse_ny_tableau(html_df):
    """The NY dashboard (postings from 2025-01). One row = one site. For amendments Date Posted
    is overwritten with the amendment date, the original posting date is not kept."""
    files = [(u, p) for u, p in latest_raw("NY").items() if p.name.startswith("tableau_warn_list")]
    if not files:
        return pd.DataFrame()
    url, p = files[-1]
    x = pd.read_csv(p, dtype=str)
    rows = []
    for _, r in x.iterrows():
        rows.append(dict(company_raw=_clean(r["Business Legal Name"]), address=_clean(r["Impacted Site Address"]),
                         county=_clean(r["Impacted Site County"]), letter_date=_d(r["Date of WARN Notice"]),
                         posted_date=_d(r["Date Posted"]), effective_date=_d(r["Date Layoff/Closure Starts"]),
                         effective_raw=r["Date Layoff/Closure Starts"], employees=_int(r["Number of Affected Workers"]),
                         type_raw=f"{r['Layoff or Closure?']} {r['Permanent or Temporary Layoff?']}",
                         is_amendment=False, is_rescinded=False, source_url=url.split("#")[0], raw_file=_rel(p)))
    df = pd.DataFrame(rows)
    df["state"] = "NY"
    df["city"] = None
    df["notice_date"] = df.letter_date
    df["layoff_type"] = df.type_raw.map(_ltype)
    df["source"] = "ny_tableau"
    # the HTML archive period is taken from the HTML (exact posting dates + FEIN)
    early = df.posted_date < NY_HTML_END
    # repeated postings (amendments) of notices from the HTML era — also from the HTML
    html_keys = set(_nkey(n, d) for n, d in zip(html_df.company_raw, html_df.letter_date))
    dup = df.apply(lambda r: _nkey(r.company_raw, r.letter_date) in html_keys, axis=1)
    print(f"NY Tableau: {len(df)} rows, dropped as posted before {NY_HTML_END.date()}: {int(early.sum())}, "
          f"repeats of HTML-era notices: {int((dup & ~early).sum())}")
    return df[~early & ~dup]


def _month_date(s):
    m = re.search(r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\.? \d{1,2}, ?\d{4})", str(s or ""))
    return m.group(1) if m else None


# ---------------- NJ ----------------
def parse_nj():
    rows = []
    for url, p in latest_raw("NJ").items():
        x = pd.read_excel(p, sheet_name=None)
        for sh, d in x.items():
            m = re.match(r"(\d{4})", sh)
            if not m:
                continue
            year = int(m.group(1))
            d.columns = [str(c).strip().lower() for c in d.columns]
            for _, r in d.iterrows():
                if pd.isna(r.get("company")):
                    continue
                mon = str(r.get("month posted", "")).strip()
                rows.append(dict(company_raw=_clean(r["company"]), city=_clean(r.get("city")),
                                 month_posted=_d(f"{mon} 1 {year}") if mon and mon != "nan" else pd.NaT,
                                 effective_raw=str(r.get("effective date")),
                                 effective_date=_d(r.get("effective date")) if not isinstance(r.get("effective date"), str)
                                 else _first_date(r.get("effective date")),
                                 employees=_int(r.get("workforce affected")), source_url=url, raw_file=_rel(p)))
    df = pd.DataFrame(rows)
    df["state"] = "NJ"
    df["notice_date"] = pd.NaT  # publication month only
    df["layoff_type"] = None
    df["is_amendment"] = df.company_raw.str.contains(r"amend", case=False)
    return df


PARSERS = {"CA": parse_ca, "WA": parse_wa, "TX": parse_tx, "NY": parse_ny, "NJ": parse_nj}
