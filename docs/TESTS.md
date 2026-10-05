# Testbericht

Stand: 3. Oktober 2026. Die ausgelieferte Version wurde mit Python 3.12 und
Node.js 24 auf Linux geprüft. Alle Testdaten entstehen in isolierten temporären
Datenbanken; vorhandene Benutzer-Datenbanken werden nicht verändert.

## Automatisierte Prüfung

**38 Backend-Tests bestanden**, mit der Python-Standardbibliothek `unittest`.

Abgedeckt sind:

- Pool-Passwort vor Account-Zugang; geschützte Daten bleiben vor Login gesperrt.
- Falsche Passwörter, Registrierung, Bestätigung und Mindestlänge.
- Eindeutige Benutzernamen, Groß-/Kleinschreibung, Passwort-Hashing.
- Session-Rotation, Wiederverwendung einer gültigen Session, Logout.
- CSRF, fremder Origin, Rollenmanipulation und unberechtigte Admin-Aktionen.
- Ein Tipp pro Spieltag, Ersetzen vor Kickoff und sechs parallele Tipp-Anfragen.
- Exakte Kickoff-Grenze, tatsächlicher Frühstart, gesperrter Wechsel auf spätere Spiele.
- Dauerhafter Lock nach einer nachträglichen Spielplanänderung.
- Verschobene Spiele und unzulässige Spiel-/Team-/Week-Kombinationen.
- Wiederverwendung eines Teams auch im Super Bowl.
- Dritter Tipp gegen einen Gegner erlaubt, vierter blockiert.
- Das dreimal gegnerische Team selbst bleibt wählbar.
- Beim Tippwechsel werden Teamverbrauch und Gegner-Zähler korrekt freigegeben.
- Endergebnisse, Zwischenstände, 0-Punkte-Ergebnisse, Sieg und Niederlage.
- Tie als falsch oder neutral; Erfolgsquote ohne Division durch null.
- Strenger Survivor-Modus, verpasste Week, Öffnen der nächsten Demo-Week.
- Verbergen fremder ungesperrter Tipps.
- Keine Passwort-Hashes in API-Antworten; Backend/Datenbank nicht statisch abrufbar.
- Fehlerhafte JSON-Bodies, zu große Requests und Rate-Limits.
- Leere Produktionsdatenbank, Secure-Cookie und Verbot von Demo-Datenbanken im Produktivmodus.
- Atomare Feed-Validierung, Zeitzonen-Normalisierung und letzte Daten bei Feed-Ausfall.
- Öffentliche PWA-Dateien und ausdrücklicher Ausschluss der API aus dem Service-Worker-Cache.

**14 zusätzliche Frontend-Prüfungen bestanden**, mit Node.js und einem kleinen
DOM-Adapter ohne externe Pakete.

Abgedeckt sind die fünf Ansichten, Formularfelder, Tippbestätigung/Abbruch,
Regelerklärungen, gesperrte und zukünftige Auswahlen, Offline-Sperren, HTML-Escaping,
leere Datenzustände, mobile erreichbare Logout-Aktion und optionale WebMCP-Werkzeuge
in einem simulierten Kontext. Dabei wird ein frischer Zustand des echten Backends
verwendet. Der ausgelieferte App-Code wird nur im Speicher des Tests instrumentiert.

JavaScript-Syntax und Python-Kompilierung wurden zusätzlich geprüft.

## Verbleibende Browser- und Geräteprüfung

Die verwaltete Browser-Vorschau stand während der Erstellung nicht zur Verfügung.
**Daher wurden Layout, echte Browser-Klickabläufe, PWA-Installation und Verhalten
auf realen iOS-/Android-Geräten hier nicht visuell oder geräteseitig bestätigt.**
Die DOM-Adapter-Prüfungen ersetzen keine Browser-End-to-End-Tests und kein
Accessibility-Audit. Eine echte WebMCP-Browserintegration ist ebenfalls ungeprüft.

Zum lokalen Gegenprüfen:

1. Starten und falsches Pool-Passwort eingeben; danach korrekt öffnen.
2. Als Max einloggen, Tipp auswählen, abbrechen, bestätigen und ändern.
3. Neu laden: Account und Tipp bleiben erhalten.
4. Demo-Kickoff starten: gesperrter Tipp darf nicht auf späteres Spiel wechseln.
5. Spiel beenden; Dashboard, Saison und Bestenliste vergleichen.
6. Unter Profil verwendete Teams und Gegen-Tipp-Zähler kontrollieren.
7. Abmelden und mit einem neuen Account registrieren; doppelte Namen abweisen.
8. Fenster auf 375, 768 und 1440 Pixel Breite einstellen. Navigation und Tabelle
   prüfen; nur die Saison-Tabelle soll horizontal scrollen.
9. Auf 200 % zoomen, mit Tab/Enter bedienen und Dialoge mit Escape schließen.
10. „App installieren“ auf localhost/HTTPS prüfen; in Safari den Teilen-Dialog nutzen.
11. Nach dem ersten Laden den Server beenden: Offline-Hinweis, keine neuen Tipps.
12. Server neu starten und erneut laden: gespeicherte Daten wieder verfügbar.

## Testbefehle

```bash
python3 -m unittest discover -s tests -v
python3 tests/export_snapshot.py
node tests/test_frontend.cjs
```

Der zweite Befehl erstellt `tests/snapshot.json` ausschließlich für den Frontend-Test.
Diese Datei ist nicht Teil der Auslieferung und kann jederzeit neu erzeugt werden.
