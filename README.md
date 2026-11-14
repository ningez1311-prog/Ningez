# Trading-Screener

Täglicher Screener für drei Strategien (A Turnaround, B Momentum-Ausbruch,
C Drift nach Zahlen) auf DAX, MDAX, TecDAX, S&P 500 und Nasdaq 100.
Regeln: siehe Dokument „Regelwerk Trading-Screener: 3 Strategien“.
Alle Parameter stehen in `screener/config.py`.

## Ablauf

| Zeit (Berlin) | Was |
|---|---|
| ca. 17:50 | GitHub Actions: Screener DE → `signals/latest_de.json` |
| ca. 18:30 | Claude: liest die Datei, prüft News, schickt Push-Nachricht |
| ca. 22:20 | GitHub Actions: Screener US → `signals/latest_us.json` |
| ca. 23:00 | Claude: Einschätzung US, Push-Nachricht |

`data/protocol.csv` führt jedes Signal als Papier-Trade (Einstieg zur Eröffnung
des Folgetags, Stop/Ziel/Zeitstop nach Regelwerk, 1 % Kostenpauschale).
`signals/stats.json` enthält die Kennzahlen je Strategie.

## Einrichtung (einmalig, ca. 10 Minuten)

1. Auf github.com ein Konto anlegen (neutraler Name genügt).
2. **New repository** → Name z. B. `screener` → **Public** → *Create repository*.
3. Auf der leeren Repo-Seite **uploading an existing file** klicken und den
   **Inhalt** des entpackten Ordners hineinziehen (alle Dateien und Ordner,
   inkl. `.github`). Unten **Commit changes**.
   - Falls der Ordner `.github` beim Hochladen fehlt (versteckter Ordner):
     **Add file → Create new file**, als Namen
     `.github/workflows/screener.yml` eingeben und den Inhalt der Datei einfügen.
4. Reiter **Actions** öffnen und Workflows aktivieren, falls GitHub danach fragt.
5. Testlauf: **Actions → Screener → Run workflow**, Region `de`, Haken bei
   „Zeitprüfung überspringen“ → *Run workflow*. Nach 5–10 Minuten liegt
   `signals/latest_de.json` im Repo.
6. Den Link zum Repository an Claude schicken – Claude richtet dann die beiden
   abendlichen Einschätzungen ein.

## Lokaler Test ohne Internet

```
python -m tests.test_offline
```

## Hinweise

- Kursdaten kommen kostenlos über yfinance (Yahoo). Das ist inoffiziell und
  fällt gelegentlich aus; dann meldet Claude abends „keine aktuellen Daten“.
- Die Aktienlisten werden wöchentlich von Wikipedia aktualisiert
  (`data/universe.csv`).
- Das Repository enthält keine Zugangsdaten und keinen Bezug zum Depot.
