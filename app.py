"""Vercel entry point for the existing Survivor Pool WSGI backend.

Render still uses server:application.  Serverless requests MUST NOT start the
Render-only two-minute background polling thread in server.create_app().
The Vercel deployment always runs as production and uses the same external Neon
database; it never silently falls back to a local SQLite demo database.
"""
import os
import threading
from pathlib import Path
from urllib.parse import urlsplit

from backend.app import App

ROOT = Path(__file__).resolve().parent


class _ConfigurationError(Exception):
    """A missing production secret or domain; do not start an unsafe demo."""


def _production_origins():
    candidates = [
        value.strip()
        for value in os.environ.get("POOL_ORIGIN", "").split(",")
        if value.strip()
    ]
    # Vercel supplies these during deployments.  Unlike Render, the assigned
    # production URL may not be known until the first successful build.
    for key in ("VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_URL"):
        hostname = os.environ.get(key, "").strip()
        if hostname:
            candidates.append("https://" + hostname)
    origins = []
    for candidate in candidates:
        candidate = candidate.rstrip("/")
        parsed = urlsplit(candidate)
        if (
            parsed.scheme != "https:"
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise _ConfigurationError("POOL_ORIGIN muss eine HTTPS-Website-Adresse sein.")
        if candidate not in origins:
            origins.append(candidate)
    if not origins:
        raise _ConfigurationError(
            "POOL_ORIGIN fehlt: bitte die Vercel-Domain hinterlegen."
        )
    return tuple(origins)


def _create_production_app():
    if not os.environ.get("DATABASE_URL", "").strip():
        raise _ConfigurationError(
            "DATABASE_URL fehlt. Neon verbinden; niemals eine neue Demo-Datenbank anlegen."
        )
    password = os.environ.get("POOL_PASSWORD")
    password_hash = os.environ.get("POOL_PASSWORD_HASH")
    if not password and not password_hash:
        raise _ConfigurationError(
            "POOL_PASSWORD oder POOL_PASSWORD_HASH fehlt."
        )
    return App(
        str(ROOT / "data" / "pool.sqlite3"),
        ROOT / "public",
        demo_mode=False,
        pool_password=password,
        pool_password_hash=password_hash,
        origins=_production_origins(),
        secure=True,
    )


class _LazyWSGI:
    """Initialize only at request time, not during a Vercel build.

    The database connection is not attempted at import time.  A failed or
    missing configuration gives a 503, not an insecure demo application.
    """

    def __init__(self):
        self._backend = None
        self._lock = threading.Lock()

    def __call__(self, environ, start_response):
        try:
            if self._backend is None:
                with self._lock:
                    if self._backend is None:
                        self._backend = _create_production_app()
            return self._backend(environ, start_response)
        except _ConfigurationError as error:
            body = (
                "Survivor Pool: Vercel-Konfiguration fehlt. "
                + str(error)
            ).encode("utf-8")
            start_response(
                "503 Service Unavailable",
                [
                    ("Content-Type", "text/plain; charset=utf-8"),
                    ("Cache-Control", "no-store"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]


# Vercel looks for a root-level variable literally named 'app'.
# server.py continues exposing 'application' for Render.
app = _LazyWSGI()
