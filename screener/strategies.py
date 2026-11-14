"""Indikatoren und Signalregeln der Strategien A, B und C.

Alle Funktionen arbeiten auf einem DataFrame mit den Spalten
Open, High, Low, Close, Volume (Tagesdaten, aufsteigend sortiert).
Geprüft wird immer der letzte Handelstag (Signaltag).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["Close"]
    df["sma20"] = close.rolling(20).mean()
    df["sma50"] = close.rolling(50).mean()
    df["sma200"] = close.rolling(200).mean()
    # Volumen-Durchschnitt der 20 Tage VOR dem jeweiligen Tag
    df["vol20"] = df["Volume"].shift(1).rolling(20).mean()
    df["turnover20"] = (close * df["Volume"]).rolling(20).mean()
    df["hi252"] = close.rolling(252, min_periods=200).max()
    df["perf126"] = close / close.shift(126) - 1
    # RSI(14) nach Wilder
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi14"] = 100 - 100 / (1 + rs)
    df.loc[loss == 0, "rsi14"] = 100
    return df


def _base(df: pd.DataFrame) -> dict:
    t = df.iloc[-1]
    return {
        "bar_date": df.index[-1].strftime("%Y-%m-%d"),
        "close": round(float(t["Close"]), 4),
        "vol_ratio": round(float(t["Volume"] / t["vol20"]), 2) if t["vol20"] > 0 else None,
    }


def liquid(df: pd.DataFrame) -> bool:
    v = df["turnover20"].iloc[-1]
    return bool(pd.notna(v) and v >= C.MIN_TURNOVER)


def strategy_a(df: pd.DataFrame) -> dict | None:
    """Turnaround nach Abverkauf."""
    if len(df) < 60:
        return None
    t, prev = df.iloc[-1], df.iloc[-2]
    window = df.iloc[-(C.A_LOOKBACK + 1):]            # Signaltag + 10 Tage davor
    peak = df["Close"].iloc[-(C.A_LOOKBACK + 1):-1].max()
    low = window["Low"].min()
    drop = low / peak - 1
    if drop > C.A_DROP:
        return None
    if df["rsi14"].iloc[-(C.A_RSI_DAYS + 1):-1].min() >= C.A_RSI_MAX:
        return None
    if not (t["Close"] > prev["High"] and t["Close"] > t["Open"]):
        return None
    if not (t["vol20"] > 0 and t["Volume"] > C.A_VOL_MULT * t["vol20"]):
        return None
    if pd.notna(t["hi252"]) and t["Close"] < (1 - C.A_MAX_BELOW_HIGH) * t["hi252"]:
        return None
    s = _base(df)
    s.update(
        strategy="A",
        stop=round(float(low), 4),
        target_pct=C.A_TARGET,
        time_stop=C.A_TIME_STOP,
        detail=f"Abverkauf {drop:.0%} in {C.A_LOOKBACK} Tagen, Erholung mit {s['vol_ratio']}x Volumen",
        rank_score=round(abs(drop) * (s["vol_ratio"] or 1), 4),
        drop=round(float(drop), 4),
    )
    return s


def strategy_b(df: pd.DataFrame, perf_threshold: float) -> dict | None:
    """Momentum-Ausbruch auf neues 52-Wochen-Hoch."""
    if len(df) < 253:
        return None
    t = df.iloc[-1]
    prior_high = df["Close"].iloc[-253:-1].max()
    if t["Close"] <= prior_high:
        return None
    if not (t["vol20"] > 0 and t["Volume"] > C.B_VOL_MULT * t["vol20"]):
        return None
    if not (t["Close"] > t["sma50"] > t["sma200"]):
        return None
    if t["Close"] / t["sma20"] - 1 > C.B_MAX_ABOVE_SMA20:
        return None
    if pd.isna(t["perf126"]) or t["perf126"] < perf_threshold:
        return None
    s = _base(df)
    s.update(
        strategy="B",
        stop=round(float(t["Close"] * (1 - C.B_INITIAL_STOP)), 4),
        target_pct=None,
        time_stop=C.B_TIME_STOP,
        detail=f"Neues 52W-Hoch, 6M-Performance {t['perf126']:.0%}, {s['vol_ratio']}x Volumen",
        rank_score=round(float(t["perf126"]), 4),
    )
    return s


def strategy_c_candidate(df: pd.DataFrame) -> dict | None:
    """Kursreaktion wie nach Zahlen. Ob es wirklich Zahlen waren, prüft run.py."""
    if len(df) < 30:
        return None
    t, prev = df.iloc[-1], df.iloc[-2]
    reaction = t["Close"] / prev["Close"] - 1
    if reaction < C.C_MIN_REACTION:
        return None
    if not (t["vol20"] > 0 and t["Volume"] > C.C_VOL_MULT * t["vol20"]):
        return None
    rng = t["High"] - t["Low"]
    if rng <= 0 or (t["Close"] - t["Low"]) / rng < C.C_UPPER_RANGE:
        return None
    s = _base(df)
    s.update(
        strategy="C",
        stop=round(float(t["Low"]), 4),
        target_pct=C.C_TARGET,
        time_stop=C.C_TIME_STOP,
        detail=f"Kursreaktion +{reaction:.1%} mit {s['vol_ratio']}x Volumen",
        rank_score=round(reaction * (s["vol_ratio"] or 1), 4),
    )
    return s


def market_filter_ok(index_df: pd.DataFrame | None) -> bool | None:
    if index_df is None or len(index_df) < 200:
        return None
    c = index_df["Close"]
    return bool(c.iloc[-1] > c.rolling(200).mean().iloc[-1])
