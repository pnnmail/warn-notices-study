"""Stage 4: daily prices (yfinance) for event tickers, SPY and sector ETFs.
Saves data/prices.parquet (long format: date, ticker, close, adj_close, volume).
Plus a company reference data/company_info.parquet: sector (from the SIC in EDGAR) and headcount
(fullTimeEmployees from yfinance — the current value; headcount is not tagged in XBRL in the 10-K)."""
import json
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import DATA, get_logger  # noqa: E402
from match.sec_reference import SUB_DIR  # noqa: E402

log = get_logger("prices")
START = "2021-10-01"
SECTOR_ETFS = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]


def sic_sector(sic):
    """SIC -> sector SPDR ETF (a rough mapping)."""
    if not sic:
        return None
    s = int(sic)
    if 100 <= s < 1000:
        return "XLP"
    if 1000 <= s < 1500 or 2900 <= s < 3000:
        return "XLE" if s in range(1300, 1400) or s >= 2900 else "XLB"
    if 1500 <= s < 1800:
        return "XLI"
    if 2000 <= s < 2200:
        return "XLP"
    if 2830 <= s < 2840 or 3840 <= s < 3860 or 8000 <= s < 8100 or s in (5122, 5912):
        return "XLV"
    if 2800 <= s < 2900 or 2400 <= s < 2700 or 3300 <= s < 3400:
        return "XLB"
    if 3570 <= s < 3580 or 3600 <= s < 3700 or 7370 <= s < 7380 or s == 3661:
        return "XLK"
    if 4800 <= s < 4900 or 2700 <= s < 2800 or 7810 <= s < 7820 or s in (7812, 7822):
        return "XLC"
    if 4900 <= s < 5000:
        return "XLU"
    if 6500 <= s < 6800 and s not in (6770,):
        return "XLRE" if 6500 <= s < 6600 or s == 6798 else "XLF"
    if 6000 <= s < 6500:
        return "XLF"
    if 5200 <= s < 6000 or 2200 <= s < 2400 or 3710 <= s < 3720 or 7000 <= s < 7100 or 5000 <= s < 5200:
        return "XLY" if not 5140 <= s < 5150 else "XLP"
    return "XLI"


def main():
    ev = pd.read_parquet(DATA / "events.parquet")
    tickers = sorted(ev.ticker.dropna().unique())
    allt = tickers + ["SPY"] + SECTOR_ETFS
    frames = []
    for i in range(0, len(allt), 50):
        chunk = allt[i:i + 50]
        df = yf.download(chunk, start=START, auto_adjust=False, progress=False, group_by="ticker", threads=True)
        for t in chunk:
            try:
                x = df[t][["Close", "Adj Close", "Volume"]].dropna(subset=["Adj Close"])
            except KeyError:
                continue
            x = x.rename(columns={"Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
            x["ticker"] = t
            frames.append(x.reset_index().rename(columns={"Date": "date"}))
        log.info("prices: %d/%d", min(i + 50, len(allt)), len(allt))
        time.sleep(2)
    px = pd.concat(frames, ignore_index=True)
    px["date"] = pd.to_datetime(px.date).dt.tz_localize(None).dt.normalize()
    px.to_parquet(DATA / "prices.parquet", index=False)
    missing = sorted(set(allt) - set(px.ticker))
    log.info("prices: %d rows, tickers %d; without prices: %s", len(px), px.ticker.nunique(), missing)

    rows = []
    for t, cik in ev.drop_duplicates("ticker")[["ticker", "cik"]].itertuples(index=False):
        sp = SUB_DIR / f"{int(cik)}.json"
        sub = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        emp = None
        try:
            emp = yf.Ticker(t).info.get("fullTimeEmployees")
        except Exception as e:  # info is unavailable for some tickers
            log.warning("info %s: %s", t, e)
        rows.append(dict(ticker=t, cik=int(cik), sic=sub.get("sic"), sic_desc=sub.get("sicDescription"),
                         sector_etf=sic_sector(sub.get("sic")), employees_total=emp))
        time.sleep(0.3)
    info = pd.DataFrame(rows)
    info.to_parquet(DATA / "company_info.parquet", index=False)
    log.info("reference: %d companies, headcount available for %d", len(info), info.employees_total.notna().sum())


if __name__ == "__main__":
    main()
