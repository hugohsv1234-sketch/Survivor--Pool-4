"""The server is authoritative. All times are UTC Unix seconds.

A replacement excludes the old pick from both season limits. The old pick's
kickoff is checked BEFORE the candidate, so a later game cannot unlock a pick.
"""
from collections import Counter


class RuleError(Exception):
    def __init__(self, message, status=400, code="invalid"):
        super().__init__(message)
        self.status, self.code = status, code


def opponent(game, team):
    if team not in (game["home"], game["away"]):
        raise RuleError("Dieses Team spielt nicht in dieser Begegnung.")
    return game["away"] if team == game["home"] else game["home"]


def started(game, now):
    return (game["status"] in ("live", "final") or game.get("started_at") is not None
            or (game["status"] == "scheduled" and game["kickoff"] <= now))


def outcome(pick, game, tie_is_loss=True):
    if game["status"] != "final":
        return "pending"
    home, away = game["home_score"], game["away_score"]
    if home is None or away is None:
        return "pending"
    if home == away:
        return "loss" if tie_is_loss else "push"
    winner = game["home"] if home > away else game["away"]
    return "win" if pick["team"] == winner else "loss"


def limits(picks, games, excluded_week=None):
    others = [p for p in picks if p["week"] != excluded_week]
    used = {p["team"] for p in others}
    against = Counter(opponent(games[p["game_id"]], p["team"]) for p in others)
    return used, against


def validate_pick(*, game, team, current_week, season, picks, games, now,
                  allow_after_elimination=True, tie_is_loss=True):
    if game["season"] != season or game["week"] != current_week:
        raise RuleError("Tipps sind nur für den aktuellen Spieltag möglich.", 409, "week")
    opponent_id = opponent(game, team)
    existing = next((p for p in picks if p["week"] == current_week), None)
    if existing and (existing["locked_at"] is not None or started(games[existing["game_id"]], now)):
        raise RuleError("Dein Tipp ist seit dem Kickoff gesperrt.", 409, "locked")
    if started(game, now):
        raise RuleError("Dieses Spiel hat bereits begonnen. Kein Tipp mehr möglich.", 409, "started")
    if game["status"] != "scheduled":
        raise RuleError("Für dieses Spiel sind aktuell keine Tipps möglich.", 409, "unavailable")
    if not allow_after_elimination and any(outcome(p, games[p["game_id"]], tie_is_loss) == "loss" for p in picks):
        raise RuleError("Du bist ausgeschieden. Weitere Tipps sind deaktiviert.", 409, "eliminated")
    used, against = limits(picks, games, current_week)
    if team in used:
        raise RuleError("Du hast dieses Team bereits verwendet.", 409, "used")
    if against[opponent_id] >= 3:
        raise RuleError("Du hast bereits dreimal gegen dieses Team gesetzt.", 409, "against")


def statistics(picks, games, tie_is_loss=True):
    results = [outcome(p, games[p["game_id"]], tie_is_loss) for p in picks]
    wins, losses = results.count("win"), results.count("loss")
    return {"wins": wins, "losses": losses, "total": len(picks),
            "pending": results.count("pending"), "pushes": results.count("push"),
            "rate": round(100 * wins / (wins + losses)) if wins + losses else 0,
            "survivor": losses == 0}
