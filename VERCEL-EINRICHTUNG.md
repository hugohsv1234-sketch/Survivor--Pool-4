# Survivor Pool auf Vercel (kostenloser Hobby-Tarif)

Diese Anleitung behebt den Buildfehler `PYTHON_ENTRYPOINT_NOT_FOUND`.
Die Datei `app.py` exportiert `app` als WSGI-Einstiegspunkt fuer
Vercel. Render benutzt weiterhin `server:application`. Beide
Plattformen haben damit getrennte Startweisen.

## 1. GitHub-Build aktualisieren

GitHub mit dem Vercel-Projekt verbinden (Repository
`hugohsv1234-sketch/Survivor--Pool-4`, Root Directory `./`).
Die Einstellung **Framework Preset** auf **Other** (oder die von Vercel
erkannte Python-Einstellung) setzen. Keine eigene Build Command, kein
Output Directory und kein Install Command eintragen. Vercel kann
`app.py` automatisch als WSGI-Anwendung erkennen.

Nach dem Merge in GitHub unter Vercel > Project > Deployments das
fehlgeschlagene Deployment mit **Redeploy** erneut starten. Falls das
alte Deployment weiterhin die vorherige Git-Version verwendet, im
Projekt die aktuelle `main`-Version deployen (neuen Push oder
`Redeploy` eines Deployments vom aktuellen Commit).

## 2. Daten SICHER einrichten

Die produktiven Daten (Accounts, Nutzer, Tipps, Spiele) liegen in
**Neon Postgres**, nicht im GitHub-Code. Die Konfiguration darf
keine neue, leere Datenbank verwenden.

Bevor Vercel produktiv auf dieselbe Neon-Datenbank zugreifen soll:
- Bestehende Neon-Datenbank als Branch/Kopie sichern und zusaetzlich
  einen echten SQL-Export aufbewahren.
- Render und die Neon-Datenbank NICHT loeschen.
- In Vercel > Project > Settings > Environment Variables anlegen
  (die Werte niemals in GitHub-Commits oder Chats einfuegen):
  - `DATABASE_URL`: dieselbe Neon/Postgres-Verbindungsadresse wie bei
    Render. Fuer erste echte Schreibtests zuvor einen **separaten
    Neon-Testbranch** verwenden.
  - `POOL_PASSWORD`: genau dasselbe Pool-Passwort wie bei Render,
    **oder** `POOL_PASSWORD_HASH`: derselbe bereits vorhandene
    Passwort-Hash (nicht beide erforderlich).
  - `POOL_ENV`: `production`.
  - `POOL_ORIGIN` (empfohlen): spaeter die tatsaechliche oeffentliche
    Vercel-Adresse, z. B. `https://survivor-pool.example.vercel.app`.
    Vercel stellt `VERCEL_URL` bzw.
    `VERCEL_PROJECT_PRODUCTION_URL` bereit; `app.py` akzeptiert
    diese sicheren HTTPS-Adressen auch automatisch.
- Bei Environment Variables zunaechst **Production** waehlen.
  Fuer Preview-Deployments keine Produktions-Datenbank-Zugangsdaten
  freigeben. Eine Preview nur mit Neon-Testbranch pruefen.
- Nach Aenderung von Environment Variables erneut deployen.
  Bereits erzeugte Deployments bekommen neue Werte nicht rueckwirkend.

Die Anwendung laeuft auf Vercel **immer im Produktivmodus** und
startet niemals mit Demo-Accounts oder fluechtiger SQLite-Datenbank.
Sind Datenbank, Pool-Passwort oder sichere Domain nicht vorhanden,
antwortet sie mit **503** und einer Konfigurationsmeldung. Dieses
Verhalten ist Absicht und schuetzt bestehende Nutzerdaten.

## 3. Testen

Nach erfolgreichem Deployment erst die Vercel-URL oeffnen:
1. Oben muss das Dashboard bzw. die Pool-Passwort-Abfrage erscheinen.
2. `https://<deine-domain>/api/session` muss eine JSON-Antwort
   liefern (ein 503 bei fehlenden Einstellungen zeigt die Ursache).
3. Anmeldung mit vorhandenem Testnutzer pruefen.
4. Konten, bisherige Picks, Wochen und Rangliste vergleichen.
5. Nur auf einer Neon-Testkopie einen Test-Pick speichern und
   erneut laden; spaeter erst mit Produktionsdaten verwenden.
6. Render als Rueckfalloption weiterlaufen lassen.

## 4. Wichtige Grenze der kostenlosen Serverless-Version

Bei Render ruft `server.py` den NFL-Feed im Hintergrund alle 120
Sekunden ab. **Vercel Functions haben keine dauerhafte Hintergrund-
Schleife.** Das neue `app.py` startet absichtlich keinen
unzuverlaessigen Hintergrundthread. Die bisherige Neon-Datenbank und
ihre Spiele bleiben unveraendert, aber ohne **separat einzurichtenden
Aktualisierungsjob** werden neue NFL-Ergebnisse NICHT automatisch
durch Vercel aktualisiert.

Vor dem endgueltigen Wechsel muss daher ein geplanter
Aktualisierungsjob, etwa in GitHub Actions mit einem separat
hinterlegten Neon-Secret, eingerichtet und getestet werden.
Auf Vercel Hobby kann ein Vercel Cron Job nur einmal taeglich
laufen; das ist fuer Live-NFL-Daten nicht genug. Der alte
Render-Worker kann voruebergehend weiter aktualisieren, solange
Render tatsaechlich aktiv ist.

Auch die Gratis-Tarife von Vercel und Neon haben Nutzungsgrenzen.
`app.py` aendert keine NFL-Regeln, keine Tabellenstruktur und keine
bestehenden API-Endpunkte.
