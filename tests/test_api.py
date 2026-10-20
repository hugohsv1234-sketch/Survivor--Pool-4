"""End-to-end HTTP semantics through the WSGI boundary, with real SQLite.

No network access is needed. Threads exercise concurrent account/pick writes.
Each test starts from a fresh database, so no demo progress is changed.
"""
import io
import json
import tempfile
import time
from datetime import datetime
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from backend.app import App
from backend.security import hash_password, verify_password
from backend.providers import apply_snapshot, refresh, utc_timestamp
from backend.betting_splits import parse_ticket_percentages, refresh_ticket_percentages, NEW_YORK

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, app):
        self.app, self.cookie, self.csrf = app, "", ""

    def call(self, path, data=None, origin="http://localhost:8000", csrf=None, raw=None, method=None):
        content = raw if raw is not None else json.dumps(data or {}).encode()
        env = {"PATH_INFO": path, "REQUEST_METHOD": method or ("GET" if data is None and raw is None else "POST"),
               "HTTP_HOST": "localhost:8000", "HTTP_ORIGIN": origin,
               "REMOTE_ADDR": "127.0.0.1", "HTTP_COOKIE": self.cookie,
               "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(content)),
               "HTTP_X_CSRF_TOKEN": self.csrf if csrf is None else csrf,
               "wsgi.input": io.BytesIO(content)}
        meta = {}
        def start(status, headers):
            meta.update(status=int(status.split()[0]), headers=dict(headers))
        body = b"".join(self.app(env, start))
        if "Set-Cookie" in meta["headers"]:
            self.cookie = meta["headers"]["Set-Cookie"].split(";")[0]
        try:
            result = json.loads(body)
        except (ValueError, UnicodeError):
            result = body
        if isinstance(result, dict) and result.get("csrf"):
            self.csrf = result["csrf"]
        return meta["status"], result, meta["headers"]

    def gate(self):
        return self.call("/api/gate", {"password": "NURDERHSV"})

    def login(self, name="max"):
        self.gate()
        return self.call("/api/login", {"username": name, "password": "Survivor2026!"})

    def state(self):
        return self.call("/api/state")[1]


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Precompute hashes once, but test uses the real scrypt verifier.
        cls.pool_hash = hash_password("NURDERHSV")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = App(Path(self.temp.name) / "test.sqlite3", ROOT / "public", pool_password_hash=self.pool_hash)
        self.client = Client(self.app)

    def tearDown(self):
        self.temp.cleanup()

    def login(self):
        self.assertEqual(self.client.login()[0], 200)

    def select(self, team="BAL"):
        return self.client.call("/api/pick", {"game_id": "d2026-5-0", "team": team})

    def test_week_six_sheet_updates_old_pending_results_and_exact_names(self):
        self.login()
        # Simulate rows imported on the earlier deployment before week six ended.
        with self.app.store.connect() as db:
            db.execute("UPDATE historical_picks SET result='pending' WHERE user_id=1 AND week=6")
            for name in ("Alec", "Sascha", "Conner"):
                db.execute(
                    "INSERT INTO users(username,display_name,password_hash,role,joined_week,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (name.lower(), name, self.pool_hash, "player", 6, time.time()))
        # Results from future gameweeks must not leak into the leaderboard.
        before = self.client.state()
        self.assertFalse(any(h["week"] == 6 for h in before["historical_picks"]))
        status, after, _ = self.client.call("/api/demo", {"action": "next_week"})
        self.assertEqual(status, 200)
        players = {p["display_name"]: p for p in after["players"]}
        sixth = {(players_by_id["display_name"], h["week"]): h
                 for h in after["historical_picks"]
                 for players_by_id in after["players"] if players_by_id["id"] == h["user_id"]
                 and h["week"] == 6}
        self.assertEqual(sixth[("Max", 6)]["result"], "loss")
        self.assertEqual(sixth[("Max", 6)]["matchup"], "IND-TEN")
        for name, matchup in (("Alec", "CAR-PHI"), ("Sascha", "NE-NYJ"), ("Conner", "NE-NYJ")):
            self.assertEqual(sixth[(name, 6)]["result"], "win")
            self.assertEqual(sixth[(name, 6)]["matchup"], matchup)
        self.assertFalse(players["Max"]["stats"]["survivor"])
        # Refreshing repeatedly should not create duplicate historic picks.
        self.client.state()
        with self.app.store.connect() as db:
            rows = list(db.execute("SELECT * FROM historical_picks WHERE user_id=1 AND week=6"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["result"], "loss")

    def test_pool_rates_keep_early_picks_private_until_kickoff(self):
        self.login()
        self.assertEqual(self.select("BAL")[0], 200)
        second = Client(self.app)
        self.assertEqual(second.login("lea")[0], 200)
        self.assertNotIn("d2026-5-0", second.state()["pick_rates"])
        status, _, _ = self.client.call("/api/demo", {"action": "kickoff", "game_id": "d2026-5-0"})
        self.assertEqual(status, 200)
        rates = second.state()["pick_rates"]["d2026-5-0"]
        self.assertEqual(rates["total"], 1)
        self.assertEqual(rates["percent"]["BAL"], 100)
        self.assertEqual(rates["percent"]["CIN"], 0)

    def test_official_pick_takes_priority_over_historical_week_six(self):
        self.login()
        with self.app.store.connect() as db:
            fixture = db.execute("SELECT * FROM games WHERE week=6 LIMIT 1").fetchone()
            db.execute("INSERT INTO picks(user_id,season,week,game_id,team,created_at,updated_at,locked_at) "
                       "VALUES(?,?,?,?,?,?,?,?)",
                       (1, 2026, 6, fixture["id"], fixture["away"], time.time(), time.time(), None))
        _, result, _ = self.client.call("/api/demo", {"action": "next_week"})
        self.assertEqual(result["me"]["stats"]["losses"], 0)
        self.assertTrue(any(p["week"] == 6 and p["user_id"] == 1 for p in result["picks"]))

    def test_gate_authentication_and_logout_boundary(self):
        self.assertEqual(self.client.call("/api/state")[0], 401)
        self.assertEqual(self.client.call("/api/login", {"username":"max","password":"Survivor2026!"})[0], 401)
        self.assertEqual(self.client.call("/api/gate", {"password":"wrong"})[0], 401)
        self.assertEqual(self.client.gate()[0], 200)
        self.assertEqual(self.client.call("/api/state")[0], 401)
        old = self.client.cookie
        self.assertEqual(self.client.call("/api/login", {"username":"MAX","password":"Survivor2026!"})[0], 200)
        self.assertNotEqual(old, self.client.cookie)
        self.assertTrue(self.client.call("/api/session")[1]["authenticated"])
        self.assertEqual(self.client.call("/api/logout", {})[0], 200)
        self.assertEqual(self.client.call("/api/state")[0], 401)

    def test_csrf_and_cross_origin_rejected(self):
        self.login()
        self.assertEqual(self.client.call("/api/pick", {"game_id":"d2026-5-0","team":"BAL"}, csrf="")[0], 403)
        self.assertEqual(self.client.call("/api/pick", {"game_id":"d2026-5-0","team":"BAL"}, origin="https://evil.example")[0], 403)

    def test_registration_validation_and_case_insensitive_uniqueness(self):
        self.client.gate()
        fields = {"username":"new_player", "display_name":"Neuer Spieler", "password":"longpassword123", "confirmation":"longpassword123"}
        self.assertEqual(self.client.call("/api/register", {**fields,"confirmation":"different"})[0], 400)
        self.assertEqual(self.client.call("/api/register", {**fields,"username":"MaX"})[0], 409)
        self.assertEqual(self.client.call("/api/register", {**fields,"username":"<script>"})[0], 400)
        self.assertEqual(self.client.call("/api/register", {**fields,"password":"short","confirmation":"short"})[0], 400)
        self.assertEqual(self.client.call("/api/register", fields)[0], 200)
        state = self.client.state()
        self.assertEqual(state["me"]["username"], "new_player")
        self.assertEqual(state["me"]["stats"]["missed"], [])
        with self.app.store.connect() as db:
            saved = db.execute("SELECT password_hash FROM users WHERE username='new_player'").fetchone()[0]
        self.assertNotIn("longpassword123", saved)
        self.assertTrue(saved.startswith("scrypt$"))
        self.assertTrue(verify_password("longpassword123", saved))

    def test_admin_role_cannot_be_submitted_at_registration(self):
        self.client.gate()
        data = {"username":"mallory","display_name":"M","password":"longpassword123","confirmation":"longpassword123","role":"admin"}
        self.assertEqual(self.client.call("/api/register", data)[0], 400)

    def test_one_pick_replacement_and_persistence(self):
        self.login()
        self.assertEqual(self.select()[0], 200)
        self.assertEqual(self.select("CIN")[0], 200)
        with self.app.store.connect() as db:
            rows = list(db.execute("SELECT * FROM picks WHERE user_id=1 AND week=5"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["team"], "CIN")
        second = Client(self.app)
        second.cookie = self.client.cookie
        self.assertTrue(second.call("/api/session")[1]["authenticated"])
        self.assertEqual([p for p in second.state()["picks"] if p["user_id"]==1 and p["week"]==5][0]["team"], "CIN")

    def test_reused_team_and_fourth_against_blocked_in_api(self):
        self.login()
        self.assertEqual(self.client.call("/api/pick", {"game_id":"d2026-5-1","team":"KC"})[1]["code"], "used")
        self.assertEqual(self.client.call("/api/pick", {"game_id":"d2026-5-2","team":"MIA"})[1]["code"], "against")
        self.assertEqual(self.client.call("/api/pick", {"game_id":"d2026-5-2","team":"NE"})[0], 200)

    def test_server_time_and_old_pick_lock_override_browser_requests(self):
        self.login()
        self.select()
        self.assertEqual(self.client.call("/api/demo", {"action":"kickoff","game_id":"d2026-5-0"})[0], 200)
        future = self.client.state()["games"]
        later = next(g for g in future if g["week"]==5 and g["kickoff"]>self.client.state()["now"])
        response=self.client.call("/api/pick", {"game_id":later["id"],"team":later["away"]})
        self.assertEqual(response[0], 409)
        self.assertEqual(response[1]["code"], "locked")
        self.assertEqual(self.client.call("/api/pick", {"game_id":later["id"],"team":later["away"],"now":0})[0], 400)

    def test_future_week_wrong_team_and_identity_injection_rejected(self):
        self.login()
        for payload in [{"game_id":"d2026-6-0","team":"CIN"}, {"game_id":"d2026-5-0","team":"NE"},
                        {"game_id":"d2026-5-0","team":"BAL","user_id":2}, {"game_id":[],"team":"BAL"}]:
            self.assertGreaterEqual(self.client.call("/api/pick", payload)[0],400)

    def test_other_players_picks_hidden_until_kickoff(self):
        self.login()
        self.select()
        second=Client(self.app)
        second.login("lea")
        self.assertFalse(any(p["user_id"]==1 and p["week"]==5 for p in second.state()["picks"]))
        self.client.call("/api/demo", {"action":"kickoff","game_id":"d2026-5-0"})
        self.assertTrue(any(p["user_id"]==1 and p["week"]==5 for p in second.state()["picks"]))

    def test_final_result_and_configurable_tie_automatic_recalculation(self):
        self.login()
        self.select()
        self.client.call("/api/demo", {"action":"finish","game_id":"d2026-5-0","winner":"away"})
        self.assertEqual(self.client.state()["me"]["stats"]["wins"],5)
        self.client.call("/api/demo", {"action":"finish","game_id":"d2026-5-0","winner":"home"})
        self.assertEqual(self.client.state()["me"]["stats"]["losses"],1)
        self.client.call("/api/demo", {"action":"finish","game_id":"d2026-5-0","winner":"tie"})
        settings = {"tie_is_loss":False,"allow_after_elimination":True,"missing_pick_eliminates":True}
        self.assertEqual(self.client.call("/api/settings",settings)[0],200)
        stats = self.client.state()["me"]["stats"]
        self.assertEqual((stats["wins"],stats["losses"],stats["pushes"],stats["survivor"]),(4,0,1,True))

    def test_admin_checks_and_invalid_demo_requests(self):
        self.client.login("lea")
        self.assertEqual(self.client.call("/api/demo", {"action":"next_week"})[0],403)
        self.assertEqual(self.client.call("/api/settings", {"tie_is_loss":False,"allow_after_elimination":True,"missing_pick_eliminates":True})[0],403)
        self.login()
        self.assertEqual(self.client.call("/api/demo", {"action":"finish","game_id":"d2026-5-0","winner":"invented"})[0],400)
        self.assertEqual(self.client.call("/api/settings", {"tie_is_loss":"false","allow_after_elimination":True,"missing_pick_eliminates":True})[0],400)

    def test_missed_week_and_new_week_progression(self):
        self.login()
        self.assertEqual(self.client.call("/api/demo", {"action":"next_week"})[0],200)
        d=self.client.state()
        self.assertEqual(d["current_week"],6)
        self.assertIn(5,d["me"]["stats"]["missed"])
        self.assertFalse(d["me"]["stats"]["survivor"])

    def test_season_and_rankings_continue_even_after_everyone_eliminated(self):
        self.login()
        # All demo users missed week 5 and are eliminated when week 6 begins.
        self.assertEqual(self.client.call("/api/demo", {"action":"next_week"})[0], 200)
        data = self.client.state()
        self.assertEqual(data["current_week"], 6)
        self.assertEqual(len(data["players"]), 6)
        self.assertTrue(all(not p["stats"]["survivor"] for p in data["players"]))
        self.assertTrue(data["rules"]["allow_after_elimination"])
        # Even an old/admin request to disable post-elimination picking cannot
        # silently stop the public pool from continuing through the season.
        settings={"tie_is_loss":True,"allow_after_elimination":False,"missing_pick_eliminates":True}
        self.assertEqual(self.client.call("/api/settings", settings)[0], 200)
        self.assertTrue(self.client.state()["rules"]["allow_after_elimination"])
        before=self.client.state()["me"]["stats"]
        selected = None
        for game in self.client.state()["games"]:
            if game["week"] != 6 or game["status"] != "scheduled":
                continue
            response = self.client.call("/api/pick", {"game_id": game["id"], "team": game["away"]})
            if response[0] == 200:
                selected = game
                break
        self.assertIsNotNone(selected, "A non-used valid team must remain pickable")
        current=self.client.state()["me"]["stats"]
        self.assertEqual(current["total"], before["total"]+1)
        self.assertFalse(current["survivor"])
        self.assertEqual(self.client.call("/api/demo", {
            "action": "finish", "game_id": selected["id"], "winner": "away"
        })[0], 200)
        updated=self.client.state()
        self.assertEqual(updated["me"]["stats"]["wins"],before["wins"]+1)
        self.assertFalse(updated["me"]["stats"]["survivor"])
        self.assertEqual(self.client.call("/api/demo", {"action":"next_week"})[0], 200)
        self.assertEqual(self.client.state()["current_week"],7)

    def test_concurrent_requests_leave_exactly_one_pick(self):
        self.login()
        cookie,csrf = self.client.cookie,self.client.csrf
        def place(team):
            client=Client(self.app);client.cookie=cookie;client.csrf=csrf
            return client.call("/api/pick", {"game_id":"d2026-5-0","team":team})[0]
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(place,["BAL","CIN"]*3))
        self.assertEqual(results,[200]*6)
        with self.app.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM picks WHERE user_id=1 AND week=5").fetchone()[0],1)

    def test_private_files_and_passwords_are_never_served(self):
        for path in ("/backend/app.py","/server.py","/../server.py","/%2e%2e/server.py","/data/demo.sqlite3","/.env"):
            self.assertEqual(self.client.call(path)[0],404,path)
        self.login()
        d=self.client.state()
        serialized=json.dumps(d)
        self.assertNotIn("password_hash",serialized)
        self.assertNotIn("scrypt$",serialized)
        self.assertNotIn("NURDERHSV",serialized)
        self.assertEqual(self.client.call("/api/state")[2]["Cache-Control"],"no-store")

    def test_malformed_requests_and_oversize(self):
        self.assertEqual(self.client.call("/api/gate",raw=b'{broken')[0],400)
        self.assertEqual(self.client.call("/api/gate",raw=b'[]')[0],400)
        self.assertEqual(self.client.call("/api/gate",raw=b'x'*16385)[0],413)
        self.assertEqual(self.client.call("/api/state",method="PUT")[0],405)

    def test_rate_limiter_persists_failed_attempts(self):
        # Seed 29 attempts instead of spending several seconds hashing failures.
        with self.app.store.transaction() as db:
            db.execute("INSERT INTO rate_limits VALUES(?,29,?)",("/api/gate:127.0.0.1",time.time()+900))
        self.assertEqual(self.client.call("/api/gate",{"password":"wrong"})[0],401)
        self.assertEqual(self.client.gate()[0],429)

    def test_true_ticket_percentages_are_not_bookmaker_prices(self):
        html = """
        <article><h5>BAL Ravens @ CIN Bengals</h5><div>10/25, 01:00PM</div>
        <section>Moneyline</section><span>Odds</span><span>% Handle</span><span>% Bets</span>
        <div>CIN Bengals</div><a>-148</a><span>18%</span><span>15%</span>
        <div>BAL Ravens</div><a>+124</a><span>82%</span><span>85%</span>
        <div>Spread</div><div>BAL Ravens</div><span>10%</span><span>90%</span></article>
        """
        result = parse_ticket_percentages(html)
        self.assertEqual(result, {("BAL", "CIN", 10, 25): {"BAL": 85, "CIN": 15}})
        # Never fall back to a percentage computed from a market price.
        self.assertEqual(parse_ticket_percentages(
            "<h5>BAL Ravens @ CIN Bengals</h5><div>10/25</div>Moneyline "
            "<div>BAL Ravens</div><div>-130</div><div>CIN Bengals</div><div>+120</div>"), {})

    def test_public_ticket_percent_fetch_is_safe_optional_and_age_limited(self):
        self.login()
        with self.app.store.connect() as db:
            game = db.execute("SELECT * FROM games WHERE id='d2026-5-0'").fetchone()
            kickoff = datetime.fromtimestamp(game["kickoff"], NEW_YORK)
        day = f"{kickoff.month}/{kickoff.day}"
        page = (
            f"<h5>{game['away']} Ravens @ {game['home']} Bengals</h5>"
            f"<span>{day}, 01:00PM</span><div>Moneyline</div>"
            "<span>Odds</span><span>% Handle</span><span>% Bets</span>"
            "<div>CIN Bengals</div><div>-130</div><span>39%</span><span>65%</span>"
            "<div>BAL Ravens</div><div>+120</div><span>61%</span><span>35%</span>"
            "<div>Spread</div>")
        with patch("backend.betting_splits._fetch_page", return_value=page) as fetched:
            self.assertTrue(refresh_ticket_percentages(self.app.store))
            self.assertEqual(fetched.call_count, 2)
        state = self.client.state()
        observed = next(g for g in state["games"] if g["id"] == game["id"])
        self.assertEqual(observed["public_bet_percent"], {"BAL": 35, "CIN": 65})
        self.assertEqual(observed["public_bet_source"], "DraftKings")
        with self.app.store.transaction() as db:
            settings = self.app.store.settings(db)
            self.app.store.set(db, "public_bet_splits", {
                game["id"]: {"updated_at": time.time() - 10000,
                              "percent": {"BAL": 35, "CIN": 65}}})
        stale = next(g for g in self.client.state()["games"] if g["id"] == game["id"])
        self.assertNotIn("public_bet_percent", stale)

    def test_public_assets_and_pwa_cache_exclusion(self):
        for path in ("/","/css/app.css","/js/app.js","/manifest.json","/service-worker.js","/icons/icon-192.png","/icons/icon-512.png"):
            self.assertEqual(self.client.call(path)[0],200,path)
        manifest=self.client.call("/manifest.json")[1]
        self.assertEqual(manifest["display"],"standalone")
        sw=self.client.call("/service-worker.js")[1].decode()
        self.assertIn("url.pathname.startsWith('/api/')",sw)

    def test_prod_disallows_demo_database(self):
        from backend.store import Store
        with self.assertRaisesRegex(RuntimeError,"eigene, leere Datenbank"):
            Store(self.app.store.path,demo_mode=False)

    def test_empty_production_has_no_demo_accounts_and_secure_cookie(self):
        production=App(Path(self.temp.name)/"prod.sqlite3",ROOT/"public",demo_mode=False,
                       pool_password_hash=self.pool_hash,origins=("https://localhost:8000",),secure=True)
        client=Client(production)
        response=client.call("/api/gate",{"password":"NURDERHSV"},origin="https://localhost:8000")
        self.assertIn("; Secure",response[2]["Set-Cookie"])
        with production.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM games").fetchone()[0],0)

    def test_feed_validation_atomicity_and_last_good_fallback(self):
        store=self.app.store
        with store.connect() as db:
            before=db.execute("SELECT kickoff FROM games WHERE id='d2026-5-0'").fetchone()[0]
        good={"id":"newfeed1","week":5,"away":"BAL","home":"CIN","kickoff":"2026-10-04T19:00:00+02:00","status":"scheduled"}
        invalid={"season":2026,"current_week":5,"games":[good,{**good,"id":"newfeed2","away":"BAD"}]}
        with self.assertRaises(ValueError):
            apply_snapshot(store,invalid)
        with store.connect() as db:
            self.assertIsNone(db.execute("SELECT id FROM games WHERE id='newfeed1'").fetchone())
        self.assertFalse(refresh(store,"http://insecure.invalid"))
        with store.connect() as db:
            self.assertEqual(db.execute("SELECT kickoff FROM games WHERE id='d2026-5-0'").fetchone()[0],before)
            self.assertIsNotNone(store.settings(db)["provider_error"])

    def test_timezone_normalization_and_score_zero(self):
        self.assertEqual(utc_timestamp("2026-10-04T19:00:00+02:00"),utc_timestamp("2026-10-04T17:00:00Z"))
        with self.assertRaises(ValueError):
            utc_timestamp("2026-10-04T17:00:00")
        with self.assertRaises(ValueError):
            utc_timestamp(1e100)
        with self.assertRaises(ValueError):
            utc_timestamp(True)
        payload={"season":2026,"current_week":5,"games":[{"id":"feedtest","week":5,"away":"BAL","home":"CIN","kickoff":"2026-10-04T17:00:00Z","status":"final","away_score":0,"home_score":3}]}
        apply_snapshot(self.app.store,payload)
        with self.app.store.connect() as db:
            self.assertEqual(db.execute("SELECT away_score FROM games WHERE id='feedtest'").fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
