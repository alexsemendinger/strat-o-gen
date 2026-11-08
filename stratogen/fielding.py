"""Fielding ratings (1 = gold glove, 5 = liability), Strat-O-Matic style.

Each player-position-season is rated against the regulars who played that
position that year in comparable leagues: z-scores of range factor and
fielding percentage, blended with position-appropriate weights (catchers
also use caught-stealing percentage). Small samples shrink toward
average — a 20-game cameo can't earn a 1 or a 5.

* Range factor is (PO + A) per game for position players, and per nine
  innings for pitchers (Pitching IPouts): per game it mostly measures
  innings per appearance, which rated every reliever a grade or two
  below the starters.
* Peer pools are league-aware: from 1901 the AL and NL (plus the 1914-15
  Federal League) form one pool; every other league — the 19th-century
  majors, each Negro league, the independents — is its own pool, widened
  to the year's comparable leagues when it has too few regulars. Negro-
  league box scores credit far fewer chances, so mixing them with MLB rated
  every Negro-league fielder a grade worse.
* Stats a season didn't record (PO/A/E for 1925 NNL/ECL) are skipped,
  not read as zeros; with nothing recorded the rating comes from the two
  prior seasons, else the neutral 3 (see unrecorded_positions).

The z -> 1-5 mapping and the blend weights are calibrated against every
range rating printed on the real cards: the 14 plain-text fixtures and
both sides of the 23 dated JSON transcriptions (tests/test_fielding.py
reports the agreement, including leave-one-out). Expect occasional ±1
disagreement with official cards: single-season fielding stats are noisy
and biased by team context (strikeout staffs depress range factors, parks
differ), and SOM's raters also use scouting judgment that box-score stats
can't reconstruct.
"""

from __future__ import annotations

import threading
import weakref

from .lahman import MAJOR_LEAGUES, MODERN_MAJOR_LEAGUES, LahmanDB

# Blend weights per position: (range factor, fielding pct, caught-stealing)
_WEIGHTS = {
    "P":  (0.45, 0.55, 0.0),
    "C":  (0.15, 0.40, 0.45),
    "1B": (0.30, 0.70, 0.0),
    "2B": (0.60, 0.40, 0.0),
    "3B": (0.60, 0.40, 0.0),
    "SS": (0.60, 0.40, 0.0),
    "LF": (0.65, 0.35, 0.0),
    "CF": (0.65, 0.35, 0.0),
    "RF": (0.65, 0.35, 0.0),
    "OF": (0.65, 0.35, 0.0),
}

# Shrink z-scores by g/(g + _SHRINK_GAMES) so partial seasons drift to
# average. Pitchers count nine-inning games (IPouts / 27), so a 70-game
# reliever with 70 innings is a small sample, not a full season.
_SHRINK_GAMES = 12
_SHRINK_GAMES_P = 12

# Cap per-metric z-scores: a couple of errors in a 25-chance sample
# shouldn't dominate the rating
_Z_CAP = 2.2

# z-score thresholds for ratings 1,2,3,4 (else 5). Pitchers' are 0.4
# lower: official cards rate most pitchers 2 (fitted on the 10 official
# pitcher ratings; see tests/test_fielding.py for in-sample and
# leave-one-out agreement).
_THRESHOLDS = (0.75, 0.28, -0.42, -1.05)
_P_THRESHOLD_SHIFT = -0.4
_THRESHOLDS_P = tuple(t + _P_THRESHOLD_SHIFT for t in _THRESHOLDS)

MIN_PEER_GAMES = 10    # peers below this don't define the league norm
_MIN_PEER_GAMES = MIN_PEER_GAMES   # old private name
MIN_POOL_PEERS = 6     # a league pool needs this many such peers

_CORNERS = ("LF", "CF", "RF")

# Current season counts fully; the two prior seasons lend stability the way
# official raters lean on reputation (a 3-error month doesn't make a butcher).
_RECENCY = (1.0, 0.7, 0.45)


def _weight(stats: dict, pos: str) -> float:
    """Sample size of a fielding line in games: nine-inning games for
    pitchers (their InnOuts come from Pitching), appearances otherwise."""
    if pos == "P":
        return (stats.get("InnOuts") or 0) / 27.0
    return float(stats.get("G") or 0)


def _metrics(stats: dict, pos: str = "") -> dict:
    """Rate stats of one fielding line; a metric is absent when the
    season didn't record what it needs."""
    g = stats.get("G") or 0
    if not g:
        return {}
    po, a, e = stats.get("PO"), stats.get("A"), stats.get("E")
    if po is None and a is None:
        return {}
    chances = (po or 0) + (a or 0)
    out = {}
    if pos == "P":
        outs = stats.get("InnOuts") or 0
        if outs > 0:
            out["rf"] = chances * 27.0 / outs
    else:
        out["rf"] = chances / g
    if e is not None and chances + e > 0:
        out["fp"] = chances / (chances + e)
    sb, cs = stats.get("SB"), stats.get("CS")
    if sb is not None and cs is not None and sb + cs >= 10:
        out["cs"] = cs / (sb + cs)
    return out


def peer_league_sets(db: LahmanDB, year: int, pos: str,
                     league: str | None) -> list[frozenset | None]:
    """Candidate peer pools for a player's league, narrowest first:
    his league group (AL+NL+FL from 1901, else his own league), then the
    year's comparable leagues (majors or non-majors), then everyone
    (None)."""
    present = db.fielding_leagues(year, pos)
    sets: list[frozenset | None] = []
    if league:
        if year >= 1901 and league in MODERN_MAJOR_LEAGUES:
            sets.append(frozenset(lg for lg in present
                                  if lg in MODERN_MAJOR_LEAGUES))
        else:
            sets.append(frozenset({league}))
        major = league in MAJOR_LEAGUES
        wider = frozenset(lg for lg in present if (lg in MAJOR_LEAGUES) == major)
        if wider not in sets:
            sets.append(wider)
    sets.append(None)
    return sets


_DIST_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_CACHE_LOCK = threading.Lock()


def _db_cache(db) -> dict:
    with _CACHE_LOCK:
        cache = _DIST_CACHE.get(db)
        if cache is None:
            cache = _DIST_CACHE[db] = {}
        return cache


def _distribution(peers: list[dict], pos: str) -> tuple[dict, int]:
    """(weighted mean/std of each metric, number of regulars)."""
    sums: dict[str, list[float]] = {}
    regulars = 0
    for stats in peers:
        if (stats.get("G") or 0) < MIN_PEER_GAMES:
            continue
        metrics = _metrics(stats, pos)
        if "rf" not in metrics:
            continue
        regulars += 1
        w = _weight(stats, pos)
        for name, value in metrics.items():
            entry = sums.setdefault(name, [0.0, 0.0, 0.0])  # w, wx, wx^2
            entry[0] += w
            entry[1] += w * value
            entry[2] += w * value * value
    dist = {}
    for name, (w, wx, wx2) in sums.items():
        if w <= 0:
            continue
        mean = wx / w
        var = max(0.0, wx2 / w - mean * mean)
        dist[name] = (mean, var ** 0.5)
    return dist, regulars


def _peer_distribution(db: LahmanDB, year: int, pos: str,
                       league: str | None = None) -> dict:
    """Weighted mean/std of each metric across the position's regulars in
    the narrowest comparable pool with MIN_POOL_PEERS regulars."""
    cache = _db_cache(db)
    key = (year, pos, league)
    if key in cache:
        return cache[key]
    dist: dict = {}
    for leagues in peer_league_sets(db, year, pos, league):
        dist, regulars = _distribution(db.fielding_peers(year, pos, leagues), pos)
        if regulars >= MIN_POOL_PEERS:
            break
    cache[key] = dist
    return dist


def _rated_position(lines: dict, pos: str) -> str:
    """The fielding line a position is rated on: a corner outfield spot
    the data doesn't split out (pre-1954 MLB) is rated on the combined
    'OF' line."""
    if (pos in _CORNERS and not (lines.get(pos) or {}).get("G")
            and not any(lines.get(c) for c in _CORNERS)
            and (lines.get("OF") or {}).get("G")):
        return "OF"
    return pos


def _season_z(db: LahmanDB, player_id: str, year: int,
              pos: str) -> tuple[float, float] | None:
    """(blended z-score, sample size in games) for one season at a
    position, or None when the season has nothing to rate."""
    lines = db.fielding_by_position(player_id, year)
    pos = _rated_position(lines, pos)
    stats = lines.get(pos)
    if not stats or not stats.get("G"):
        return None
    metrics = _metrics(stats, pos)
    dist = _peer_distribution(db, year, pos, stats.get("lg"))
    named = dict(zip(("rf", "fp", "cs"), _WEIGHTS.get(pos, (0.6, 0.4, 0.0))))
    z_total = 0.0
    w_total = 0.0
    for name, value in metrics.items():
        if name not in dist or named.get(name, 0.0) == 0.0:
            continue
        mean, std = dist[name]
        if std <= 1e-9:
            continue
        z = max(-_Z_CAP, min(_Z_CAP, (value - mean) / std))
        z_total += named[name] * z
        w_total += named[name]
    if w_total == 0:
        return None
    return z_total / w_total, _weight(stats, pos)


def rate_position(db: LahmanDB, player_id: str, year: int, pos: str) -> int | None:
    """Rating 1-5 at a position, or None if the player didn't play it.

    A corner outfield spot without split data that season is rated on the
    combined outfield line. When no season in the window recorded anything
    to rate (e.g. 1925 NNL with blank putouts and assists) the rating is
    the neutral 3.
    """
    lines = db.fielding_by_position(player_id, year)
    if not (lines.get(_rated_position(lines, pos)) or {}).get("G"):
        return None
    z_sum = 0.0
    w_sum = 0.0
    for offset, recency in enumerate(_RECENCY):
        season = _season_z(db, player_id, year - offset, pos)
        if season is None:
            continue
        z, games = season
        weight = games * recency
        z_sum += weight * z
        w_sum += weight
    if w_sum == 0:
        return 3
    z = z_sum / w_sum
    shrink = _SHRINK_GAMES_P if pos == "P" else _SHRINK_GAMES
    z *= w_sum / (w_sum + shrink)
    for rating, threshold in enumerate(
            _THRESHOLDS_P if pos == "P" else _THRESHOLDS, start=1):
        if z >= threshold:
            return rating
    return 5


def unrecorded_positions(db: LahmanDB, player_id: str, year: int) -> list[str]:
    """Positions whose season fielding line recorded no putouts or
    assists (1925 NNL/ECL): their rating leans on prior seasons or is the
    neutral 3, worth a warning on the card."""
    return [pos for pos, stats in db.fielding_by_position(player_id, year).items()
            if stats.get("G") and stats.get("PO") is None and stats.get("A") is None]


def position_ratings(db: LahmanDB, player_id: str, year: int,
                     max_positions: int | None = None,
                     ) -> list[tuple[str, int, int]]:
    """[(position, rating, games)] for the season, most games first.

    Every position played is listed, however briefly — a Strat-O-Matic
    player may only field the positions on his card, and real cards print
    one-game positions (Carter 1975 3b, Carey 1953 2b) and long lists
    (Linz 1963: six). `max_positions` caps the list when given. A position
    player's pitching cameo isn't listed: 'P' appears only when pitching
    is the player's most-played position (or his only one).
    """
    played = [(pos, g) for pos, g in db.positions(player_id, year)
              if pos not in ("PH", "PR") and g > 0]
    others = [g for pos, g in played if pos != "P"]
    if others:
        played = [(pos, g) for pos, g in played
                  if pos != "P" or g >= max(others)]
    if max_positions is not None:
        played = played[:max_positions]
    out = []
    for pos, g in played:
        rating = rate_position(db, player_id, year, pos)
        if rating is not None:
            out.append((pos, rating, g))
    return out
