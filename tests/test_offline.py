"""Offline-Test mit künstlichen Kursen: prüft Signale, Papier-Trades und den ganzen Lauf.

    python -m tests.test_offline
"""
import json
import shutil
import sys
import tempfile
import types
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from screener import papertrades, strategies

DAYS = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=300)


def frame(close, vol=None, spread=0.01):
    close = np.asarray(close, float)
    vol = np.full(len(close), 1_000_000.0) if vol is None else np.asarray(vol, float)
    opn = np.r_[close[0], close[:-1]]
    hi = np.maximum(opn, close) * (1 + spread)
    lo = np.minimum(opn, close) * (1 - spread)
    return pd.DataFrame({"Open": opn, "High": hi, "Low": lo, "Close": close, "Volume": vol},
                        index=DAYS[-len(close):])


def turnaround():
    c = list(np.linspace(80, 100, 288)) + [95, 90, 86, 82, 79, 77, 75, 74, 73, 72, 71]
    c = c + [76]                            # kräftige Erholung am letzten Tag
    v = [1e6] * (len(c) - 1) + [3e6]
    df = frame(c, v)
    df.iloc[-1, df.columns.get_loc("Open")] = 71.5
    df.iloc[-1, df.columns.get_loc("Low")] = 71.0
    df.iloc[-1, df.columns.get_loc("High")] = 76.5
    return df


def breakout():
    c = list(np.linspace(50, 100, 299)) + [104]
    return frame(c, [1e6] * 299 + [2e6])


def earnings_jump():
    c = list(np.linspace(90, 100, 299)) + [108]
    df = frame(c, [1e6] * 299 + [3e6])
    df.iloc[-1, df.columns.get_loc("Low")] = 100.5
    df.iloc[-1, df.columns.get_loc("High")] = 108.2
    return df


def flat():
    return frame(np.full(300, 50.0) + np.sin(np.arange(300)) * 0.2)


def test_strategies():
    a = strategies.strategy_a(strategies.add_indicators(turnaround()))
    assert a and a["strategy"] == "A", a
    b = strategies.strategy_b(strategies.add_indicators(breakout()), perf_threshold=0.1)
    assert b and b["strategy"] == "B", b
    c = strategies.strategy_c_candidate(strategies.add_indicators(earnings_jump()))
    assert c and c["strategy"] == "C", c
    f = strategies.add_indicators(flat())
    assert not strategies.strategy_a(f) and not strategies.strategy_b(f, 0) and not strategies.strategy_c_candidate(f)
    print("Strategien OK:", a["detail"], "|", b["detail"], "|", c["detail"])


def test_papertrades():
    idx = pd.bdate_range("2026-01-05", periods=6)
    df = pd.DataFrame({"Open": [100, 101, 102, 104, 107, 108], "High": [101, 103, 105, 109, 108, 109],
                       "Low": [99, 100, 101, 103, 106, 107], "Close": [100, 102, 104, 108, 107, 108],
                       "Volume": 1e6}, index=idx)
    df = strategies.add_indicators(df)
    proto = papertrades.load(Path("/nonexistent"))
    sig = dict(bar_date="2026-01-05", strategy="A", ticker="X", close=100, stop=95,
               target_pct=0.08, time_stop=10)
    proto = papertrades.add_signal(proto, "de", sig)
    proto = papertrades.add_signal(proto, "de", sig)        # Duplikat wird ignoriert
    assert len(proto) == 1
    closed = papertrades.update(proto, "de", {"X": df.iloc[:3]})
    assert proto.at[0, "status"] == "open" and not closed
    closed = papertrades.update(proto, "de", {"X": df})       # Ziel 101*1.08=109.08 -> nicht erreicht
    assert proto.at[0, "status"] == "open", proto.iloc[0].to_dict()
    assert int(proto.at[0, "bars_held"]) == 5
    # Gap-Fall
    sig2 = dict(sig, bar_date="2026-01-05", ticker="Y", close=90)   # max_entry 92.7 < Open 101
    proto = papertrades.add_signal(proto, "de", sig2)
    papertrades.update(proto, "de", {"Y": df})
    assert proto.loc[proto.ticker == "Y", "status"].iloc[0] == "skipped"
    # Stop-Fall
    sig3 = dict(sig, ticker="Z", stop=103.5)                       # Einstieg 101, Tief 100 am Tag 1 -> Stop
    proto = papertrades.add_signal(proto, "de", sig3)
    closed = papertrades.update(proto, "de", {"Z": df})
    z = proto[proto.ticker == "Z"].iloc[0]
    assert z["status"] == "skipped" and "unter Stop" in z["exit_reason"], z.to_dict()
    sig4 = dict(sig, ticker="W", stop=100.5)
    proto = papertrades.add_signal(proto, "de", sig4)
    closed = papertrades.update(proto, "de", {"W": df})
    w = proto[proto.ticker == "W"].iloc[0]
    assert w["status"] == "closed" and w["exit_reason"] == "Stop" and closed, w.to_dict()
    print("Papier-Trades OK:", papertrades.stats(proto)["A"])


def test_full_run():
    tmp = Path(tempfile.mkdtemp())
    root = Path(__file__).resolve().parent.parent
    for d in ("data", "signals"):
        (tmp / d).mkdir()
    pd.DataFrame([
        {"ticker": "TURN.DE", "name": "Turn AG", "region": "de", "index": "MDAX", "benchmark": "^MDAXI"},
        {"ticker": "BRK.DE", "name": "Break AG", "region": "de", "index": "DAX", "benchmark": "^GDAXI"},
        {"ticker": "EARN.DE", "name": "Earn AG", "region": "de", "index": "DAX", "benchmark": "^GDAXI"},
        {"ticker": "NOEARN.DE", "name": "Noearn AG", "region": "de", "index": "DAX", "benchmark": "^GDAXI"},
        {"ticker": "FLAT.DE", "name": "Flat AG", "region": "de", "index": "TecDAX", "benchmark": "^TECDAX"},
    ]).assign(updated=date.today().isoformat()).to_csv(tmp / "data" / "universe.csv", index=False)

    rising = frame(np.linspace(10000, 16000, 300))
    falling = frame(np.linspace(16000, 10000, 300))
    fake = types.ModuleType("screener.marketdata")
    fake.download = lambda tickers, period="2y": {
        "TURN.DE": turnaround(), "BRK.DE": breakout(), "EARN.DE": earnings_jump(),
        "NOEARN.DE": earnings_jump(), "FLAT.DE": flat(),
        "^GDAXI": rising, "^MDAXI": rising, "^TECDAX": falling}
    today = DAYS[-1].date()
    fake.earnings_dates = lambda t: {"EARN.DE": [today], "NOEARN.DE": [date(2025, 1, 1)]}.get(t, [])
    from screener import marketdata as real  # noqa: F401  (nur Signaturen)
    fake.recent_earnings = real.recent_earnings
    fake.upcoming_earnings = real.upcoming_earnings
    sys.modules["screener.marketdata"] = fake
    import screener
    screener.marketdata = fake

    from screener import run
    run.DATA, run.SIGNALS = tmp / "data", tmp / "signals"
    assert run.main(["--region", "de", "--force"]) == 0
    out = json.loads((tmp / "signals" / "latest_de.json").read_text())
    names = sorted(s["ticker"] for s in out["top_signale"])
    print(json.dumps(out["top_signale"][0], ensure_ascii=False, indent=1))
    print("Top:", names, "| Marktfilter:", out["marktfilter"], "| weitere:", out["weitere_signale"])
    assert len(names) == len(set(names)) and "FLAT.DE" not in names, names
    proto = pd.read_csv(tmp / "data" / "protocol.csv")
    assert len(proto) >= len(names)
    shutil.rmtree(tmp)
    print("Gesamtlauf OK")


if __name__ == "__main__":
    test_strategies()
    test_papertrades()
    test_full_run()
