"""Aktienliste: DAX, MDAX, TecDAX (Region de) sowie S&P 500 und Nasdaq 100 (Region us).

Die Zusammensetzung wird wöchentlich von Wikipedia aktualisiert und in
data/universe.csv zwischengespeichert. Schlägt der Abruf fehl, wird der
Zwischenstand weiterverwendet.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (trading-screener; personal use)"}

# Reihenfolge = Priorität für den Marktfilter (erstes Vorkommen gewinnt)
SOURCES = [
    # name, region, url, Benchmark-Index (Yahoo), Mindestanzahl
    ("DAX", "de", "https://en.wikipedia.org/wiki/DAX", "^GDAXI", 35),
    ("MDAX", "de", "https://en.wikipedia.org/wiki/MDAX", "^MDAXI", 40),
    ("TecDAX", "de", "https://de.wikipedia.org/wiki/TecDAX", "^TECDAX", 25),
    ("S&P 500", "us", "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "^GSPC", 480),
    ("Nasdaq 100", "us", "https://de.wikipedia.org/wiki/NASDAQ-100", "^NDX", 95),
]
TICKER_COLS = ["Symbol", "Ticker", "Ticker symbol", "Ticker Symbol"]
MAX_AGE_DAYS = 7


def _normalize(sym: str, region: str) -> str | None:
    s = str(sym).strip().split(":")[-1].strip().split(" ")[0]
    if not s or s.lower() == "nan":
        return None
    if region == "us":
        return s.replace(".", "-")          # BRK.B -> BRK-B (Yahoo-Schreibweise)
    return s if "." in s else f"{s}.DE"     # Xetra-Kürzel -> Yahoo-Schreibweise


NAME_COLS = ["Security", "Company", "Name", "Company name"]


def _fetch(name, region, url, min_rows) -> list[tuple[str, str]]:
    html = requests.get(url, headers=UA, timeout=30).text
    for tbl in pd.read_html(io.StringIO(html)):
        clean = {c: str(c).split("[")[0].strip() for c in tbl.columns}   # "Symbol[9]" -> "Symbol"
        cols = [c for c in tbl.columns if clean[c] in TICKER_COLS]
        if cols and len(tbl) >= min_rows:
            ncol = next((c for c in tbl.columns if clean[c] in NAME_COLS or clean[c].startswith("Name")), None)
            names = tbl[ncol].astype(str) if ncol else [""] * len(tbl)
            out = [(_normalize(x, region), n) for x, n in zip(tbl[cols[0]], names)]
            return [(t, n) for t, n in out if t]
    raise ValueError(f"{name}: keine passende Tabelle gefunden")


def load(cache: Path) -> pd.DataFrame:
    # Datei-Zeitstempel sind nach einem Git-Checkout wertlos -> Datum in der Datei
    old = (pd.read_csv(cache) if cache.exists()
           else pd.DataFrame(columns=["ticker", "name", "region", "index", "benchmark", "updated"]))
    if len(old) and "updated" in old.columns:
        age = (pd.Timestamp.today().normalize() - pd.Timestamp(old["updated"].iloc[0])).days
        complete = set(old["index"]) >= {src[0] for src in SOURCES}
        if age < MAX_AGE_DAYS and complete:
            return old
    rows = []
    for name, region, url, bench, min_rows in SOURCES:
        try:
            items = _fetch(name, region, url, min_rows)
            print(f"Universum {name}: {len(items)} Titel")
        except Exception as e:  # noqa: BLE001
            print(f"WARNUNG {name}: {e} – nutze Zwischenstand")
            sub = old[old["index"] == name]
            items = list(zip(sub["ticker"], sub["name"].fillna("")))
        rows += [{"ticker": t, "name": n, "region": region, "index": name, "benchmark": bench}
                 for t, n in items]
    uni = pd.DataFrame(rows).drop_duplicates("ticker", keep="first")
    uni["updated"] = pd.Timestamp.today().strftime("%Y-%m-%d")
    if len(uni):
        uni.to_csv(cache, index=False)
    return uni
