"""Zentrale Parameter – entsprechen dem Regelwerk. Hier anpassen, nicht im Code."""

# --- Gemeinsame Regeln ---
MIN_TURNOVER = 5_000_000          # Ø Tagesumsatz (Kurs x Volumen, 20 Tage) in EUR/USD
DEPOT_EUR = 10_000                # Spieldepot
RISK_PER_TRADE = 0.01             # 1 % -> 100 EUR
KO_BUFFER = 0.03                  # Knock-out-Schwelle mind. 3 % unter dem Stop
GAP_MAX = 0.03                    # Folgetag: Einstieg nur bis Signalkurs +3 %
COST_PER_TRADE = 0.01             # 1 % Kostenpauschale (Spread + Gebühr) im Protokoll
EARNINGS_BLOCK_DAYS = 7           # Kalendertage (~5 Handelstage) Zahlen-Sperre für A und B
TOP_N = 5                         # max. Signale pro Lauf für Claudes Einschätzung

# --- Strategie A: Turnaround ---
A_DROP = -0.15                    # mind. -15 % ...
A_LOOKBACK = 10                   # ... in 10 Handelstagen
A_RSI_MAX = 30
A_RSI_DAYS = 3
A_VOL_MULT = 1.5
A_MAX_BELOW_HIGH = 0.40           # höchstens 40 % unter 52-Wochen-Hoch
A_TARGET = 0.08
A_TIME_STOP = 10

# --- Strategie B: Momentum-Ausbruch ---
B_VOL_MULT = 1.5
B_MAX_ABOVE_SMA20 = 0.10
B_TOP_QUANTILE = 0.75             # 6-Monats-Performance im oberen Viertel
B_INITIAL_STOP = 0.07
B_TIME_STOP = 40

# --- Strategie C: Drift nach Quartalszahlen ---
C_MIN_REACTION = 0.05
C_VOL_MULT = 2.0
C_UPPER_RANGE = 2 / 3             # Schluss im oberen Drittel der Tagesspanne
C_EARNINGS_MAX_DAYS = 4           # Zahlen max. 4 Kalendertage vor dem Signaltag
C_TARGET = 0.10
C_TIME_STOP = 20

STRATEGY_NAMES = {
    "A": "Turnaround",
    "B": "Momentum-Ausbruch",
    "C": "Drift nach Zahlen",
}
