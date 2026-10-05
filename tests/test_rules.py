"""Deterministic domain tests: run python3 -m unittest discover -s tests -v."""
import unittest
from backend.rules import RuleError, limits, outcome, started, statistics, validate_pick


def game(gid="g5", week=5, away="BAL", home="CIN", kickoff=1000, status="scheduled", season=2026):
    return dict(id=gid, week=week, season=season, away=away, home=home,
                kickoff=kickoff, status=status, away_score=None, home_score=None, started_at=None)


def pick(g, team, locked_at=None):
    return dict(week=g["week"], season=g["season"], game_id=g["id"], team=team, locked_at=locked_at)


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.current = game()
        self.games = {self.current["id"]: self.current}
        self.picks = []

    def validate(self, team="BAL", **options):
        args = dict(game=self.current, team=team, current_week=5, season=2026,
                    picks=self.picks, games=self.games, now=999.999)
        args.update(options)
        validate_pick(**args)

    def add_past(self, week, team, rival):
        g = game(f"g{week}", week, team, rival, 100, "final")
        g.update(away_score=27, home_score=20)
        self.games[g["id"]] = g
        self.picks.append(pick(g, team, 100))

    def test_before_kickoff_allowed(self):
        self.validate()

    def test_exact_kickoff_blocked(self):
        with self.assertRaisesRegex(RuleError, "bereits begonnen"):
            self.validate(now=1000)

    def test_live_before_scheduled_time_blocked(self):
        self.current["status"] = "live"
        with self.assertRaises(RuleError):
            self.validate()

    def test_actual_started_at_blocks_scheduled_status(self):
        self.current["started_at"] = 800
        self.assertTrue(started(self.current, 900))

    def test_postponed_does_not_start_by_old_schedule(self):
        self.current["status"] = "postponed"
        self.assertFalse(started(self.current, 2000))
        with self.assertRaisesRegex(RuleError, "keine Tipps"):
            self.validate()

    def test_changing_locked_pick_to_later_game_is_blocked(self):
        self.picks = [pick(self.current, "BAL")]
        later = game("late", away="SF", home="SEA", kickoff=5000)
        self.games[later["id"]] = later
        with self.assertRaisesRegex(RuleError, "gesperrt"):
            self.validate(game=later, team="SF", now=1000)

    def test_persisted_lock_survives_reschedule(self):
        self.picks = [pick(self.current, "BAL", 800)]
        self.current["kickoff"] = 9000
        with self.assertRaisesRegex(RuleError, "gesperrt"):
            self.validate(team="CIN")

    def test_team_reuse_is_blocked(self):
        self.add_past(1, "BAL", "NE")
        with self.assertRaisesRegex(RuleError, "bereits verwendet"):
            self.validate()

    def test_three_against_allowed_fourth_blocked(self):
        for week, team in enumerate(("KC", "BUF"), 1):
            self.add_past(week, team, "CIN")
        self.validate()
        self.add_past(3, "PHI", "CIN")
        with self.assertRaisesRegex(RuleError, "dreimal"):
            self.validate()

    def test_three_against_does_not_block_team_itself(self):
        for week, team in enumerate(("KC", "BUF", "PHI"), 1):
            self.add_past(week, team, "CIN")
        self.validate(team="CIN")

    def test_replacement_releases_own_team_and_opponent_count(self):
        self.add_past(1, "KC", "CIN")
        self.add_past(2, "BUF", "CIN")
        self.picks.append(pick(self.current, "BAL"))
        self.validate()
        self.validate(team="CIN")
        used, against = limits(self.picks, self.games, 5)
        self.assertNotIn("BAL", used)
        self.assertEqual(against["CIN"], 2)

    def test_foreign_team_future_week_and_wrong_season(self):
        with self.assertRaises(RuleError):
            self.validate(team="KC")
        with self.assertRaises(RuleError):
            self.validate(current_week=4)
        with self.assertRaises(RuleError):
            self.validate(season=2025)

    def test_playoff_reuse_same_season_blocked(self):
        self.add_past(1, "BAL", "NE")
        self.current["week"] = 22
        with self.assertRaisesRegex(RuleError, "bereits verwendet"):
            self.validate(current_week=22)

    def test_scores_ignored_before_final(self):
        self.current.update(away_score=24, home_score=10, status="live")
        self.assertEqual(outcome(pick(self.current, "BAL"), self.current), "pending")

    def test_win_loss_tie_and_zero_scores(self):
        self.current.update(away_score=0, home_score=3, status="final")
        self.assertEqual(outcome(pick(self.current, "BAL"), self.current), "loss")
        self.assertEqual(outcome(pick(self.current, "CIN"), self.current), "win")
        self.current.update(away_score=0, home_score=0)
        self.assertEqual(outcome(pick(self.current, "CIN"), self.current), "loss")
        self.assertEqual(outcome(pick(self.current, "CIN"), self.current, False), "push")
        self.current.update(home_score=None)
        self.assertEqual(outcome(pick(self.current, "CIN"), self.current), "pending")

    def test_neutral_tie_retains_survivor_without_awarding_win(self):
        self.current.update(away_score=24, home_score=24, status="final")
        stats = statistics([pick(self.current, "BAL")], self.games, False)
        self.assertEqual((stats["wins"], stats["losses"], stats["pushes"], stats["rate"], stats["survivor"]), (0, 0, 1, 0, True))

    def test_strict_elimination_can_block_further_picks(self):
        self.add_past(1, "KC", "NE")
        self.games["g1"].update(home_score=30)
        self.validate()
        with self.assertRaisesRegex(RuleError, "ausgeschieden"):
            self.validate(allow_after_elimination=False)
