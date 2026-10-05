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


ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_TEAM_MAP = {
    "ARI":"ARI","ATL":"ATL","BAL":"BAL","BUF":"BUF","CAR":"CAR","CHI":"CHI","CIN":"CIN","CLE":"CLE",
    "DAL":"DAL","DEN":"DEN","DET":"DET","GB":"GB","HOU":"HOU","IND":"IND","JAX":"JAX","KC":"KC",
    "LV":"LV","LAC":"LAC","LAR":"LAR","MIA":"MIA","MIN":"MIN","NE":"NE","NO":"NO","NYG":"NYG",
    "NYJ":"NYJ","PHI":"PHI","PIT":"PIT","SF":"SF","SEA":"SEA","TB":"TB","TEN":"TEN","WSH":"WAS","WAS":"WAS"
}

def _espn_json(url):
    request = urllib.request.Request(url, headers={"Accept":"application/json","User-Agent":"SurvivorPool/2.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError("ESPN-Antwort zu groß")
        return json.loads(raw)

def _espn_status(status):
    name = str((status or {}).get("type", {}).get("name", "")).lower()
    state = str((status or {}).get("type", {}).get("state", "")).lower()
    if "postpon" in name: return "postponed"
    if "cancel" in name: return "cancelled"
    if state == "post" or "final" in name: return "final"
    if state == "in": return "live"
    return "scheduled"

def _score(value):
    if value in (None, ""): return None
    return int(float(value))

def espn_snapshot(season=None):
    """Normalize ESPN's public NFL scoreboard into the pool's internal feed shape."""
    season = int(season or datetime.now().year)
    games = []
    weeks_with_games = set()
    # Regular season = weeks 1-18. Postseason maps to pool weeks 19-22.
    requests = [(2, w, w) for w in range(1, 19)] + [(3, w, 18 + w) for w in range(1, 5)]
    for season_type, espn_week, pool_week in requests:
        url = f"{ESPN_SCOREBOARD}?dates={season}&seasontype={season_type}&week={espn_week}&limit=100"
        payload = _espn_json(url)
        for event in payload.get("events", []):
            competitions = event.get("competitions") or []
            if not competitions: continue
            comp = competitions[0]
            sides = {}
            for c in comp.get("competitors", []):
                team = c.get("team") or {}
                abbr = ESPN_TEAM_MAP.get(str(team.get("abbreviation", "")).upper())
                side = c.get("homeAway")
                if abbr and side in ("home", "away"):
                    sides[side] = (abbr, _score(c.get("score")))
            if "home" not in sides or "away" not in sides: continue
            status = _espn_status(comp.get("status") or event.get("status"))
            kickoff = event.get("date") or comp.get("date")
            if not kickoff: continue
            games.append({
                "id": "espn_" + str(event.get("id")),
                "week": pool_week,
                "away": sides["away"][0], "home": sides["home"][0],
                "kickoff": kickoff, "status": status,
                "away_score": sides["away"][1] if status in ("live","final") else None,
                "home_score": sides["home"][1] if status in ("live","final") else None,
                "started_at": kickoff if status in ("live","final") else None
            })
            weeks_with_games.add(pool_week)
    if not games:
        raise ValueError("ESPN lieferte keine NFL-Spiele")
    now = time.time()
    future = sorted({g["week"] for g in games if utc_timestamp(g["kickoff"]) > now and g["status"] == "scheduled"})
    active = sorted({g["week"] for g in games if g["status"] == "live"})
    current_week = active[0] if active else (future[0] if future else max(weeks_with_games))
    return {"season": season, "current_week": current_week, "games": games}

def refresh_espn(store, season=None):
    """Refresh schedule/scores from ESPN. Previous good data survive any provider failure."""
    try:
        apply_snapshot(store, espn_snapshot(season))
        with store.transaction() as db:
            store.set(db, "source", "espn")
        return True
    except Exception as exc:
        print(f"ESPN refresh failed: {exc}", flush=True)
        with store.transaction() as db:
            store.set(db, "provider_error", "NFL-Daten konnten gerade nicht aktualisiert werden. Die zuletzt geladenen Daten bleiben sichtbar.")
        return False
