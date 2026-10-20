"""WSGI HTTP adapter. All private data and writes require a server-side session."""
import hmac
import base64
import binascii
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


HISTORICAL_SHEET = "Frank|JAX-CLE:g|TB-CLE:r|SF-ARI:g|MIN-MIA:g|DAL-TB:r|IND-TEN:r\nJochen|CHI-CAR:g|CAR-ATL:g|DET-NYJ:g|MIN-MIA:g|LV-NE:r|IND-TEN:r\nSven|LV-MIA:g|TB-CLE:r|NYG-TEN:g|MIN-MIA:g|JAX-PHI:g|LAR-ARI:r\nLiche|LAC-ARI:r|TB-CLE:r|NO-LV:r|MIN-MIA:g|-:p|IND-TEN:r\nMomo|LAC-ARI:r|TB-CLE:r|GB-ATL:r|MIN-MIA:g|DAL-TB:r|IND-TEN:r\nLulle|JAX-CLE:g|DAL-WAS:g|GB-ATL:r|MIN-MIA:g|PIT-IND:g|LAR-ARI:r\nLetti|CHI-CAR:g|DAL-WAS:g|NO-LV:r|MIN-MIA:g|DAL-TB:r|IND-TEN:r\nAlec|LAC-ARI:r|GB-NYJ:g|MIN-TB:g|BAL-TEN:g|DAL-TB:r|CAR-PHI:g\nFlo|LAC-ARI:r|TB-CLE:r|GB-ATL:r|DET-CAR:r|DAL-TB:r|IND-TEN:r\nSascha|LAC-ARI:r|TB-CLE:r|CAR-CLE:r|DET-CAR:r|DAL-TB:r|NE-NYJ:g\nMarkus|JAX-CLE:g|CAR-ATL:g|GB-ATL:r|BAL-TEN:g|HOU-TEN:g|IND-TEN:r\nMax|PIT-ATL:g|TB-CLE:r|NO-LV:r|GB-TB:g|DEN-LAC:g|IND-TEN:r\nConner|JAX-CLE:g|TB-CLE:r|GB-ATL:r|BAL-TEN:g|DET-ARI:g|NE-NYJ:g\nBertram|JAX-CLE:g|TB-CLE:r|GB-ATL:r|DET-CAR:r|DAL-TB:r|IND-TEN:r\nPatrick|CHI-CAR:g|CAR-ATL:g|GB-ATL:r|NO-ATL:r|CLE-NYJ:r|IND-TEN:r"

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
            path, method = unquote(env.get("PATH_INFO", "/")), env["REQUEST_METHOD"]
            # Render's internal health check uses an internal host:port rather than
            # the public POOL_ORIGIN. Allow only GET / for that platform probe.
            render_probe = method == "GET" and path == "/" and env.get("HTTP_USER_AGENT", "").startswith("Render/")
            hosts = {urlsplit(origin).netloc for origin in self.origins}
            if env.get("HTTP_HOST") not in hosts and not render_probe:
                raise RuleError("Nicht erlaubte Server-Adresse.", 403)
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
                    if size < 0 or size > (110000 if path == '/api/avatar' else 16384):
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
            db.execute("INSERT INTO rate_limits(key,count,reset_at) VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=rate_limits.count+1,reset_at=excluded.reset_at", (key, now + 900))

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
        if path in ("/api/login", "/api/register") and method == "POST":
            self.rate_limit(env, path)
        with self.store.transaction() as db:
            sess = self.session(db, env)
            if path == "/api/session" and method == "GET":
                if not sess:
                    return self.new_session(db)
                return {"gated": True, "authenticated": bool(sess["user_id"]),
                        "csrf": sess["csrf"], "demo": self.demo_mode}, None
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
                    if len(password) < 5:
                        raise RuleError("Dein Passwort benötigt mindestens 5 Zeichen.")
                    if password != data.get("confirmation"):
                        raise RuleError("Die Passwörter stimmen nicht überein.")
                    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                        raise RuleError("Dieser Benutzername ist bereits vergeben.", 409)
                    cursor = db.execute("INSERT INTO users(username,display_name,password_hash,role,joined_week,created_at) VALUES(?,?,?,'player',?,?)" +
                                        (" RETURNING id" if self.store.postgres else ""),
                                        (username, display, hash_password(password), settings["current_week"], now))
                    user_id = cursor.fetchone()["id"] if self.store.postgres else cursor.lastrowid
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
                return self.new_session(db)
            if not sess["user_id"]:
                raise RuleError("Bitte melde dich mit deinem persönlichen Account an.", 401, "session")
            user = dict(db.execute("SELECT id,username,display_name,role,joined_week FROM users WHERE id=?", (sess["user_id"],)).fetchone())
            if path == "/api/change-password" and method == "POST":
                self.fields(data, ("current_password", "new_password", "confirmation"))
                current = self.text(data, "current_password", 1, 128)
                new = self.text(data, "new_password", 5, 128)
                if new != data["confirmation"]:
                    raise RuleError("Die neuen Passwörter stimmen nicht überein.")
                stored = db.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
                if not verify_password(current, stored["password_hash"]):
                    raise RuleError("Das bisherige Passwort ist falsch.", 403)
                if current == new:
                    raise RuleError("Bitte wähle ein anderes Passwort.")
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), user["id"]))
                db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user["id"], sess["token_hash"]))
                return {"ok": True}, None
            if path == "/api/avatar" and method == "POST":
                self.fields(data, ("image",))
                raw = data["image"]
                if raw is None:
                    db.execute("DELETE FROM profile_images WHERE user_id=?", (user["id"],))
                    return {"ok": True}, None
                if not isinstance(raw, str) or len(raw) > 95000:
                    raise RuleError("Profilbild zu groß (maximal 65 KB).")
                match = re.fullmatch(r"data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/]+={0,2})", raw)
                if not match:
                    raise RuleError("Bitte ein JPEG-, PNG- oder WebP-Bild verwenden.")
                try:
                    image_bytes = base64.b64decode(match.group(2), validate=True)
                except (ValueError, binascii.Error):
                    raise RuleError("Bilddaten sind ungültig.")
                if len(image_bytes) > 65536 or not image_bytes:
                    raise RuleError("Profilbild zu groß (maximal 65 KB).")
                kind = match.group(1)
                valid = (kind == "jpeg" and image_bytes.startswith(b"\\xff\\xd8\\xff")) or (kind == "png" and image_bytes.startswith(b"\\x89PNG\\r\\n\\x1a\\n")) or (kind == "webp" and image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP")
                if not valid:
                    raise RuleError("Das Bildformat stimmt nicht.")
                db.execute("INSERT INTO profile_images(user_id,image_data) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET image_data=excluded.image_data", (user["id"], raw))
                return {"ok": True}, None
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
                validate_pick(game=games[gid], team=team, current_week=settings["current_week"], season=settings["season"],
                              picks=picks, games=games, now=now, allow_after_elimination=True, tie_is_loss=settings["tie_is_loss"])
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
                # Survivor status may change, but leaderboard and weekly picks
                # always continue through the complete season for everyone.
                data["allow_after_elimination"] = True
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
        # External public Moneyline ticket percentages, not pool picks and
        # never an odds-based estimate. Ignore unavailable or stale entries.
        published_splits = settings.get("public_bet_splits") or {}
        if isinstance(published_splits, dict):
            for gid, game in games.items():
                split = published_splits.get(gid)
                if not isinstance(split, dict):
                    continue
                updated_at = split.get("updated_at")
                values = split.get("percent")
                if not isinstance(updated_at, (int, float)) or not 0 <= now - updated_at < 5400:
                    continue
                if not isinstance(values, dict):
                    continue
                away, home = values.get(game["away"]), values.get(game["home"])
                if (isinstance(away, int) and not isinstance(away, bool)
                        and isinstance(home, int) and not isinstance(home, bool)
                        and 0 <= away <= 100 and 0 <= home <= 100
                        and abs(away + home - 100) <= 2):
                    game["public_bet_percent"] = {game["away"]: away, game["home"]: home}
                    game["public_bet_source"] = "DraftKings"
                    game["public_bet_updated_at"] = updated_at
        users = [dict(u) for u in db.execute("SELECT id,username,display_name,role,joined_week FROM users")]
        images = {row["user_id"]: row["image_data"] for row in db.execute("SELECT user_id,image_data FROM profile_images")}
        for player in users:
            player["avatar"] = images.get(player["id"])
        known = {}
        for player in users:
            known.setdefault(player["display_name"].strip().casefold(), []).append(player["id"])
        for line in HISTORICAL_SHEET.splitlines():
            name, *entries = line.split("|")
            ids = known.get(name.casefold(), [])
            if len(ids) != 1:
                continue
            for week, entry in enumerate(entries, 1):
                matchup, status = entry.rsplit(":", 1)
                if matchup == "-":
                    continue
                db.execute("INSERT INTO historical_picks(user_id,season,week,matchup,result) VALUES(?,?,?,?,?) ON CONFLICT(user_id,season,week) DO NOTHING",
                           (ids[0], settings["season"], week, matchup, {"g":"win","r":"loss","p":"pending"}[status]))
                # Week 6 was formerly entered as "pending"; the supplied
                # spreadsheet now has final red/green results. Update ONLY
                # unchanged pending historical rows for unique exact-name
                # matches and identical matchups. Never modify actual picks
                # or already-decided historical results.
                if week == 6 and status in ("g", "r"):
                    db.execute("UPDATE historical_picks SET result=? WHERE user_id=? AND season=? AND week=6 AND matchup=? AND result='pending'",
                               ("win" if status == "g" else "loss", ids[0], settings["season"], matchup))
        history = [dict(h) for h in db.execute("SELECT * FROM historical_picks WHERE season=? AND week<=? ORDER BY week", (settings["season"], settings["current_week"]))]
        # A formerly unique display name may have become ambiguous later.
        # Keep stored data intact, but only show/count historic results for
        # players whose current display name is uniquely matched.
        unique_history_ids = {ids[0] for ids in known.values() if len(ids) == 1}
        history = [h for h in history if h["user_id"] in unique_history_ids]
        picks = [dict(p) for p in db.execute("SELECT * FROM picks WHERE season=? ORDER BY week", (settings["season"],))]
        public = []
        for pick in picks:
            game = games[pick["game_id"]]
            pick["result"] = outcome(pick, game, settings["tie_is_loss"])
            pick["opponent"] = opponent(game, pick["team"])
            pick["locked"] = pick["locked_at"] is not None or started(game, now)
            if pick["user_id"] == user["id"] or pick["locked"]:
                public.append(pick)

        # Free pool-only pick distribution, NOT bookmaker betting odds.
        # Only publish a distribution once that game's kickoff has occurred:
        # no counts or choices from still-secret early picks can leak.
        available_games = {gid: g for gid, g in games.items() if started(g, now)}
        totals = {gid: {g["away"]: 0, g["home"]: 0}
                  for gid, g in available_games.items()}
        official_weeks = {(p["user_id"], p["week"]) for p in picks}
        for pick in picks:
            if pick["game_id"] in totals and pick["team"] in totals[pick["game_id"]]:
                totals[pick["game_id"]][pick["team"]] += 1
        for entry in history:
            # An official pick always takes precedence over imported history.
            if (entry["user_id"], entry["week"]) in official_weeks:
                continue
            try:
                selected, against = entry["matchup"].split("-", 1)
            except ValueError:
                continue
            for gid, g in available_games.items():
                if entry["week"] == g["week"] and selected in (g["away"], g["home"]) and set((selected, against)) == set((g["away"], g["home"])):
                    totals[gid][selected] += 1
                    break
        pick_rates = {}
        for gid, counts in totals.items():
            total = sum(counts.values())
            if total:
                pick_rates[gid] = {"total": total,
                                   "percent": {team: round(count * 100 / total)
                                               for team, count in counts.items()},
                                   "counts": counts}
        for player in users:
            own = [p for p in picks if p["user_id"] == player["id"]]
            player["stats"] = self.player_stats(player, own, games, settings, now)
            occupied = {p["week"] for p in own}
            extra = [h for h in history if h["user_id"] == player["id"] and h["week"] not in occupied]
            player["stats"]["wins"] += sum(h["result"] == "win" for h in extra)
            player["stats"]["losses"] += sum(h["result"] == "loss" for h in extra)
            player["stats"]["total"] += len(extra)
            if any(h["result"] == "loss" for h in extra):
                player["stats"]["survivor"] = False
            evaluated = player["stats"]["wins"] + player["stats"]["losses"]
            player["stats"]["rate"] = round(player["stats"]["wins"] / evaluated * 100) if evaluated else 0
        users.sort(key=lambda u: (-u["stats"]["wins"], u["display_name"].casefold(), u["username"]))
        user = next(u for u in users if u["id"] == user["id"])
        return {"me": user, "players": users, "picks": public, "historical_picks": history, "pick_rates": pick_rates, "games": list(games.values()),
                "teams": [dict(t) for t in db.execute("SELECT * FROM teams ORDER BY city,name")],
                "weeks": [{"number": n, "name": week_name(n)} for n in range(1, 23)],
                "season": settings["season"], "current_week": settings["current_week"], "now": now,
                "rules": {"tie_is_loss": settings["tie_is_loss"], "allow_after_elimination": True,
                          "missing_pick_eliminates": settings["missing_pick_eliminates"]},
                "demo": self.demo_mode, "source_error": settings.get("provider_error"), "last_sync": settings.get("last_sync")}
