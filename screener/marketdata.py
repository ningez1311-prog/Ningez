"""Kursdaten und Zahlentermine über yfinance (kostenlos, Tagesdaten)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def download(tickers: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    import yfinance as yf
    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), 200):
        chunk = tickers[i:i + 200]
        raw = yf.download(chunk, period=period, interval="1d", group_by="ticker",
                          auto_adjust=True, threads=True, progress=False)
        for t in chunk:
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                if len(df):
                    df.index = pd.to_datetime(df.index).tz_localize(None)
                    out[t] = df
            except KeyError:
                pass
    return out


def earnings_dates(ticker: str) -> list[date]:
    """Vergangene und kommende Zahlentermine. Leere Liste = unbekannt."""
    import yfinance as yf
    tk = yf.Ticker(ticker)
    dates: set[date] = set()
    try:
        ed = tk.get_earnings_dates(limit=12)
        if ed is not None:
            dates |= {pd.Timestamp(d).date() for d in ed.index}
    except Exception:  # noqa: BLE001
        pass
    try:
        cal = tk.calendar or {}
        for d in cal.get("Earnings Date", []) or []:
            dates.add(pd.Timestamp(d).date())
    except Exception:  # noqa: BLE001
        pass
    return sorted(dates)


def recent_earnings(dates: list[date], bar_date: date, max_days: int) -> bool | None:
    if not dates:
        return None
    return any(bar_date - timedelta(days=max_days) <= d <= bar_date for d in dates)


def upcoming_earnings(dates: list[date], bar_date: date, days: int) -> bool | None:
    if not dates:
        return None
    return any(bar_date < d <= bar_date + timedelta(days=days) for d in dates)
