# Datenfeed und API

## NFL-Feed vorbereiten

`backend/providers.py` bildet die Grenze zur Datenquelle. Die lokale Demo braucht
keinen Netzwerkzugriff und keinen API-Key. Ein später ausgewählter Anbieter wird
über einen kleinen Normalisierungsadapter angebunden. Es wird kein echter
NFL-Live-Datenvertrag oder frei nutzbarer offizieller API-Zugang vorausgesetzt.

Erforderliches JSON-Format:

```json
{
  "season": 2026,
  "current_week": 5,
  "games": [
    {
      "id": "2026-w5-bal-cin",
      "week": 5,
      "away": "BAL",
      "home": "CIN",
      "kickoff": "2026-10-04T17:00:00Z",
      "status": "scheduled",
      "away_score": null,
      "home_score": null,
      "started_at": null
    }
  ]
}
```

Das Beispiel ist eine **Schema-Demonstration**, kein verifizierter Spielplan.

| Feld | Bedeutung |
|---|---|
| `season` | Saisonjahr, 2020–2100 |
| `current_week` | 1–18 Regular Season, 19 Wild Card, 20 Divisional, 21 Conference, 22 Super Bowl |
| `id` | Stabile ID, 1–80 ASCII-Buchstaben, Zahlen, Bindestrich oder Unterstrich |
| `week` | 1–22 |
| `away`, `home` | Vorhandene eindeutige Team-IDs wie BAL, CIN, KC, NE, SF |
| `kickoff` | UTC-Unix-Sekunden oder ISO 8601 mit expliziter Zeitzone |
| `status` | `scheduled`, `live`, `final`, `postponed`, `cancelled` |
| `away_score`, `home_score` | null oder ganze Zahl 0–150; bei `final` beide erforderlich |
| `started_at` | Optionaler tatsächlich bestätigter Startzeitpunkt |

Die Teamliste mit 32 Einträgen befindet sich in `backend/demo.py` und wird auch
für eine leere Produktionsdatenbank verwendet. Der Name des Moduls bedeutet bei
Teams keine simulierten Teamnamen; nur die Fixtures und Ergebnisse sind fiktiv.
Die Feed-Normalisierung muss ihre Team-IDs auf diese Kürzel abbilden.

Ein Batch ist atomar: bei einem ungültigen Spiel wird keine seiner Änderungen
übernommen. Vorhandene IDs dürfen nicht plötzlich andere Teams, eine andere
Week oder eine andere Saison bezeichnen. Ergebnisse und Kickoff-Zeit können
aktualisiert werden. Nicht enthaltene Spiele bleiben erhalten; es handelt sich
um einen Upsert-Batch, kein destruktives Ersetzen des gesamten Spielplans.

Einspielen einer lokalen Datei in eine Produktionsdatenbank:

```bash
python3 manage.py import-feed mein-feed.json --db /persistent-data/pool.sqlite3
```

Automatisches Laden: Im Produktionsprozess `NFL_FEED_URL` auf eine vom Betreiber
kontrollierte HTTPS-Adresse setzen. Optional `NFL_FEED_TOKEN` für Bearer-Auth.
Der Prozess lädt alle 60 Sekunden; Browser aktualisieren alle 20 Sekunden und
beim erneuten Aktivieren des Tabs. Redirects werden nicht verfolgt, damit ein
Bearer-Token nicht an einen anderen Host gelangen kann. Timeout: 8 Sekunden,
maximale Antwort: 2 MB. Bei einem Fehler bleibt die letzte valide Datenbasis
erhalten. Ein erfolgreicher Import entfernt den Fehlerhinweis.

## Frontend-API

Alle API-Antworten haben `Cache-Control: no-store`. Fehler verwenden eine passende
HTTP-Statusnummer und `{ "error": "Verständlicher Text", "code": "optional" }`.
Die Browseradresse muss auf `POOL_ORIGIN` passen. Alle POSTs senden JSON und
den erlaubten `Origin`. Nach dem Pool-Zugang ist `X-CSRF-Token` erforderlich.
Die Benutzeridentität wird ausschließlich aus dem HttpOnly-Cookie abgeleitet.

| Methode / Pfad | Felder / Zweck |
|---|---|
| GET `/api/session` | Anmeldestatus und bei vorhandener Sitzung CSRF-Token; keine Pool-Daten |
| POST `/api/gate` | `password`: gemeinsames Pool-Passwort; erstellt kurzlebige Zugangssitzung |
| POST `/api/register` | `username`, `display_name`, `password`, `confirmation`; eindeutiger persönlicher Account |
| POST `/api/login` | `username`, `password`; rotiert Session |
| POST `/api/logout` | Leeres Objekt; beendet die Session |
| GET `/api/state` | Nur angemeldet: Teams, Spiele, eigene/öffentliche Tipps, Teilnehmer, Regeln und Serverzeit |
| POST `/api/pick` | `game_id`, `team`; validierter Tipp oder Tippwechsel; Antwort enthält aktuellen Zustand |
| POST `/api/settings` | Admin: `tie_is_loss`, `allow_after_elimination`, `missing_pick_eliminates`, jeweils boolesch |
| POST `/api/demo` | Nur Demo-Admin: `action` = `kickoff`, `finish` oder `next_week`; für Spiele `game_id`, für Ergebnis `winner` = `away`, `home`, `tie` |

`/api/pick` akzeptiert ausdrücklich keine Client-Felder für Benutzer-ID, Saison,
Week, Rolle, Uhrzeit, Ergebnis oder angeblichen Sperrstatus. Zusätzliche Felder
werden abgewiesen. Die aktuelle Saison und Week stammen aus Server-Konfiguration
bzw. dem Feed.

Das Frontend fragt regelmäßig nach dem gespeicherten Zustand. Server-seitige
Regelprüfung und Auswertung funktionieren auch ohne offenen Browser.
