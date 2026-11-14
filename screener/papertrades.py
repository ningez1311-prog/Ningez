"""Protokoll: jedes Signal wird als Papier-Trade nach festen Regeln verfolgt.

Status: pending -> open -> closed, oder skipped (Gap / unter Stop).
Stop und Ziel werden auf Tagesbasis geprüft (Tief/Hoch), wie eine echte
Stop-Order. Treffen Stop und Ziel am selben Tag, zählt konservativ der Stop.
"""
from __future__ import annotations

import pandas as pd

from . import config as C

COLUMNS = [
    "id", "region", "strategy", "ticker", "index", "signal_date", "signal_close",
    "stop", "target_pct", "time_stop", "max_entry", "market_ok", "earnings_flag",
    "in_top", "rank_score", "status", "entry_date", "entry_price", "target",
    "exit_date", "exit_price", "exit_reason", "bars_held", "ret_pct", "last_checked",
]


def load(path) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, dtype={"id": str})
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df[COLUMNS].astype(object)
    except FileNotFoundError:
        return pd.DataFrame(columns=COLUMNS).astype(object)


def add_signal(proto: pd.DataFrame, region: str, sig: dict) -> pd.DataFrame:
    sid = f"{sig['bar_date']}-{sig['strategy']}-{sig['ticker']}"
    if (proto["id"] == sid).any():
        return proto
    row = {c: None for c in COLUMNS}
    row.update(
        id=sid, region=region, strategy=sig["strategy"], ticker=sig["ticker"],
        index=sig.get("index"), signal_date=sig["bar_date"], signal_close=sig["close"],
        stop=sig["stop"], target_pct=sig["target_pct"], time_stop=sig["time_stop"],
        max_entry=round(sig["close"] * (1 + C.GAP_MAX), 4), market_ok=sig.get("market_ok"),
        earnings_flag=sig.get("earnings_flag"), in_top=sig.get("in_top", False),
        rank_score=sig.get("rank_score"), status="pending", bars_held=0,
    )
    return pd.concat([proto, pd.DataFrame([row])], ignore_index=True)


def _close(row, date, price, reason):
    row["status"] = "closed"
    row["exit_date"] = date.strftime("%Y-%m-%d")
    row["exit_price"] = round(float(price), 4)
    row["exit_reason"] = reason
    row["ret_pct"] = round(float(price) / float(row["entry_price"]) - 1 - C.COST_PER_TRADE, 4)


def _step(row: dict, date, bar) -> None:
    """Einen Handelstag auf einen offenen Trade anwenden."""
    stop, target = float(row["stop"]), row["target"]
    row["bars_held"] = int(row["bars_held"] or 0) + 1
    hit_stop = bar["Low"] <= stop
    hit_target = target is not None and pd.notna(target) and bar["High"] >= float(target)
    if hit_stop:
        _close(row, date, min(bar["Open"], stop), "Stop")
    elif hit_target:
        _close(row, date, max(bar["Open"], float(target)), "Ziel")
    elif row["strategy"] == "B" and pd.notna(bar.get("sma20")) and bar["Close"] < bar["sma20"]:
        _close(row, date, bar["Close"], "Unter 20-Tage-Linie")
    elif row["bars_held"] >= int(row["time_stop"]):
        _close(row, date, bar["Close"], "Zeitstop")


def update(proto: pd.DataFrame, region: str, data: dict[str, pd.DataFrame]) -> list[dict]:
    """Offene und wartende Trades mit neuen Kursdaten fortschreiben.
    Gibt die heute geschlossenen Trades zurück."""
    closed_now = []
    for i, r in proto.iterrows():
        if r["region"] != region or r["status"] not in ("pending", "open"):
            continue
        df = data.get(r["ticker"])
        if df is None:
            continue
        row = r.to_dict()
        last = row["last_checked"] if pd.notna(row["last_checked"]) and row["last_checked"] else row["signal_date"]
        new_bars = df[df.index > pd.Timestamp(last)]
        for date, bar in new_bars.iterrows():
            row["last_checked"] = date.strftime("%Y-%m-%d")
            if row["status"] == "pending":
                o = float(bar["Open"])
                if o > float(row["max_entry"]):
                    row.update(status="skipped", exit_reason="Gap über Einstiegsgrenze",
                               exit_date=date.strftime("%Y-%m-%d"))
                    break
                if o <= float(row["stop"]):
                    row.update(status="skipped", exit_reason="Eröffnung unter Stop",
                               exit_date=date.strftime("%Y-%m-%d"))
                    break
                row["status"] = "open"
                row["entry_date"] = date.strftime("%Y-%m-%d")
                row["entry_price"] = round(o, 4)
                tp = row["target_pct"]
                row["target"] = round(o * (1 + float(tp)), 4) if tp is not None and pd.notna(tp) else None
                row["bars_held"] = 0
                _step(row, date, bar)        # Einstiegstag zählt mit
            elif row["status"] == "open":
                _step(row, date, bar)
            if row["status"] == "closed":
                closed_now.append(row)
                break
        for k in COLUMNS:
            proto.at[i, k] = row[k]
    return closed_now


def stats(proto: pd.DataFrame) -> dict:
    out = {}
    for strat, name in C.STRATEGY_NAMES.items():
        p = proto[proto["strategy"] == strat]
        closed = p[p["status"] == "closed"]
        r = pd.to_numeric(closed["ret_pct"], errors="coerce").dropna()
        wins, losses = r[r > 0], r[r <= 0]
        out[strat] = {
            "name": name,
            "signale": int(len(p)),
            "offen": int((p["status"] == "open").sum()),
            "wartend": int((p["status"] == "pending").sum()),
            "ausgelassen": int((p["status"] == "skipped").sum()),
            "geschlossen": int(len(r)),
            "trefferquote": round(float(len(wins) / len(r)), 3) if len(r) else None,
            "avg_gewinn": round(float(wins.mean()), 4) if len(wins) else None,
            "avg_verlust": round(float(losses.mean()), 4) if len(losses) else None,
            "erwartungswert": round(float(r.mean()), 4) if len(r) else None,
        }
    return out
