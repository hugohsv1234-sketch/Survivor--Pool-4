"""Generate an isolated demo fixture for the dependency-free frontend checks."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app import App

destination = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests/snapshot.json"
with tempfile.TemporaryDirectory() as td:
    app = App(Path(td) / "test.sqlite3", ROOT / "public")
    with app.store.transaction() as db:
        me = dict(db.execute("SELECT id,username,display_name,role,joined_week FROM users WHERE id=1").fetchone())
        snapshot = app.snapshot(db, me, app.store.settings(db), time.time())
    destination.write_text(json.dumps(snapshot), encoding="utf-8")
print("Frontend-Testdaten erzeugt.")
