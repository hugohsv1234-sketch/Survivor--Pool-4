#!/usr/bin/env python3
"""Run locally: python3 server.py. Production WSGI entry: server:application."""
import argparse
import os
import threading
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server
from backend.app import App
from backend.providers import refresh

ROOT = Path(__file__).resolve().parent


def create_app(port=8000, host="127.0.0.1"):
    production = os.environ.get("POOL_ENV") == "production"
    secret_hash = os.environ.get("POOL_PASSWORD_HASH")
    secret = os.environ.get("POOL_PASSWORD")
    if production and (not (secret_hash or secret) or not os.environ.get("POOL_ORIGIN")):
        raise RuntimeError("POOL_ENV=production benötigt POOL_PASSWORD_HASH (oder POOL_PASSWORD) und POOL_ORIGIN=https://…")
    origins = os.environ.get("POOL_ORIGIN", f"http://localhost:{port},http://127.0.0.1:{port}").split(",")
    if production and any(not origin.startswith("https://") for origin in origins):
        raise RuntimeError("Produktive Origins müssen HTTPS verwenden.")
    app = App(os.environ.get("POOL_DB", str(ROOT / "data" / ("pool.sqlite3" if production else "demo.sqlite3"))),
              ROOT / "public", demo_mode=not production, pool_password=secret,
              pool_password_hash=secret_hash, origins=origins, secure=production)
    if production and os.environ.get("NFL_FEED_URL"):
        def poll():
            while True:
                refresh(app.store, os.environ["NFL_FEED_URL"], os.environ.get("NFL_FEED_TOKEN"))
                threading.Event().wait(60)
        threading.Thread(target=poll, daemon=True).start()
    return app


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Survivor Pool lokal starten")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    app = create_app(args.port, args.host)
    print(f"\n  SURVIVOR POOL\n  Im Browser öffnen: http://localhost:{args.port}\n  Beenden: Strg+C\n", flush=True)
    try:
        with make_server(args.host, args.port, app, server_class=ThreadedServer) as server:
            server.serve_forever()
    except KeyboardInterrupt:
        print("\nSurvivor Pool beendet.")
else:
    # Imported by a real WSGI server, e.g. Gunicorn; never use the dev server publicly.
    application = create_app(int(os.environ.get("PORT", "8000")))
