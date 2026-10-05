"""End-to-end HTTP semantics through the WSGI boundary, with real SQLite.

No network access is needed. Threads exercise concurrent account/pick writes.
Each test starts from a fresh database, so no demo progress is changed.
"""
import io
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from backend.app import App
from backend.security import hash_password, verify_password
from backend.providers import apply_snapshot, refresh, utc_timestamp

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
