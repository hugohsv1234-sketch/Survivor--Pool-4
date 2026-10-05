# Architektur und Betrieb

## Überblick

| Bereich | Umsetzung |
|---|---|
| Oberfläche | `public/index.html`, `public/js/app.js`, `public/css/app.css`; HTML, CSS und JavaScript ohne Build-Schritt |
| API | `backend/app.py`: WSGI, JSON, Sessions und Autorisierung |
| Survivor-Regeln | `backend/rules.py`: reine, testbare Funktionen ohne HTTP-Abhängigkeit |
| Datenbank | `backend/store.py`: SQLite, Fremdschlüssel, WAL, parametrisierte SQL-Abfragen |
| Accounts | `backend/security.py`: scrypt mit individuellem Zufallssalt |
| Demo | `backend/demo.py`: fiktive Spielpläne und sechs Accounts |
| NFL-Feed | `backend/providers.py`: normalisierte JSON-Schnittstelle, Validierung, atomare Aktualisierung |
| PWA | `public/manifest.json`, `public/service-worker.js`, `public/icons/` |
| Administration | `manage.py`: Hash erzeugen, Administrator bestimmen, Feed-Datei importieren |
| Tests | `tests/test_rules.py`, `tests/test_api.py`, `tests/test_frontend.cjs` |

Das Frontend kann separat weiterentwickelt werden, ruft die API aber im selben
Origin auf. HTTP-Routing und Regeln sind getrennt. Die Datenbank bleibt außerhalb
des öffentlichen Ordners. Die App lässt sich ohne Frontend-Build auf einem
Python-fähigen Server hosten. Reines Static Hosting reicht für den sicheren
Mehrbenutzerbetrieb nicht aus.

## Verbindliche Prüfungen

Ein Schreibvorgang läuft vollständig in einer `BEGIN IMMEDIATE`-Transaktion:
Session und Benutzer prüfen, fällige Tipps sperren, aktuellen Spieltag und
Spielidentität prüfen, alten Tipp auf Sperre prüfen, neuen Kickoff prüfen,
Team-/Gegner-Limits prüfen, anschließend den Tipp einfügen oder ersetzen.
`UNIQUE(user_id, season, week)` schützt zusätzlich vor doppelten Tipps.

Die Datenbank serialisiert konkurrierende Schreibvorgänge. Eine erneute identische
Anfrage vor Kickoff erzeugt keine zweite Zeile. Nach Kickoff wird auch ein Retry
abgewiesen; ein nachgeladenes Dashboard zeigt den tatsächlich gespeicherten Tipp.
Auswertungen werden aus gespeicherten Spielen berechnet und bei jeder API-Abfrage
aktualisiert. Korrigierte Ergebnisse bleiben dadurch konsistent.

## Accounts und Sessions

- Passwörter: scrypt, `N=32768`, `r=8`, `p=3`, zufälliger 16-Byte-Salt;
  konstante Vergleichsfunktion für Hashes. Diese Parameter entsprechen einer
  von OWASP beschriebenen scrypt-Konfiguration.
- Persönliche Passwörter sind 10–128 Zeichen lang. Das Demo-Passwort und das
  vorgegebene gemeinsame Pool-Passwort sind ausschließlich Demo-Zugangsdaten.
- Undurchsichtige zufällige Session-Tokens mit 256 Bit Entropie; in SQLite liegt
  nur der SHA-256-Token-Hash. Das ist ein Token-Hash, kein Passwort-Hash.
- Cookies: HttpOnly, SameSite=Strict, Pfad `/`, maximal 30 Tage; Secure im
  Produktionsmodus. Pool-Zugang ohne Account läuft nach 30 Minuten ab.
- Session-Rotation beim Login und bei Registrierung; vollständiger Widerruf
  beim Logout. Benutzername ist eindeutig und wird kleingeschrieben.
- POST-Anfragen benötigen erlaubten Origin, JSON-Content-Type und (nach dem
  Pool-Zugang) CSRF-Token. Browserfelder wie Benutzer-ID, Uhrzeit oder Rolle
  werden nicht als Autorität akzeptiert und als unbekannte Felder verworfen.
- Pro IP und Auth-Endpunkt höchstens 30 Versuche pro 15 Minuten. Die Fehlversuche
  werden unabhängig von zurückgerollten Login-Transaktionen gespeichert.
- Content Security Policy, Frame-Schutz, MIME-Schutz und im Produktivmodus HSTS.
- Für Rechte zählt nur die serverseitige Account-Rolle. Demo-Steuerung benötigt
  zusätzlich den aktiven Demo-Modus. Sie ist im Produktivmodus nicht nutzbar.

## Online-Betrieb vorbereiten

Die Auslieferung ist eine lokal testbare erste Version, keine bereits betriebene
Online-Installation. Für Hosting werden Python, ein dauerhafter Datenträger und
ein HTTPS-Reverse-Proxy benötigt. Die mitgelieferte Entwicklungs-HTTP-Schleife
ist nicht der Produktions-Webserver.

1. Produktions-Datenbankpfad auf einem persistenten Datenträger festlegen.
2. Ein neues Pool-Passwort verwenden und den Hash verdeckt erzeugen:

   ```bash
   python3 manage.py hash-password
   ```

3. In der Hosting-Konfiguration `POOL_ENV=production`, `POOL_ORIGIN` auf die
   exakte HTTPS-Adresse und `POOL_PASSWORD_HASH` auf den erzeugten Hash setzen.
   Den Hash als **wörtlichen Secret-Wert** eintragen; er enthält Dollarzeichen.
   Nicht in JavaScript, im Repository oder in einer öffentlich ausgelieferten
   Datei speichern. Alternativ kann das Passwort serverseitig als
   `POOL_PASSWORD` bereitgestellt werden.
4. `POOL_DB` auf eine **eigene Produktionsdatenbank** setzen. Der Produktionsmodus
   verweigert den Start mit einer vorhandenen Demo-Datenbank. Er erstellt keine
   Testkonten und keine fiktiven Begegnungen.
5. Die `.env.example` dient als Referenz. Sie wird nicht automatisch eingelesen;
   Variablen müssen vom Prozess/Hosting-System tatsächlich gesetzt werden.
6. Beispielsweise Gunicorn unter Linux verwenden:

   ```bash
   python3 -m pip install gunicorn
   gunicorn --workers 1 --threads 4 --bind 127.0.0.1:8000 server:application
   ```

7. HTTPS-Reverse-Proxy aufsetzen, der `/` und `/api/` an dieselbe Anwendung
   weiterleitet und den richtigen Host-Header erhält. HTTPS ist für Secure-Cookies
   und PWA nötig. Datenbank und Backend-Verzeichnis niemals statisch ausliefern.
8. Mit dem Pool-Passwort öffnen, den eigenen Account registrieren, anschließend
   diesen Account mit dem lokalen Administrationsbefehl berechtigen:

   ```bash
   python3 manage.py make-admin meinname --db /persistent-data/pool.sqlite3
   ```

9. Einen lizenzierten NFL-Feed normalisieren, importieren bzw. `NFL_FEED_URL`
   konfigurieren; siehe [API.md](API.md). Erst damit stehen reale Spiele zur Auswahl.
10. Datenbank regelmäßig sichern, TLS-Erneuerung und Feed-Verfügbarkeit überwachen.

Der Prozess erwartet die in `POOL_ORIGIN` genannten Adressen exakt. Mehrere
Adressen werden mit Kommas ohne Leerzeichen getrennt. Ungeprüfte Forwarded-Header
werden nicht für Autorisierung oder sichere Cookies verwendet. Hinter einem Proxy
kann das IP-Limit auf dessen Adresse wirken; eine spätere Skalierung sollte einen
vom Betreiber vertrauenswürdig konfigurierten gemeinsamen Rate-Limiter ergänzen.

## Zeit und Datenfrische

Kickoffs werden als UTC-Unix-Sekunden gespeichert. Die Anzeige verwendet
`Intl.DateTimeFormat` in der Browser-Zeitzone. Der Countdown basiert auf der
Serverzeit plus monoton vergangener Zeit. Ein Manipulieren der Browseruhr
verändert keine Backend-Entscheidung.

Ein Feed kann `started_at` setzen oder den Status auf `live`/`final` wechseln,
auch vor dem geplanten Kickoff. Beides sperrt Tipps. Eine rechtzeitig gemeldete
Verschiebung aktualisiert den geplanten Zeitpunkt. `postponed` ohne tatsächlichen
Start sperrt neue Tipps auf dieses Spiel; ein noch ungesperrter alter Tipp darf
zu einem anderen Spiel wechseln. Ein einmal gespeicherter Lock bleibt auch bei
späteren Feed-Korrekturen bestehen.

Ohne tatsächliche Live-Meldung ist der zuletzt bestätigte geplante Kickoff die
konservative Sperrgrenze. Keine App kann einen nicht gelieferten abweichenden
tatsächlichen Spielstart kennen. Bei Feed-Fehlern bleiben letzte Daten erhalten
und werden mit einem Hinweis gezeigt. Abgesagte oder verschobene Spiele werden
nicht automatisch als Sieg/Niederlage bewertet. Eine besondere Wertung dafür
müsste der Betreiber als zusätzliche Regel definieren.

## PWA und Oberfläche

Der Service Worker cached ausschließlich die öffentliche App-Hülle. APIs bleiben
Network-only; es gibt keine Offline-Schreibwarteschlange. Das schützt vor
veralteten Tippänderungen nach Kickoff und verhindert private Daten im Offline-Cache.
Für Shell-Änderungen bei einer späteren Veröffentlichung die Cache-Version erhöhen.

Mobile Bottom-Navigation, responsives Grid, horizontale Saison-Tabelle,
Tastaturfokus, native modale Dialoge, Formularlabels und reduzierte Animationen
bei `prefers-reduced-motion` sind implementiert. Das Installationsangebot ist
browserabhängig; Safari erhält eine Anleitung für „Zum Home-Bildschirm“.

Zwei optionale, feature-detected WebMCP-Werkzeuge lesen den eigenen Status oder
öffnen einen Tipp-Bestätigungsdialog. Sie speichern keinen Tipp ohne den
sichtbaren Bestätigungsschritt. Der Mock-Kontext ist getestet; eine Prüfung in
einem echten WebMCP-fähigen Browser steht noch aus.

## Referenzen

- OWASP Password Storage Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- MDN, Making PWAs installable:
  https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable
- MDN, Trigger installation from your PWA:
  https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/How_to/Trigger_install_prompt

Diese Dokumentation beschreibt implementierte Schutzmaßnahmen. Ein produktiver
Betrieb mit echten Benutzern benötigt zusätzlich die übliche Prüfung der
Hosting-Konfiguration; ein unabhängiges Sicherheitsaudit wurde nicht durchgeführt.
