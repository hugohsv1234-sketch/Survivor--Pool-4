import json
import sqlite3
import os
import time
from contextlib import contextmanager
from pathlib import Path
from . import demo
from .security import hash_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY,city TEXT NOT NULL,name TEXT NOT NULL,full_name TEXT NOT NULL,color TEXT NOT NULL,logo TEXT);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE COLLATE NOCASE,display_name TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'player',joined_week INTEGER NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,season INTEGER NOT NULL,week INTEGER NOT NULL CHECK(week BETWEEN 1 AND 22),away TEXT NOT NULL REFERENCES teams(id),home TEXT NOT NULL REFERENCES teams(id),kickoff REAL NOT NULL,status TEXT NOT NULL CHECK(status IN ('scheduled','live','final','postponed','cancelled')),away_score INTEGER,home_score INTEGER,started_at REAL,CHECK(away<>home));
CREATE INDEX IF NOT EXISTS idx_games_season_week ON games(season,week);
CREATE TABLE IF NOT EXISTS picks(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),season INTEGER NOT NULL,week INTEGER NOT NULL,game_id TEXT NOT NULL REFERENCES games(id),team TEXT NOT NULL REFERENCES teams(id),created_at REAL NOT NULL,updated_at REAL NOT NULL,locked_at REAL,UNIQUE(user_id,season,week));
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),csrf TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits(key TEXT PRIMARY KEY,count INTEGER NOT NULL,reset_at REAL NOT NULL);
"""


class ClosingConnection(sqlite3.Connection):
    """A read context also closes its handle, including WAL sidecar handles."""
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class PostgresConnection:
    """Small compatibility layer so the existing store can use SQLite locally and Postgres on Neon."""
    def __init__(self, url):
        import psycopg
        from psycopg.rows import dict_row
        self.raw = psycopg.connect(url, row_factory=dict_row)

    @staticmethod
    def _sql(sql):
        return sql.replace("?", "%s")

    def execute(self, sql, params=()):
        return self.raw.execute(self._sql(sql), params)

    def executescript(self, script):
        for statement in script.split(";"):
            if statement.strip():
                self.raw.execute(statement)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()


class Store:
    def __init__(self, path, demo_mode=True):
        self.path = str(path)
        self.database_url = os.environ.get("DATABASE_URL")
        self.postgres = bool(self.database_url)
        if not self.postgres:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            schema = SCHEMA
            if self.postgres:
                schema = schema.replace("id INTEGER PRIMARY KEY,username", "id BIGSERIAL PRIMARY KEY,username")
                schema = schema.replace("id INTEGER PRIMARY KEY,user_id", "id BIGSERIAL PRIMARY KEY,user_id")
                schema = schema.replace(" UNIQUE COLLATE NOCASE", " UNIQUE")
            db.executescript(schema)
            if not self.postgres:
                db.execute("PRAGMA journal_mode=WAL")
            if not db.execute("SELECT 1 FROM settings LIMIT 1").fetchone():
                if demo_mode:
                    demo.seed(db, time.time(), hash_password("Survivor2026!"))
                else:
                    for tid, city, name, color in demo.TEAMS:
                        db.execute("INSERT INTO teams VALUES(?,?,?,?,?,NULL)", (tid, city, name, f"{city} {name}", color))
                    for key, value in {"season": 2026, "current_week": 1, "clock_offset": 0, "tie_is_loss": True,
                                       "allow_after_elimination": True, "missing_pick_eliminates": True,
                                       "source": "json", "last_sync": None, "provider_error": "Noch keine Spieldaten geladen."}.items():
                        self.set(db, key, value)
            if not demo_mode and self.settings(db).get("source") == "demo":
                raise RuntimeError("Produktivmodus benötigt eine eigene, leere Datenbank (POOL_DB).")
            db.commit()

    def connect(self):
        if self.postgres:
            return PostgresConnection(self.database_url)
        db = sqlite3.connect(self.path, timeout=15, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN" if self.postgres else "BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def settings(db):
        return {row["key"]: json.loads(row["value"]) for row in db.execute("SELECT * FROM settings")}

    @staticmethod
    def set(db, key, value):
        db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    @staticmethod
    def lock_due(db, now):
        # A lock stays in place even if a feed subsequently moves kickoff later.
        db.execute("""UPDATE picks SET locked_at=? WHERE locked_at IS NULL AND game_id IN
                      (SELECT id FROM games WHERE (status='scheduled' AND kickoff<=?) OR started_at IS NOT NULL OR status IN ('live','final'))""", (now, now))
