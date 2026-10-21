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


## 5. Kostenlosen NFL-Ergebnisabgleich mit GitHub Actions aktivieren

Der aktualisierte Code enthaelt `.github/workflows/nfl-refresh.yml` und
`scripts/refresh_nfl.py`. Der Job nutzt exakt die vorhandene ESPN-
Synchronisierung und optional die bereits vorhandene DraftKings-
Wettanteil-Anzeige. Es ist **kein** neuer NFL-Provider eingebaut.

Die GitHub-Action ist aus Sicherheitsgruenden **standardmaessig aus**:
Weder `push` noch `pull_request` loesen DB-Schreibzugriffe aus. Ohne
die ausdrueckliche Aktivierungsvariable wird auch der Zeitplan uebersprungen.

### Erst auf einer Test-Datenbank testen

1. Neon > Branches > `vercel-test` > Connect oeffnen und
   **Connection pooling** eingeschaltet lassen.
2. Die Postgres-Verbindungsadresse kopieren, aber NIE im GitHub-Code
   oder Chat veroeffentlichen. Der geheime String gehoert nur in
   **GitHub > Repository > Settings > Secrets and variables >
   Actions > Secrets > New repository secret**.
3. Als Secret-Name genau **`NFL_REFRESH_DATABASE_URL`** verwenden;
   als Wert die Verbindung zum **Neon-Branch `vercel-test`**.
   Der Secret-Wert darf nicht `production` sein, solange wir testen.
4. GitHub > **Actions > NFL Ergebnisse aktualisieren > Run workflow**
   auf Branch `main`. Den Lauf oeffnen und kontrollieren:
   gruene Steps, "Bestehender NFL-Pool" und "erfolgreich aktualisiert".
   Falls der Lauf fehlschlaegt, die Fehlermeldung ohne Secrets zeigen.
5. Neon-Testbranch und die Vercel-Testwebsite vergleichen, damit
   das Live-Ergebnis-Update und die bereits vorhandenen Tipps stimmen.

### Danach Zeitplan einschalten (weiterhin Test-Datenbank)

6. GitHub > Repository > **Settings > Secrets and variables >
   Actions > Variables > New repository variable**.
7. Name genau **`NFL_REFRESH_ENABLED`**; Wert **`true`**.
   Damit kann der Job automatisch **etwa alle 10 Minuten** laufen
   (GitHub-Cron startet gelegentlich verzoegert oder faellt aus).
8. Pruefen, dass die naechsten automatischen Laeufe gruen bleiben.

### Erst nach Daten-Backup: Produktivwechsel

9. Neon-`production` erst als separaten Branch sichern und zusaetzlich
   mit `pg_dump` ausserhalb Neons sichern. Render nicht loeschen.
10. **Zuerst** die GitHub-Variable `NFL_REFRESH_ENABLED` auf `false`
    setzen und laufende Sync-Jobs auslaufen lassen.
11. Die Vercel-`DATABASE_URL` von `vercel-test` auf die bestehende
    Neon-`production`-Adresse umstellen (nur Production-Umgebung).
    Auf Vercel danach eine neue Production-Deployment-Version starten.
    Gewachsene Benutzerdaten NICHT neu importieren.
12. Sobald die Produktionswebsite getestet ist, das GitHub-Secret
    `NFL_REFRESH_DATABASE_URL` ebenfalls auf die **gleiche**
    bestehende Neon-`production`-Adresse aendern.
13. GitHub-Action erst manuell pruefen, danach
    `NFL_REFRESH_ENABLED=true` setzen und die Zeitlaeufe beobachten.

**Wichtig:** GitHub Actions auf Standard-Ubuntu-Runnern ist fuer dieses
oeffentliche GitHub-Repo kostenlos. Geplante Jobs sind keine
Garantie fuer Echtzeit-Live-Ergebnisse; der Zeitplan kann sich verzoegern,
und GitHub deaktiviert geplante Workflows bei oeffentlichen Repos nach
60 Tagen ohne Repository-Aktivitaet. Auch Neon bleibt an das eigene
Free-Tier-Limit gebunden. Der Job speichert keine Anmeldeinformationen
in Dateien/Artefakten und nutzt den vorhandenen Postgres-Datensatz.
