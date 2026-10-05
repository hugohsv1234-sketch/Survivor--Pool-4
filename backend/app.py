"""WSGI HTTP adapter. All private data and writes require a server-side session."""
import hmac
import json
import mimetypes
import re
import sqlite3
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import unquote, urlsplit
from .rules import RuleError, outcome, statistics, validate_pick, opponent, started
from .security import hash_password, verify_password, token, token_hash
from .store import Store
from .demo import week_name


class App:
    def __init__(self, db_path, public_dir, demo_mode=True, pool_password=None,
                 pool_password_hash=None, origins=("http://localhost:8000",), secure=False):
        self.store = Store(db_path, demo_mode)
        self.public = Path(public_dir).resolve()
        self.demo_mode, self.origins, self.secure = demo_mode, set(origins), secure
        self.pool_hash = pool_password_hash or hash_password(pool_password or "NURDERHSV")
        self.dummy_hash = hash_password(token())

    def __call__(self, env, start_response):
        headers = [("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
                   ("Referrer-Policy", "same-origin"), ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
                   ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")]
        if self.secure:
            headers.append(("Strict-Transport-Security", "max-age=31536000"))
        try:
            hosts = {urlsplit(origin).netloc for origin in self.origins}
            if env.get("HTTP_HOST") not in hosts:
                raise RuleError("Nicht erlaubte Server-Adresse.", 403)
            path, method = unquote(env.get("PATH_INFO", "/")), env["REQUEST_METHOD"]
            if path.startswith("/api/"):
                headers += [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")]
                if method not in ("GET", "POST"):
                    raise RuleError("Methode nicht erlaubt.", 405)
                data = {}
                if method == "POST":
                    if env.get("HTTP_ORIGIN") not in self.origins:
                        raise RuleError("Anfrage von einer fremden Seite abgelehnt.", 403, "origin")
                    if env.get("CONTENT_TYPE", "").split(";")[0].strip() != "application/json":
                        raise RuleError("JSON erforderlich.", 415)
                    try:
                        size = int(env.get("CONTENT_LENGTH", 0))
                    except ValueError:
                        raise RuleError("Ungültige Anfrage.")
                    if size < 0 or size > 16384:
                        raise RuleError("Anfrage zu groß.", 413)
                    try:
                        data = json.loads(env["wsgi.input"].read(size))
                    except (ValueError, UnicodeError):
                        raise RuleError("Ungültiges JSON.")
                    if not isinstance(data, dict):
                        raise RuleError("Ungültige Anfrage.")
                result, cookie = self.api(path, method, data, env)
                if cookie:
                    headers.append(("Set-Cookie", cookie))
                body, status = json.dumps(result, ensure_ascii=False).encode(), 200
            else:
                if method not in ("GET", "HEAD"):
                    raise RuleError("Methode nicht erlaubt.", 405)
                target = (self.public / (path.lstrip("/") or "index.html")).resolve()
                if not target.is_relative_to(self.public) or not target.is_file() or any(p.startswith(".") for p in target.relative_to(self.public).parts):
                    raise RuleError("Datei nicht gefunden.", 404)
                body = target.read_bytes()
                mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                headers += [("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime.endswith("javascript") else "")),
                            ("Cache-Control", "no-cache"), ("Service-Worker-Allowed", "/")]
                status = 200
                if method == "HEAD":
                    body = b""
        except RuleError as error:
            status, body = error.status, json.dumps({"error": str(error), "code": error.code}, ensure_ascii=False).encode()
            headers = [(k, v) for k, v in headers if k not in ("Content-Type", "Cache-Control")]
            headers += [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")]
        except Exception:
            import traceback
            traceback.print_exc()
            status, body = 500, b'{"error":"Serverfehler. Bitte erneut versuchen."}'
            headers += [("Cache-Control", "no-store")]
        labels = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 409: "Conflict", 413: "Payload Too Large", 415: "Unsupported Media Type", 429: "Too Many Requests", 500: "Internal Server Error", 405: "Method Not Allowed", 503: "Service Unavailable"}
        headers.append(("Content-Length", str(len(body))))
        start_response(f"{status} {labels.get(status, 'Error')}", headers)
        return [body]

    def cookie(self, value, expires=False):
        return f"survivor_session={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if expires else 2592000}" + ("; Secure" if self.secure else "")

    def session(self, db, env):
        try:
            cookies = SimpleCookie(env.get("HTTP_COOKIE", ""))
            raw = cookies["survivor_session"].value if "survivor_session" in cookies else ""
            return db.execute("SELECT * FROM sessions WHERE token_hash=? AND expires>?", (token_hash(raw), time.time())).fetchone()
        except Exception:
            return None

    def new_session(self, db, user_id=None, previous=None):
        if previous:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (previous["token_hash"],))
        db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        raw, csrf = token(), token()
        db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (token_hash(raw), user_id, csrf, time.time() + (2592000 if user_id else 1800)))
        return {"gated": True, "authenticated": user_id is not None, "csrf": csrf, "demo": self.demo_mode}, self.cookie(raw)

    def rate_limit(self, env, scope):
        # Persist the attempt outside the request transaction, including failures.
        key = scope + ":" + env.get("REMOTE_ADDR", "local")
        with self.store.transaction() as db:
            now = time.time()
            db.execute("DELETE FROM rate_limits WHERE reset_at<?", (now,))
            row = db.execute("SELECT * FROM rate_limits WHERE key=?", (key,)).fetchone()
            if row and row["count"] >= 30:
                raise RuleError("Zu viele Versuche. Bitte in 15 Minuten erneut versuchen.", 429)
            db.execute("INSERT INTO rate_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1", (key, now + 900))

    @staticmethod
    def fields(data, required, optional=()):
        if set(data) - set(required) - set(optional) or any(key not in data for key in required):
            raise RuleError("Ungültige oder fehlende Felder.")

    @staticmethod
    def text(data, key, minimum=1, maximum=128):
        value = data.get(key)
        if not isinstance(value, str) or not minimum <= len(value) <= maximum:
            raise RuleError(f"Bitte prüfe das Feld {key}.")
        return value

    def api(self, path, method, data, env):
        if path in ("/api/gate", "/api/login", "/api/register") and method == "POST":
            self.rate_limit(env, path)
        with self.store.transaction() as db:
            sess = self.session(db, env)
            if path == "/api/session" and method == "GET":
                return {"gated": bool(sess), "authenticated": bool(sess and sess["user_id"]),
                        "csrf": sess["csrf"] if sess else None,
                        **({"demo": self.demo_mode} if sess else {})}, None
            if path == "/api/gate" and method == "POST":
                self.fields(data, ("password",))
                password = self.text(data, "password")
                if not verify_password(password, self.pool_hash):
                    raise RuleError("Das Pool-Passwort stimmt nicht. Versuch es noch einmal.", 401)
                return self.new_session(db, previous=sess)
            if not sess:
                raise RuleError("Bitte öffne zuerst den privaten Pool.", 401, "session")
            if method == "POST" and not hmac.compare_digest(env.get("HTTP_X_CSRF_TOKEN", ""), sess["csrf"]):
                raise RuleError("Ungültige Sitzung. Bitte lade die Seite neu.", 403, "csrf")
            settings = self.store.settings(db)
            now = time.time() + (settings["clock_offset"] if self.demo_mode else 0)
            if path in ("/api/register", "/api/login") and method == "POST":
                self.fields(data, ("username", "password", "display_name", "confirmation") if path.endswith("register") else ("username", "password"))
                username = self.text(data, "username", 3, 24).strip().lower()
                password = self.text(data, "password")
                if not re.fullmatch(r"[a-z0-9_]{3,24}", username):
                    raise RuleError("Benutzername: 3–24 Zeichen, nur Buchstaben, Zahlen und Unterstrich.")
                if path.endswith("register"):
                    display = self.text(data, "display_name", 1, 40).strip()
                    if not display or any(ord(c) < 32 for c in display):
                        raise RuleError("Bitte gib einen gültigen Anzeigenamen ein.")
                    if len(password) < 10:
                        raise RuleError("Dein Passwort benötigt mindestens 10 Zeichen.")
                    if password != data.get("confirmation"):
                        raise RuleError("Die Passwörter stimmen nicht überein.")
                    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                        raise RuleError("Dieser Benutzername ist bereits vergeben.", 409)
                    user_id = db.execute("INSERT INTO users(username,display_name,password_hash,role,joined_week,created_at) VALUES(?,?,?,'player',?,?)",
                                         (username, display, hash_password(password), settings["current_week"], now)).lastrowid
                else:
                    user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
                    valid = verify_password(password, user["password_hash"] if user else self.dummy_hash)
                    if not valid or not user:
                        raise RuleError("Benutzername oder Passwort stimmt nicht.", 401)
                    user_id = user["id"]
                return self.new_session(db, user_id, sess)
            if path == "/api/logout" and method == "POST":
                self.fields(data, ())
                db.execute("DELETE FROM sessions WHERE token_hash=?", (sess["token_hash"],))
                return {"ok": True}, self.cookie("", True)
            if not sess["user_id"]:
                raise RuleError("Bitte melde dich mit deinem persönlichen Account an.", 401, "session")
            user = dict(db.execute("SELECT id,username,display_name,role,joined_week FROM users WHERE id=?", (sess["user_id"],)).fetchone())
            self.store.lock_due(db, now)
            if path == "/api/state" and method == "GET":
                return self.snapshot(db, user, settings, now), None
            if path == "/api/pick" and method == "POST":
                self.fields(data, ("game_id", "team"))
                gid, team = self.text(data, "game_id", 1, 80), self.text(data, "team", 2, 4)
                games = {g["id"]: dict(g) for g in db.execute("SELECT * FROM games WHERE season=?", (settings["season"],))}
                if gid not in games:
                    raise RuleError("Spiel nicht gefunden.", 404)
                picks = [dict(p) for p in db.execute("SELECT * FROM picks WHERE user_id=? AND season=?", (user["id"], settings["season"]))]
                if not settings["allow_after_elimination"] and self.player_stats(user, picks, games, settings, now)["survivor"] is False:
                    raise RuleError("Du bist ausgeschieden. Weitere Tipps sind deaktiviert.", 409)
                validate_pick(game=games[gid], team=team, current_week=settings["current_week"], season=settings["season"],
                              picks=picks, games=games, now=now, allow_after_elimination=settings["allow_after_elimination"], tie_is_loss=settings["tie_is_loss"])
                db.execute("""INSERT INTO picks(user_id,season,week,game_id,team,created_at,updated_at) VALUES(?,?,?,?,?,?,?)
                              ON CONFLICT(user_id,season,week) DO UPDATE SET game_id=excluded.game_id,team=excluded.team,updated_at=excluded.updated_at""",
                           (user["id"], settings["season"], settings["current_week"], gid, team, now, now))
                return self.snapshot(db, user, settings, now), None
            if path == "/api/settings" and method == "POST":
                if user["role"] != "admin":
                    raise RuleError("Nur der Administrator darf Regeln ändern.", 403)
                self.fields(data, ("tie_is_loss", "allow_after_elimination", "missing_pick_eliminates"))
                if any(type(v) is not bool for v in data.values()):
                    raise RuleError("Regeln müssen Wahrheitswerte sein.")
                for key, value in data.items():
                    self.store.set(db, key, value)
                settings.update(data)
                return self.snapshot(db, user, settings, now), None
            if path == "/api/demo" and method == "POST":
                if not self.demo_mode or user["role"] != "admin":
                    raise RuleError("Nicht verfügbar.", 403)
                self.fields(data, ("action",), ("game_id", "winner"))
                action = data.get("action")
                if action in ("kickoff", "finish"):
                    gid = self.text(data, "game_id", 1, 80)
                    game = db.execute("SELECT * FROM games WHERE id=? AND season=? AND week=?", (gid, settings["season"], settings["current_week"])).fetchone()
                    if not game:
                        raise RuleError("Aktuelles Spiel nicht gefunden.", 404)
                    if action == "kickoff":
                        if game["status"] != "scheduled":
                            raise RuleError("Nur ein noch nicht gestartetes Spiel kann angepfiffen werden.", 409)
                        now = max(now, game["kickoff"])
                        self.store.set(db, "clock_offset", now - time.time())
                        db.execute("UPDATE games SET status='live',away_score=0,home_score=0,started_at=? WHERE id=?", (now, gid))
                    else:
                        winner = data.get("winner")
                        if winner not in ("away", "home", "tie"):
                            raise RuleError("Bitte wähle den Sieger.")
                        away, home = {"away": (27, 20), "home": (20, 27), "tie": (24, 24)}[winner]
                        db.execute("UPDATE games SET status='final',away_score=?,home_score=?,started_at=COALESCE(started_at,?) WHERE id=?", (away, home, now, gid))
                elif action == "next_week":
                    if settings["current_week"] >= 22:
                        raise RuleError("Der Super Bowl ist der letzte Spieltag.")
                    db.execute("UPDATE games SET status='final',away_score=24,home_score=17,started_at=COALESCE(started_at,kickoff) WHERE season=? AND week=? AND status!='final'", (settings["season"], settings["current_week"]))
                    settings["current_week"] += 1
                    self.store.set(db, "current_week", settings["current_week"])
                    first = db.execute("SELECT MIN(kickoff) FROM games WHERE season=? AND week=?", (settings["season"], settings["current_week"])).fetchone()[0]
                    now = max(now, first - 7200)
                    self.store.set(db, "clock_offset", now - time.time())
                else:
                    raise RuleError("Unbekannte Demo-Aktion.")
                self.store.lock_due(db, now)
                settings = self.store.settings(db)
                return self.snapshot(db, user, settings, now), None
            raise RuleError("Endpunkt nicht gefunden.", 404)

    @staticmethod
    def player_stats(user, picks, games, settings, now):
        stats = statistics(picks, games, settings["tie_is_loss"])
        picked_weeks = {p["week"] for p in picks}
        missed = []
        for week in range(user["joined_week"], settings["current_week"] + 1):
            fixtures = [g for g in games.values() if g["week"] == week and g["status"] != "cancelled"]
            if fixtures and all(started(g, now) for g in fixtures) and week not in picked_weeks:
                missed.append(week)
        stats["missed"] = missed
        if settings["missing_pick_eliminates"] and missed:
            stats["survivor"] = False
        return stats

    def snapshot(self, db, user, settings, now):
        games = {g["id"]: dict(g) for g in db.execute("SELECT * FROM games WHERE season=? ORDER BY week,kickoff,id", (settings["season"],))}
        users = [dict(u) for u in db.execute("SELECT id,username,display_name,role,joined_week FROM users")]
        picks = [dict(p) for p in db.execute("SELECT * FROM picks WHERE season=? ORDER BY week", (settings["season"],))]
        public = []
        for pick in picks:
            game = games[pick["game_id"]]
            pick["result"] = outcome(pick, game, settings["tie_is_loss"])
            pick["opponent"] = opponent(game, pick["team"])
            pick["locked"] = pick["locked_at"] is not None or started(game, now)
            if pick["user_id"] == user["id"] or pick["locked"]:
                public.append(pick)
        for player in users:
            player["stats"] = self.player_stats(player, [p for p in picks if p["user_id"] == player["id"]], games, settings, now)
        users.sort(key=lambda u: (-u["stats"]["wins"], u["display_name"].casefold(), u["username"]))
        user = next(u for u in users if u["id"] == user["id"])
        return {"me": user, "players": users, "picks": public, "games": list(games.values()),
                "teams": [dict(t) for t in db.execute("SELECT * FROM teams ORDER BY city,name")],
                "weeks": [{"number": n, "name": week_name(n)} for n in range(1, 23)],
                "season": settings["season"], "current_week": settings["current_week"], "now": now,
                "rules": {k: settings[k] for k in ("tie_is_loss", "allow_after_elimination", "missing_pick_eliminates")},
                "demo": self.demo_mode, "source_error": settings.get("provider_error"), "last_sync": settings.get("last_sync")}
