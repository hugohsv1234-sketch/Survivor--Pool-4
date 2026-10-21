"""Refresh NFL results and public betting-ticket splits from a GitHub Actions runner.

This is deliberately independent of the Vercel HTTP functions. It uses the
existing normalization/scoring functions and connects only to a PRE-EXISTING
Neon Postgres Survivor Pool. The current database's user accounts and picks
are not re-created or imported.

Run manually: DATABASE_URL=<NEON_SECRET> python3 -m scripts.refresh_nfl
Never store the DATABASE_URL in the repository, a log, or a chat.
"""
import os
import sys
from urllib.parse import urlsplit

from backend.betting_splits import refresh_ticket_percentages
from backend.providers import refresh, refresh_espn
from backend.store import PostgresConnection, Store


def required_neon_url():
    """Fail closed: the refresh job cannot silently create a local demo DB."""
    url = os.environ.get("DATABASE_URL", "").strip()
    parts = urlsplit(url)
    if (
        parts.scheme not in ("postgresql", "postgres")
        or not parts.hostname
        or not parts.hostname.lower().endswith(".neon.tech")
        or not parts.username
        or not parts.path.strip("/")
    ):
        raise RuntimeError(
            "DATABASE_URL fehlt oder ist keine gueltige Neon-Postgres-Adresse. "
            "Bitte unter GitHub Actions Secrets als NFL_REFRESH_DATABASE_URL hinterlegen."
        )
    return url


def inspect_existing_pool(url):
    """Check existing data using SELECTs *before* allowing any writer to start."""
    with PostgresConnection(url) as db:
        users = db.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
        games = db.execute("SELECT COUNT(*) AS total FROM games").fetchone()["total"]
        picks = db.execute("SELECT COUNT(*) AS total FROM picks").fetchone()["total"]
        settings = Store.settings(db)
    season = settings.get("season")
    if (
        type(season) is not int
        or not 2020 <= season <= 2100
        or not users
        or not games
    ):
        raise RuntimeError(
            "Datenbank enthaelt keinen bestehenden Pool mit Benutzern und "
            "NFL-Spielen. Abbruch ohne Datenimport oder Demo-Initialisierung."
        )
    if settings.get("source") == "demo":
        raise RuntimeError("Demo-Datenbank ist kein gueltiges Synchronisierungsziel.")
    # Only non-sensitive counts; no hostname, user IDs, password or URL in logs.
    print(f"Bestehender NFL-Pool: Saison {season}, {users} Spieler, "
          f"{games} Spiele, {picks} Tipps.", flush=True)
    return season


def update():
    """Return success only when a real ESPN/custom-feed snapshot was applied."""
    url = required_neon_url()
    season = inspect_existing_pool(url)
    # Existing Store and feed logic; PostgreSQL is mandatory by the guard above.
    store = Store("unused-with-NEON.sqlite3", demo_mode=False)
    feed_url = os.environ.get("NFL_FEED_URL", "").strip()
    if feed_url:
        if not feed_url.startswith("https://"):
            raise RuntimeError("NFL_FEED_URL muss HTTPS verwenden.")
        ok = refresh(store, feed_url, os.environ.get("NFL_FEED_TOKEN"))
    else:
        # The Neon pool's actual active season also works during Jan/Feb
        # playoffs (when calendar year differs from the NFL season year).
        ok = refresh_espn(store, season)
    if not ok:
        raise RuntimeError(
            "NFL-Ergebnisse konnten nicht aktualisiert werden. "
            "Vorhandene Spiele/Tipps bleiben erhalten."
        )

    try:
        # This optional adapter itself throttles to at most every 30 minutes.
        refresh_ticket_percentages(store)
    except Exception as exc:
        print(f"Optionale Wettanteile aktuell nicht verfuegbar: {type(exc).__name__}",
              flush=True)
    print("NFL-Spielplan und Ergebnisse erfolgreich aktualisiert.", flush=True)
    return True


if __name__ == "__main__":
    try:
        update()
    except Exception as exc:
        print("NFL-Aktualisierung fehlgeschlagen: " + str(exc), file=sys.stderr)
        sys.exit(1)
