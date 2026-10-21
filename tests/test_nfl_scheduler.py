"""Local safety tests for the scheduled NFL updates (no Neon/network needed)."""
import os
import unittest
from unittest.mock import patch, MagicMock

from scripts import refresh_nfl


class SchedulerSafetyTests(unittest.TestCase):
    def test_requires_neon_postgres_not_sqlite_or_arbitrary_host(self):
        for value in (
            "",
            "sqlite:///test.db",
            "postgresql://user@not-neon.example/app",
            "postgresql://user@neon.tech.evil.example/app",
            "postgresql://user@ep-example.neon.tech/",
        ):
            with self.subTest(value=value), patch.dict(os.environ, {"DATABASE_URL": value}, clear=True):
                with self.assertRaises(RuntimeError):
                    refresh_nfl.required_neon_url()

    def test_accepts_pooled_and_unpooled_neon_endpoints(self):
        for host in (
            "ep-example-pooler.c-6.eu-west-2.aws.neon.tech",
            "ep-example.c-6.eu-west-2.aws.neon.tech",
        ):
            url = "postgresql://reader@" + host + "/neondb?sslmode=require"
            with patch.dict(os.environ, {"DATABASE_URL": url}, clear=True):
                self.assertEqual(refresh_nfl.required_neon_url(), url)

    def test_requires_preexisting_users_games_and_real_season(self):
        for players, games, season, source in (
            (0, 270, 2026, "espn"),
            (15, 0, 2026, "espn"),
            (15, 270, "unknown", "espn"),
            (15, 270, 2026, "demo"),
        ):
            with self.subTest(players=players,games=games,season=season,source=source):
                connection = MagicMock()
                db = connection.return_value.__enter__.return_value
                db.execute.return_value.fetchone.side_effect = [
                    {"total": players}, {"total": games}, {"total": 15},
                ]
                with patch.object(refresh_nfl, "PostgresConnection", connection), \
                     patch.object(refresh_nfl.Store, "settings", return_value={"season": season, "source": source}):
                    with self.assertRaises(RuntimeError):
                        refresh_nfl.inspect_existing_pool("test-only-placeholder")
                self.assertEqual(db.execute.call_count, 3)
                self.assertTrue(all(call.args[0].startswith("SELECT ") for call in db.execute.call_args_list))

    def test_preflight_is_read_only_and_reports_existing_season(self):
        connection = MagicMock()
        db = connection.return_value.__enter__.return_value
        db.execute.return_value.fetchone.side_effect = [
            {"total": 15}, {"total": 270}, {"total": 75},
        ]
        with patch.object(refresh_nfl, "PostgresConnection", connection), \
             patch.object(refresh_nfl.Store, "settings", return_value={"season": 2026, "source": "espn"}):
            self.assertEqual(refresh_nfl.inspect_existing_pool("test-only-placeholder"), 2026)
        self.assertTrue(all(call.args[0].startswith("SELECT ") for call in db.execute.call_args_list))

    def test_refresh_reuses_existing_espn_adapter_and_current_season(self):
        url = "postgresql://user@ep-example.neon.tech/neondb"
        with patch.dict(os.environ, {"DATABASE_URL": url}, clear=True), \
             patch.object(refresh_nfl, "inspect_existing_pool", return_value=2026), \
             patch.object(refresh_nfl, "Store") as store, \
             patch.object(refresh_nfl, "refresh_espn", return_value=True) as espn, \
             patch.object(refresh_nfl, "refresh_ticket_percentages") as splits:
            self.assertTrue(refresh_nfl.update())
            self.assertFalse(store.call_args.kwargs["demo_mode"])
            espn.assert_called_once_with(store.return_value, 2026)
            splits.assert_called_once_with(store.return_value)

    def test_failed_provider_is_not_silent_success(self):
        url = "postgresql://user@ep-example.neon.tech/neondb"
        with patch.dict(os.environ, {"DATABASE_URL": url}, clear=True), \
             patch.object(refresh_nfl, "inspect_existing_pool", return_value=2026), \
             patch.object(refresh_nfl, "Store") as store, \
             patch.object(refresh_nfl, "refresh_espn", return_value=False), \
             patch.object(refresh_nfl, "refresh_ticket_percentages") as splits:
            with self.assertRaises(RuntimeError):
                refresh_nfl.update()
            splits.assert_not_called()
            self.assertFalse(store.call_args.kwargs["demo_mode"])

    def test_custom_feed_only_if_https(self):
        url = "postgresql://user@ep-example.neon.tech/neondb"
        with patch.dict(os.environ, {"DATABASE_URL": url, "NFL_FEED_URL": "http://unsafe.example/feed"}, clear=True), \
             patch.object(refresh_nfl, "inspect_existing_pool", return_value=2026), \
             patch.object(refresh_nfl, "Store"), \
             patch.object(refresh_nfl, "refresh") as custom:
            with self.assertRaises(RuntimeError):
                refresh_nfl.update()
            custom.assert_not_called()

    def test_workflow_requires_explicit_opt_in_and_avoids_pr_secrets(self):
        from pathlib import Path
        workflow=(Path(__file__).resolve().parents[1] / ".github/workflows/nfl-refresh.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("schedule:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("vars.NFL_REFRESH_ENABLED == 'true'", workflow)
        self.assertIn("secrets.NFL_REFRESH_DATABASE_URL", workflow)
        self.assertIn("cancel-in-progress: false", workflow)


if __name__ == "__main__":
    unittest.main()
