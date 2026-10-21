# Premium UI und Motion

Die fünf bestehenden Ansichten, Login/Registrierung und alle Dialoge behalten
ihre Texte, Aktionen und Daten. Der bestehende 49ers-Fotobanner und die originalen
NFL-Logos bleiben erhalten. Backend, API, Datenbank, Rechte und Survivor-Regeln
sind von dieser Änderung nicht betroffen.

## Verantwortlichkeiten

- `public/css/app.css`: bestehende Layout- und Komponentenbasis.
- `public/css/premium.css`: konsolidierte visuelle Ebene mit Farb-, Typografie-,
  Abstands-, Oberflächen- und Motion-Tokens. Komponenten und Breakpoints stehen
  in zusammenhängenden Abschnitten; neue Anpassungen bitte dort einpflegen.
- `public/js/immersive-motion.js`: optionale Darstellung mit nativer Web Animations
  API und Intersection Observer, ohne zusätzliche Bibliothek. Die vorher in
  `app.js` duplizierten dekorativen Pointer-Handler sind hier zusammengeführt.
- `public/js/app.js`: unveränderte Render-, Routing-, Formular- und Spielaktionen.
- `public/service-worker.js`: neue öffentliche Shell-Version; API-Antworten bleiben
  vom Cache ausgeschlossen.

## Bewegung und Zugriff

Micro-Feedback liegt bei 180 ms, Navigation und Ansichtswechsel bei 260–360 ms,
Reveals bei 440–540 ms und Zahlenwechsel bei höchstens 620 ms. Die langsamen
blauen und roten Hintergrundlichter verwenden Transform und Opacity.

Scroll-Reveals verstecken wartende Elemente nicht. Animationen blockieren keine
Interaktion und verzögern keine Requests oder Dialogbestätigungen. Automatische
Aktualisierungen derselben Ansicht wiederholen keine vollständige Eingangsanimation.
Bestehende Prozentbalken werden per Scale animiert; ihre Werte und Breiten bleiben
unverändert. Zahlenanimationen lesen ausschließlich die vom Renderer ausgegebenen
Werte und stellen bei Abbruch sofort den bestätigten Endwert her.

Pointer-Effekte laufen nur mit feinem Zeigegerät und höchstens einmal pro Frame.
Mobil gibt es natives Touch-Feedback. `prefers-reduced-motion` wird auch bei
Änderungen während der Sitzung respektiert. Bei ausgeblendetem Dokument pausieren
Ambient-Animationen und temporäre Effekte werden beendet. Observer und Frames werden
bei Seitenwechsel/Verlassen bereinigt; eine Rückkehr aus dem Browsercache wird behandelt.
Ohne das optionale Motion-Script bleiben alle Ansichten und Aktionen nutzbar.

## Verifikation

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tests/export_snapshot.py
node tests/test_frontend.cjs
```

Die vorhandene GitHub-Actions-Prüfung startet zusätzlich einen isolierten Demo-Server
und führt `node tests/test_browser.cjs` aus. Das Browser-Script verweigert andere
Hosts als localhost/127.0.0.1, weil es eigene QA-Accounts und Testtipps erstellt.

Chromium prüft Desktop (1440 px), Tablet (820 px), Smartphone (390 px), schmale
Smartphones (320 px), reduzierte Bewegung und ein blockiertes Motion-Script.
Abgedeckt sind alle fünf Ansichten, Registrierung, Nutzerrechte, Dialoge, Abbruch,
einmalige Tippbestätigung, Sperre künftiger Spieltage, Neuladen, Offline-Zustand und
Abmeldung. Statistik-Endwerte werden gegen die echte Test-API geprüft. Screenshots
liegen im Actions-Artefakt `survivor-premium-visual-qa`.

Ein garantiertes 60-FPS-Ergebnis auf jeder Hardware lässt sich aus Browser-Smoke-Tests
nicht ableiten. Die Darstellung vermeidet zusätzliche Dependencies, kontinuierliche
JavaScript-Loops und flächige animierte Blur-Filter.
