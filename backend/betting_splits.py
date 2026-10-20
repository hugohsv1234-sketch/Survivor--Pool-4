"""Best-effort public NFL ticket percentages; never implied probabilities.

DraftKings Network publicly publishes '% Bets' for MONEYLINE outcomes, which
means the share of betting tickets for each outright winner. Their webpage
is not an official public API and may change or limit access at any time.
Missing numbers must not be guessed or derived from Moneyline odds.
"""
from datetime import datetime
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import re
import time

SOURCE_URL = "https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/"
NFL_SPLITS_URL = SOURCE_URL + "?tb_eg=NFL&tb_emt=Moneyline&tb_edate=n7days&tb_page={page}"
NEW_YORK = ZoneInfo("America/New_York")
TICKER_INTERVAL = 30 * 60
DISPLAY_MAX_AGE = 90 * 60

# Exact public team names as used by the sportsbook's NFL ticket splits page.
TEAM_NAMES = {
    "ARI": ("ARI Cardinals",), "ATL": ("ATL Falcons",),
    "BAL": ("BAL Ravens",), "BUF": ("BUF Bills",),
    "CAR": ("CAR Panthers",), "CHI": ("CHI Bears",),
    "CIN": ("CIN Bengals",), "CLE": ("CLE Browns",),
    "DAL": ("DAL Cowboys",), "DEN": ("DEN Broncos",),
    "DET": ("DET Lions",), "GB": ("GB Packers",),
    "HOU": ("HOU Texans",), "IND": ("IND Colts",),
    "JAX": ("JAX Jaguars", "JAC Jaguars"), "KC": ("KC Chiefs",),
    "LV": ("LV Raiders",), "LAC": ("LA Chargers", "LAC Chargers"),
    "LAR": ("LA Rams", "LAR Rams"), "MIA": ("MIA Dolphins",),
    "MIN": ("MIN Vikings",), "NE": ("NE Patriots",),
    "NO": ("NO Saints",), "NYG": ("NY Giants", "NYG Giants"),
    "NYJ": ("NY Jets", "NYJ Jets"), "PHI": ("PHI Eagles",),
    "PIT": ("PIT Steelers",), "SF": ("SF 49ers",),
    "SEA": ("SEA Seahawks",), "TB": ("TB Buccaneers",),
    "TEN": ("TEN Titans",), "WAS": ("WAS Commanders", "WSH Commanders"),
}
ALIAS = {re.sub(r"\s+", " ", name).casefold(): code
         for code, names in TEAM_NAMES.items() for name in names}
PERCENT = re.compile(r"^(100|[0-9]{1,2})%$")
DATE = re.compile(r"\b(1[0-2]|[1-9])/([1-9]|[12][0-9]|3[01])\b")


class _TextTokens(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens = []

    def handle_data(self, data):
        for part in data.splitlines():
            value = " ".join(part.split())
            if value:
                self.tokens.append(value)


def _team(token):
    return ALIAS.get(" ".join(token.split()).casefold())


def _heading(tokens, i):
    # Supports headings rendered as one text node or multiple nested spans.
    for n in (1, 2, 3):
        chunk = " ".join(tokens[i:i+n])
        if " @ " not in chunk:
            continue
        a, h = chunk.split(" @ ", 1)
        away, home = _team(a), _team(h)
        if away and home and away != home:
            return away, home, n
    return None


def _bet_percent(tokens, start, stop, team):
    for i in range(start, stop):
        if _team(tokens[i]) != team:
            continue
        numbers = []
        for candidate in tokens[i+1:min(i+9, stop)]:
            if candidate in ("Spread", "Total", "Moneyline"):
                break
            if _team(candidate):
                break
            matched = PERCENT.fullmatch(candidate)
            if matched:
                numbers.append(int(matched.group(1)))
                if len(numbers) >= 2:
                    return numbers[1]  # '% Bets', not '% Handle'
    return None


def parse_ticket_percentages(html):
    """Return {(away,home,month,day): {away:x, home:y}}.

    Don't accept non-moneyline percentages, incomplete rows or a mismatched
    matchup. A missing or reordered format should produce no result, not
    incorrect data.
    """
    if not isinstance(html, str):
        raise ValueError("Text expected")
    parser = _TextTokens()
    parser.feed(html)
    tokens = parser.tokens
    headers = []
    i = 0
    while i < len(tokens):
        found = _heading(tokens, i)
        if found:
            away, home, length = found
            headers.append((i, away, home))
            i += length
        else:
            i += 1
    data = {}
    for index, (start, away, home) in enumerate(headers):
        end = headers[index+1][0] if index+1 < len(headers) else len(tokens)
        block = tokens[start:end]
        when = next((DATE.search(t) for t in block[:12] if DATE.search(t)), None)
        if not when:
            continue
        try:
            moneyline = block.index("Moneyline")
            spread = block.index("Spread", moneyline+1)
        except ValueError:
            spread = len(block)
            try:
                moneyline = block.index("Moneyline")
            except ValueError:
                continue
        away_pct = _bet_percent(block, moneyline+1, spread, away)
        home_pct = _bet_percent(block, moneyline+1, spread, home)
        if away_pct is None or home_pct is None:
            continue
        # One-percent rounding discrepancies can occur; larger errors signal
        # changed site markup or incorrect row parsing.
        if abs(away_pct + home_pct - 100) > 2:
            continue
        key = (away, home, int(when.group(1)), int(when.group(2)))
        data[key] = {away: away_pct, home: home_pct}
    return data


def _fetch_page(page):
    if page not in (1, 2):
        raise ValueError("Page outside permitted range")
    url = NFL_SPLITS_URL.format(page=page)
    req = Request(url, headers={
        "Accept": "text/html",
        "User-Agent": "Mozilla/5.0 (compatible; SurvivorPool/1.0; NFL splits display)"
    })
    with urlopen(req, timeout=6) as response:
        if response.status != 200:
            raise ValueError("No public splits response")
        data = response.read(1_600_001)
    if len(data) > 1_600_000:
        raise ValueError("Splits page too large")
    return data.decode("utf-8", "replace")


def refresh_ticket_percentages(store):
    """Run from the existing server poll thread, max once every 30 minutes.

    Fetch errors are non-fatal and leave all NFL schedules and pool picks alone.
    """
    now = time.time()
    with store.transaction() as db:
        settings = store.settings(db)
        prev = settings.get("public_bet_splits_attempt") or 0
        if isinstance(prev, (float, int)) and 0 <= now - prev < TICKER_INTERVAL:
            return False
        store.set(db, "public_bet_splits_attempt", now)
    try:
        published = {}
        for page in (1, 2):
            try:
                published.update(parse_ticket_percentages(_fetch_page(page)))
            except (ValueError, OSError, TimeoutError, UnicodeError) as exc:
                print(f"Public ticket percentages unavailable (page {page}): {exc}", flush=True)
        if not published:
            return False
        results = {}
        with store.connect() as db:
            settings = store.settings(db)
            season = settings["season"]
            games = list(db.execute(
                "SELECT id,away,home,kickoff,season FROM games WHERE season=?",
                (season,)))
        for game in games:
            local = datetime.fromtimestamp(game["kickoff"], NEW_YORK)
            key = (game["away"], game["home"], local.month, local.day)
            split = published.get(key)
            if split is not None:
                results[game["id"]] = {
                    "percent": split, "updated_at": now, "source": "DraftKings"
                }
        with store.transaction() as db:
            store.set(db, "public_bet_splits", results)
        return bool(results)
    except Exception as exc:
        print(f"Public ticket percentages temporarily unavailable: {exc}", flush=True)
        return False
