"""Fielding ratings (1 = gold glove, 5 = liability), Strat-O-Matic style.

Each player-position-season is rated against everyone who played that
position that year: z-scores of range factor (PO+A per game) and fielding
percentage, blended with position-appropriate weights (catchers also use
caught-stealing percentage). Small samples shrink toward average — a
20-game cameo can't earn a 1 or a 5.

The z -> 1-5 mapping and the blend weights are calibrated against the ~18
position ratings printed on the real-card fixtures (Mays cf-1, Bonds lf-2,
Raines lf-2/cf-3/2b-4, Murray 1b-4, Carter c-3/3b-4, Ryan p-4, Colon p-1,
...). Expect occasional ±1 disagreement with official cards: single-season
fielding stats are noisy and biased by team context (strikeout staffs
depress range factors, parks differ), and SOM's raters also use scouting
judgment that box-score stats can't reconstruct.
"""

from __future__ import annotations

from .lahman import LahmanDB

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

# Shrink z-scores by g/(g + _SHRINK_GAMES) so partial seasons drift to average
_SHRINK_GAMES = 12

# Cap per-metric z-scores: a couple of errors in a 25-chance sample
# shouldn't dominate the rating
_Z_CAP = 2.2

# z-score thresholds for ratings 1,2,3,4 (else 5)
_THRESHOLDS = (0.75, 0.28, -0.42, -1.05)

_MIN_PEER_GAMES = 10   # peers below this don't define the league norm


def _metrics(stats: dict) -> dict:
    g = stats.get("G", 0)
    if not g:
        return {}
    chances = stats.get("PO", 0) + stats.get("A", 0)
    out = {"rf": chances / g}
    if chances + stats.get("E", 0) > 0:
        out["fp"] = chances / (chances + stats["E"])
    attempts = stats.get("SB", 0) + stats.get("CS", 0)
    if attempts >= 10:
        out["cs"] = stats.get("CS", 0) / attempts
    return out


_DIST_CACHE: dict[tuple[int, int, str], dict] = {}


def _peer_distribution(db: LahmanDB, year: int, pos: str) -> dict:
    """Weighted mean/std of each metric across the position's regulars."""
    cache_key = (id(db), year, pos)
    if cache_key in _DIST_CACHE:
        return _DIST_CACHE[cache_key]
    sums: dict[str, list[float]] = {}
    for stats in db.fielding_peers(year, pos):
        g = stats.get("G", 0)
        if g < _MIN_PEER_GAMES:
            continue
        for name, value in _metrics(stats).items():
            entry = sums.setdefault(name, [0.0, 0.0, 0.0])  # w, wx, wx^2
            entry[0] += g
            entry[1] += g * value
            entry[2] += g * value * value
    dist = {}
    for name, (w, wx, wx2) in sums.items():
        if w <= 0:
            continue
        mean = wx / w
        var = max(0.0, wx2 / w - mean * mean)
        dist[name] = (mean, var ** 0.5)
    _DIST_CACHE[cache_key] = dist
    return dist


# Current season counts fully; the two prior seasons lend stability the way
# official raters lean on reputation (a 3-error month doesn't make a butcher).
_RECENCY = (1.0, 0.7, 0.45)


def _season_z(db: LahmanDB, player_id: str, year: int,
              pos: str) -> tuple[float, int] | None:
    """(blended z-score, games) for one season at a position."""
    stats = db.fielding_by_position(player_id, year).get(pos)
    if not stats or not stats.get("G"):
        return None
    metrics = _metrics(stats)
    dist = _peer_distribution(db, year, pos)
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
    return z_total / w_total, stats["G"]


def rate_position(db: LahmanDB, player_id: str, year: int, pos: str) -> int | None:
    """Rating 1-5 at a position, or None if the player didn't play it."""
    if not db.fielding_by_position(player_id, year).get(pos, {}).get("G"):
        return None
    z_sum = 0.0
    w_sum = 0.0
    games_eff = 0.0
    for offset, recency in enumerate(_RECENCY):
        season = _season_z(db, player_id, year - offset, pos)
        if season is None:
            continue
        z, games = season
        weight = games * recency
        z_sum += weight * z
        w_sum += weight
        games_eff += weight
    if w_sum == 0:
        return 3
    z = z_sum / w_sum
    z *= games_eff / (games_eff + _SHRINK_GAMES)
    for rating, threshold in enumerate(_THRESHOLDS, start=1):
        if z >= threshold:
            return rating
    return 5


def position_ratings(db: LahmanDB, player_id: str, year: int,
                     max_positions: int = 3) -> list[tuple[str, int, int]]:
    """[(position, rating, games)] for the season, most games first.

    Cameo positions (under 5 games) are dropped unless nothing else
    remains; pitchers' P rating is included only when they actually
    pitched (for pitcher cards it's looked up separately).
    """
    played = [(pos, g) for pos, g in db.positions(player_id, year)
              if pos not in ("PH", "PR")]
    if not played:
        return []
    significant = [(pos, g) for pos, g in played if g >= 5] or played[:1]
    out = []
    for pos, g in significant[:max_positions]:
        rating = rate_position(db, player_id, year, pos)
        if rating is not None:
            out.append((pos, rating, g))
    return out
