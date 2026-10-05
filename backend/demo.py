"""Deliberately fictional fixtures, dates and scores, never a live NFL feed."""
TEAMS = [
    ("ARI", "Arizona", "Cardinals", "#C9374C"), ("ATL", "Atlanta", "Falcons", "#E34855"),
    ("BAL", "Baltimore", "Ravens", "#9B83E9"), ("BUF", "Buffalo", "Bills", "#599AFF"),
    ("CAR", "Carolina", "Panthers", "#32B1E9"), ("CHI", "Chicago", "Bears", "#F58B51"),
    ("CIN", "Cincinnati", "Bengals", "#FF8A4C"), ("CLE", "Cleveland", "Browns", "#EC945D"),
    ("DAL", "Dallas", "Cowboys", "#A2B5D5"), ("DEN", "Denver", "Broncos", "#FF945C"),
    ("DET", "Detroit", "Lions", "#5AB8F2"), ("GB", "Green Bay", "Packers", "#E9C45A"),
    ("HOU", "Houston", "Texans", "#E96574"), ("IND", "Indianapolis", "Colts", "#669DE9"),
    ("JAX", "Jacksonville", "Jaguars", "#55C8C2"), ("KC", "Kansas City", "Chiefs", "#F26977"),
    ("LV", "Las Vegas", "Raiders", "#B9C2CD"), ("LAC", "Los Angeles", "Chargers", "#72CCF5"),
    ("LAR", "Los Angeles", "Rams", "#F4CB50"), ("MIA", "Miami", "Dolphins", "#5ED1CB"),
    ("MIN", "Minnesota", "Vikings", "#C29AF6"), ("NE", "New England", "Patriots", "#B2BEE2"),
    ("NO", "New Orleans", "Saints", "#D9CBA3"), ("NYG", "New York", "Giants", "#7B9DF6"),
    ("NYJ", "New York", "Jets", "#65C3A2"), ("PHI", "Philadelphia", "Eagles", "#57BFB1"),
    ("PIT", "Pittsburgh", "Steelers", "#F6CE62"), ("SF", "San Francisco", "49ers", "#E96870"),
    ("SEA", "Seattle", "Seahawks", "#9BC96A"), ("TB", "Tampa Bay", "Buccaneers", "#F16D6A"),
    ("TEN", "Tennessee", "Titans", "#72BDE3"), ("WAS", "Washington", "Commanders", "#DBAF71")
]


def week_name(week):
    return {19: "Wild Card", 20: "Divisional", 21: "Conference", 22: "Super Bowl"}.get(week, f"Week {week}")


def seed(db, now, password_hash):
    season = 2026
    for tid, city, name, color in TEAMS:
        db.execute("INSERT INTO teams VALUES(?,?,?,?,?,?)", (tid, city, name, f"{city} {name}", color, None))
    config = {"season": season, "current_week": 5, "clock_offset": 0,
              "tie_is_loss": True, "allow_after_elimination": True,
              "missing_pick_eliminates": True, "provider_error": None,
              "last_sync": now, "source": "demo"}
    import json
    for key, value in config.items():
        db.execute("INSERT INTO settings VALUES(?,?)", (key, json.dumps(value)))
    ids = [t[0] for t in TEAMS]
    forced = {1: [("KC", "NE")], 2: [("BUF", "NE")],
              3: [("PHI", "NE")], 4: [("DET", "GB")],
              5: [("BAL", "CIN"), ("BUF", "KC"), ("NE", "MIA"),
                  ("SF", "SEA"), ("DET", "DAL"), ("PHI", "LAR")]}
    for week in range(1, 23):
        pairs = forced.get(week, []).copy()
        paired = {t for pair in pairs for t in pair}
        remaining = [tid for tid in ids[week % 32:] + ids[:week % 32] if tid not in paired]
        pairs += list(zip(remaining[::2], remaining[1::2]))
        count = {19: 6, 20: 4, 21: 2, 22: 1}.get(week, 16)
        for index, (away, home) in enumerate(pairs[:count]):
            kickoff = int(now // 60 * 60) + 7200 + (week - 5) * 604800 + (index // 6) * 14400
            status = "final" if week < 5 else "scheduled"
            a, h = ((28, 17) if index % 2 == 0 else (20, 24)) if week < 5 else (None, None)
            db.execute("INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (f"d{season}-{week}-{index}", season, week, away, home, kickoff, status, a, h, None))
    names = [("max", "Max", "admin"), ("lea", "Lea", "player"), ("tim", "Tim", "player"),
             ("nina", "Nina", "player"), ("finn", "Finn", "player"), ("ben", "Ben", "player")]
    for index, (username, display, role) in enumerate(names):
        user_id = db.execute("INSERT INTO users(username,display_name,password_hash,role,joined_week,created_at) VALUES(?,?,?,?,?,?)",
                             (username, display, password_hash, role, 1, now)).lastrowid
        used, against = set(), {}
        for week in range(1, 5):
            games = [dict(row) for row in db.execute("SELECT * FROM games WHERE week=? ORDER BY id", (week,))]
            preferred = {1: "KC", 2: "BUF", 3: "PHI", 4: "DET"}[week] if index == 0 else None
            candidate = None
            for game in games:
                winner = game["away"] if game["away_score"] > game["home_score"] else game["home"]
                loser = game["home"] if winner == game["away"] else game["away"]
                wish = winner if week <= max(1, 5 - index) else loser
                for team in ([preferred] if preferred else [wish]):
                    if team not in (game["away"], game["home"]) or team in used:
                        continue
                    rival = game["home"] if team == game["away"] else game["away"]
                    if against.get(rival, 0) < 3:
                        candidate = game, team, rival
                        break
                if candidate:
                    break
            if candidate:
                game, team, rival = candidate
                db.execute("INSERT INTO picks(user_id,season,week,game_id,team,created_at,updated_at,locked_at) VALUES(?,?,?,?,?,?,?,?)",
                           (user_id, season, week, game["id"], team, game["kickoff"] - 3600,
                            game["kickoff"] - 3600, game["kickoff"]))
                used.add(team)
                against[rival] = against.get(rival, 0) + 1
