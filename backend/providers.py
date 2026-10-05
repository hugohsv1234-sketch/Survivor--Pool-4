"""Small, replaceable NFL data boundary. Only normalized, validated data enter SQLite.

The JSON feed is operator-configured, never supplied by a browser. A provider
adapter may normalize any licensed feed to this format; no vendor is required.
"""
import json
import math
import re
import time
import urllib.request
from datetime import datetime
from .rules import RuleError


def utc_timestamp(value):
    if isinstance(value, bool):
        raise ValueError("Ungültige Zeit")
    if isinstance(value, (int, float)) and math.isfinite(value):
        result = float(value)
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Kickoff benötigt eine explizite Zeitzone")
        result = dt.timestamp()
    if not 946684800 <= result < 4133980800:
        raise ValueError("Spielzeit muss zwischen 2000 und 2100 liegen")
    return result


def apply_snapshot(store, payload):
    if not isinstance(payload, dict) or set(payload) != {"season", "current_week", "games"}:
        raise ValueError("Feed muss season, current_week und games enthalten")
    season, week, games = payload["season"], payload["current_week"], payload["games"]
    if type(season) is not int or not 2020 <= season <= 2100 or type(week) is not int or not 1 <= week <= 22:
        raise ValueError("Ungültige Saison/Week")
    if not isinstance(games, list) or not 1 <= len(games) <= 500:
        raise ValueError("Ungültige Spieleliste")
    with store.transaction() as db:
        known = {row[0] for row in db.execute("SELECT id FROM teams")}
        # Lock according to the previous known schedule BEFORE any rescheduling.
        store.lock_due(db, time.time())
        seen, participants = set(), set()
        for g in games:
            if not isinstance(g, dict) or set(g) - {"id", "week", "away", "home", "kickoff", "status", "away_score", "home_score", "started_at"}:
                raise ValueError("Unbekannte Spielfelder")
            gid, gw = g.get("id"), g.get("week")
            if not isinstance(gid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", gid) or gid in seen:
                raise ValueError("Ungültige oder doppelte Spiel-ID")
            if type(gw) is not int or not 1 <= gw <= 22:
                raise ValueError("Ungültige Spiel-Week")
            away, home = g.get("away"), g.get("home")
            if away not in known or home not in known or away == home:
                raise ValueError("Unbekannte Teams")
            if (gw, away) in participants or (gw, home) in participants:
                raise ValueError("Ein Team darf nicht zweimal in derselben Week spielen")
            seen.add(gid)
            participants.update(((gw, away), (gw, home)))
            status = g.get("status")
            if status not in ("scheduled", "live", "final", "postponed", "cancelled"):
                raise ValueError("Ungültiger Spielstatus")
            scores = [g.get("away_score"), g.get("home_score")]
            if any(v is not None and (type(v) is not int or not 0 <= v <= 150) for v in scores):
                raise ValueError("Ungültiger Spielstand")
            if status == "final" and None in scores:
                raise ValueError("Ein Endergebnis benötigt beide Spielstände")
            kickoff = utc_timestamp(g.get("kickoff"))
            started_at = utc_timestamp(g["started_at"]) if g.get("started_at") is not None else None
            old = db.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
            if old and (old["season"], old["week"], old["away"], old["home"]) != (season, gw, away, home):
                raise ValueError("Die Identität eines vorhandenen Spiels darf nicht verändert werden")
            if old and old["started_at"] is not None:
                started_at = old["started_at"]
            db.execute("""INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                kickoff=excluded.kickoff,status=excluded.status,away_score=excluded.away_score,
                home_score=excluded.home_score,started_at=excluded.started_at""",
                       (gid, season, gw, away, home, kickoff, status, *scores, started_at))
        store.set(db, "season", season)
        store.set(db, "current_week", week)
        store.set(db, "last_sync", time.time())
        store.set(db, "provider_error", None)
        store.lock_due(db, time.time())


def refresh(store, url, bearer=None):
    """An all-or-nothing refresh. Keep the previous good snapshot on any failure."""
    try:
        if not url.startswith("https://"):
            raise ValueError("Der Feed benötigt HTTPS")
        headers = {"Accept": "application/json", "User-Agent": "SurvivorPool/1.0"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        request = urllib.request.Request(url, headers=headers)
        # Do not redirect authorization headers to another origin.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=8) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("Feed zu groß")
        apply_snapshot(store, json.loads(raw))
        return True
    except Exception:
        with store.transaction() as db:
            store.set(db, "provider_error", "NFL-Daten sind vorübergehend nicht erreichbar. Die zuletzt geladenen Daten bleiben sichtbar.")
        return False
