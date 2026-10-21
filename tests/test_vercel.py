"""Vercel WSGI adapter tests; entirely local and isolated."""
import os
import unittest
from unittest.mock import patch
import app as entry


class VercelSmoke(unittest.TestCase):
    def test_entrypoint_is_callable(self):
        self.assertTrue(callable(entry.app))

    def test_without_database_configuration_returns_503(self):
        with patch.dict(os.environ, {}, clear=True):
            seen = []
            body = b"".join(entry._LazyWSGI()(
                {"PATH_INFO": "/api/session", "REQUEST_METHOD": "GET"},
                lambda status, headers: seen.append((status, dict(headers))),
            ))
        self.assertTrue(seen[0][0].startswith("503 "))
        self.assertEqual(seen[0][1]["Cache-Control"], "no-store")
        self.assertIn(b"DATABASE_URL", body)

    def test_only_https_origins_are_accepted(self):
        with patch.dict(os.environ, {"POOL_ORIGIN": "http://invalid.example"}, clear=True):
            with self.assertRaises(entry._ConfigurationError):
                entry._production_origins()

    def test_vercel_production_hostname_is_auto_detected(self):
        with patch.dict(os.environ, {"VERCEL_PROJECT_PRODUCTION_URL": "my-pool.vercel.app"}, clear=True):
            self.assertEqual(entry._production_origins(), ("https://my-pool.vercel.app",))


if __name__ == "__main__":
    unittest.main()
