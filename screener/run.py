"""Täglicher Screener-Lauf.

    python -m screener.run --region de     # nach Xetra-Schluss
    python -m screener.run --region us     # nach US-Schluss

Schreibt:
    signals/latest_<region>.json   -> wird von Claude gelesen
    data/protocol.csv              -> alle Signale + Papier-Trades
    signals/stats.json             -> Kennzahlen je Strategie
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import config as C
from . import papertrades, strategies, universe

ROOT = Path(__file__).resolve().parent.parent
DATA, SIGNALS = ROOT / "data", ROOT / "signals"

REGIONS = {
    # Zeitzone der Börse, frühester Start (Ortszeit), Börse
    "de": ("Europe/Berlin", (17, 40), "Xetra"),
    "us": ("America/New_York", (16, 10), "NYSE/Nasdaq"),
}


def position_hint(close: float, stop: float) -> dict:
    """Knock-out-Schwelle 3 % unter dem Stop; Einsatz so, dass der Verlust bei Stop = 1 % Depot."""
    ko = stop * (1 - C.KO_BUFFER)
    risk_eur = C.DEPOT_EUR * C.RISK_PER_TRADE
    loss_frac = (close - stop) / (close - ko)          # Anteil des KO-Werts, der beim Stop verloren geht
    return {
        "stop_abstand_pct": round((close - stop) / close, 4),
        "ko_schwelle_max": round(ko, 4),
        "hebel_max": round(close / (close - ko), 1),
        "max_einsatz_eur": round(risk_eur / loss_frac, 0),
        "max_verlust_eur": risk_eur,
    }


def pick_top(signals: list[dict], n: int) -> list[dict]:
    """Abwechselnd das jeweils stärkste Signal je Strategie (A, B, C), bis n erreicht."""
    by = {s: sorted([x for x in signals if x["strategy"] == s], key=lambda x: -x["rank_score"])
          for s in C.STRATEGY_NAMES}
    out, seen = [], set()
    while len(out) < n and any(by.values()):
        for s in C.STRATEGY_NAMES:
            while by[s] and by[s][0]["ticker"] in seen:     # max. 1 Signal je Aktie
                by[s].pop(0)
            if by[s] and len(out) < n:
                x = by[s].pop(0)
                out.append(x)
                seen.add(x["ticker"])
    return out


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", choices=REGIONS, required=True)
    ap.add_argument("--force", action="store_true", help="Zeit- und Doppellauf-Prüfung überspringen")
    args = ap.parse_args(argv)
    region = args.region
    tz, (h, m), exchange = REGIONS[region]
    now = datetime.now(ZoneInfo(tz))
    latest_path = SIGNALS / f"latest_{region}.json"

    if not args.force and (now.hour, now.minute) < (h, m):
        print(f"Zu früh ({now:%H:%M} {tz}) – Lauf übersprungen.")
        return 0

    from . import marketdata  # erst hier, damit Tests ohne yfinance laufen

    uni = universe.load(DATA / "universe.csv")
    uni = uni[uni["region"] == region]
    benchmarks = sorted(uni["benchmark"].unique())
    data = marketdata.download(uni["ticker"].tolist() + benchmarks)
    print(f"{len(data)} von {len(uni) + len(benchmarks)} Kursreihen geladen")

    last_dates = pd.Series({t: df.index[-1] for t, df in data.items() if t not in benchmarks})
    bar_date = last_dates.mode().iloc[0]
    today = now.date()

    if bar_date.date() != today and not args.force:
        write_json(latest_path, {"status": "kein_handelstag", "region": region,
                                 "erstellt": now.isoformat(timespec="minutes"),
                                 "letzter_handelstag": bar_date.strftime("%Y-%m-%d")})
        print("Heute kein Handelstag – nichts zu tun.")
        return 0

    if latest_path.exists() and not args.force:
        prev = json.loads(latest_path.read_text(encoding="utf-8"))
        if prev.get("status") == "ok" and prev.get("handelstag") == bar_date.strftime("%Y-%m-%d"):
            print("Für diesen Handelstag bereits gelaufen.")
            return 0

    market_ok = {b: strategies.market_filter_ok(data.get(b)) for b in benchmarks}
    bench_name = dict(zip(uni["benchmark"], uni["index"]))
    meta = uni.set_index("ticker")

    full = {t: strategies.add_indicators(df) for t, df in data.items() if t not in benchmarks}
    ind = {t: df for t, df in full.items()
           if df.index[-1] == bar_date and len(df) >= 60 and strategies.liquid(df)}
    perf = pd.Series({t: df["perf126"].iloc[-1] for t, df in ind.items()}).dropna()
    perf_threshold = perf.quantile(C.B_TOP_QUANTILE) if len(perf) else float("inf")
    print(f"{len(ind)} liquide Titel geprüft, B-Schwelle 6M-Performance: {perf_threshold:.1%}")

    signals = []
    for t, df in ind.items():
        for fn in (strategies.strategy_a,
                   lambda d: strategies.strategy_b(d, perf_threshold),
                   strategies.strategy_c_candidate):
            s = fn(df)
            if s:
                s["ticker"] = t
                signals.append(s)

    # Zahlentermine nur für Kandidaten abfragen (spart Zeit)
    final = []
    for s in signals:
        dates = marketdata.earnings_dates(s["ticker"])
        bd = bar_date.date()
        if s["strategy"] == "C":
            recent = marketdata.recent_earnings(dates, bd, C.C_EARNINGS_MAX_DAYS)
            if recent is False:
                continue                       # Kurssprung ohne Zahlen -> kein C-Signal
            s["earnings_flag"] = "Zahlen bestätigt" if recent else "Zahlentermin nicht gefunden – bitte prüfen"
            s["blocked"] = False
        else:
            soon = marketdata.upcoming_earnings(dates, bd, C.EARNINGS_BLOCK_DAYS)
            s["earnings_flag"] = ("Zahlen in Kürze – gesperrt" if soon
                                  else "Zahlentermin unbekannt – bitte prüfen" if soon is None else "")
            s["blocked"] = bool(soon)
        row = meta.loc[s["ticker"]]
        s["name"], s["index"] = row["name"], row["index"]
        s["market_ok"] = market_ok.get(row["benchmark"])
        s["strategie_name"] = C.STRATEGY_NAMES[s["strategy"]]
        s.update(position_hint(s["close"], s["stop"]))
        s["max_einstieg"] = round(s["close"] * (1 + C.GAP_MAX), 4)
        if s["target_pct"]:
            s["ziel_ca"] = round(s["close"] * (1 + s["target_pct"]), 4)
        final.append(s)

    eligible = [s for s in final if s["market_ok"] and not s["blocked"]]
    top = pick_top(eligible, C.TOP_N)
    top_ids = {(s["strategy"], s["ticker"]) for s in top}
    for s in final:
        s["in_top"] = (s["strategy"], s["ticker"]) in top_ids

    proto = papertrades.load(DATA / "protocol.csv")
    closed_today = papertrades.update(proto, region, full)
    for s in final:
        proto = papertrades.add_signal(proto, region, s)
    proto.to_csv(DATA / "protocol.csv", index=False)
    stats = papertrades.stats(proto)
    write_json(SIGNALS / "stats.json", stats)

    open_trades = proto[(proto["region"] == region) & (proto["status"] == "open")]
    keep = ["strategie_name", "ticker", "name", "index", "close", "max_einstieg", "stop",
            "ziel_ca", "time_stop", "detail", "earnings_flag", "hebel_max", "ko_schwelle_max",
            "max_einsatz_eur", "stop_abstand_pct"]
    write_json(latest_path, {
        "status": "ok",
        "region": region,
        "boerse": exchange,
        "handelstag": bar_date.strftime("%Y-%m-%d"),
        "erstellt": now.isoformat(timespec="minutes"),
        "marktfilter": {bench_name.get(b, b): v for b, v in market_ok.items()},
        "top_signale": [{k: s.get(k) for k in keep} for s in top],
        "weitere_signale": len(final) - len(top),
        "gesperrt_oder_marktfilter": [f"{s['ticker']} ({s['strategy']}): "
                                      f"{'Zahlen in Kürze' if s['blocked'] else 'Marktfilter'}"
                                      for s in final if s not in eligible],
        "heute_geschlossene_papier_trades": [
            {k: r[k] for k in ("strategy", "ticker", "exit_reason", "ret_pct")} for r in closed_today],
        "offene_papier_trades": len(open_trades),
        "kennzahlen": stats,
    })
    print(f"{len(final)} Signale, {len(top)} für die Einschätzung, {len(closed_today)} Papier-Trades geschlossen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
