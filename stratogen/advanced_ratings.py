"""Advanced-side card ratings (error, arm, catcher, bunting, hit & run,
pitcher hold / wp / bk / endurance), calibrated against real cards.

The advanced (6col) side of a Strat-O-Matic card prints more than the basic
side's 1-5 range ratings: per-position error ratings (`ss-1 e24`), outfield
and catcher arms (`cf-1(+2)`, `c-3(0)`), catcher throwing / passed-ball
ratings (`T-1-7(pb-4)`), bunting and hit-and-run letters, and for pitchers
error, hold, wild-pitch, balk, bunting and endurance ratings. Official
formulas are proprietary; everything here is reconstructed from the
Lahman data and fitted against the transcribed cards in
data/real_cards/transcriptions/ (official cards only; the four unofficial
dead-ball pitchers are weak evidence, the HOF composite Sewell and the
undated McDaniel are excluded).

What the cards revealed, in one line each (details in each docstring):

* **Error ratings are absolute, not peer-relative**: `eN` is about N errors
  per full season (154/162 nine-inning games) at that position. Pipp's
  ordinary-for-1921 16 errors print as e16; every official pitcher card
  satisfies e = E per (IP/9) x season games exactly (the four unofficial
  ones within one).
* Small samples at a *secondary* position are not given the benefit of the
  doubt: Linz (0 errors in 6 games at 2B) prints e41. Modeled as pooling
  the two prior seasons, then a floor of twice the league rate.
* Hit & run is a contact rating: strikeout rate relative to the league
  separates every official card. Bunting tracks sacrifice hits relative to
  the league, with a pseudo-count so a single bunt can't make a bunter.
* Pitcher wp/bk scale with wild pitches and balks per inning.
* Outfield arms only loosely follow assists (lower = stronger arm): strong
  arms deter runners instead of collecting assists, so the scale is
  anchored on the season's population of regulars rather than fitted to
  the six printed arms.

Ratings without a Lahman basis (pitcher hold — no stolen bases are charged
to pitchers in the data; the catcher T-rating; the closer suffix) are
reasoned priors, flagged as such in their docstrings and in the README.

Entry points: `advanced_batter_ratings` / `advanced_batter_header_lines`
and `advanced_pitcher_ratings` / `advanced_pitcher_header_lines`.
"""

from __future__ import annotations

import math
import re
import threading
import weakref

from . import fielding as _fielding
from . import ratings as _ratings
from .lahman import LahmanDB

# --- shared helpers ----------------------------------------------------------


def _round(x: float) -> int:
    """Round half up (Python's round() is banker's rounding)."""
    return int(math.floor(x + 0.5))


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def season_games(year: int, league: str | None = None) -> int:
    """Nominal schedule length the error ratings are scaled to.

    162 games from 1961 (AL) / 1962 (NL) on, otherwise 154. Strike- or
    pandemic-shortened seasons keep the nominal length (the 1994 Melido
    Perez card only fits at 162), and 19th-century seasons use 154 so an
    error rating stays a per-game *rate* comparable across eras.
    """
    if year >= 1962 or (year == 1961 and (league or "").upper() == "AL"):
        return 162
    return 154


def _pa(stats: dict) -> int:
    return sum(stats.get(k, 0) or 0 for k in ("AB", "BB", "HBP", "SH", "SF"))


_OF_CORNERS = ("LF", "CF", "RF")


def _tc(stats: dict) -> int:
    return (stats.get("PO", 0) or 0) + (stats.get("A", 0) or 0) + (stats.get("E", 0) or 0)


# --- fielding peer norms -----------------------------------------------------

# Per-database caches (weak keys: they die with the database).
_CACHES: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_PEER_LOCK = threading.Lock()


def _cache(db, name: str) -> dict:
    with _PEER_LOCK:
        caches = _CACHES.get(db)
        if caches is None:
            caches = _CACHES[db] = {}
        return caches.setdefault(name, {})


def _games_eq(stats: dict, tc_per_game: float) -> float:
    """Full nine-inning games a fielding line represents.

    Innings (InnOuts/27) when recorded. Otherwise appearances are capped
    by chance volume — a 40-game defensive sub with 85 chances played
    about 28 full games — using the regulars' chances per game.
    """
    inn = stats.get("InnOuts", 0) or 0
    if inn > 0:
        return inn / 27.0
    g = stats.get("G", 0) or 0
    tc = _tc(stats)
    if tc > 0 and tc_per_game > 0:
        return min(float(g), tc / tc_per_game)
    return 0.5 * g


def _peer_norms(db: LahmanDB, year: int, pos: str) -> dict:
    """League rates at a position for one season (both leagues pooled).

    Returns the peers' total full games and per-full-game rates of
    errors, assists and passed balls, the caught-stealing rate (None when
    not recorded), and the regulars' chances per game used to convert
    appearances into full games.
    Peers below fielding.MIN_PEER_GAMES games don't define the norm.
    """
    cache = _cache(db, "peers")
    key = (year, pos)
    if key in cache:
        return cache[key]
    peers = [p for p in db.fielding_peers(year, pos)
             if (p.get("G") or 0) >= _fielding.MIN_PEER_GAMES]
    out = {"tc_per_game": 0.0, "games": 0.0, "e_rate": 0.0, "a_rate": 0.0,
           "pb_rate": 0.0, "cs_pct": None, "steals_tracked": False}
    if peers:
        max_g = max(p["G"] for p in peers)
        regulars = [p for p in peers if p["G"] >= 0.6 * max_g] or peers
        reg_g = sum(p["G"] for p in regulars)
        out["tc_per_game"] = sum(_tc(p) for p in regulars) / reg_g if reg_g else 0.0
        games = sum(_games_eq(p, out["tc_per_game"]) for p in peers)
        out["games"] = games
        if games > 0:
            sb = sum(p.get("SB", 0) or 0 for p in peers)
            cs = sum(p.get("CS", 0) or 0 for p in peers)
            out["e_rate"] = sum(p.get("E", 0) or 0 for p in peers) / games
            out["a_rate"] = sum(p.get("A", 0) or 0 for p in peers) / games
            out["pb_rate"] = sum(p.get("PB", 0) or 0 for p in peers) / games
            out["steals_tracked"] = sb + cs > 0
            if sb + cs > 0:
                out["cs_pct"] = cs / (sb + cs)
    cache[key] = out
    return out


def _position_line(db: LahmanDB, player_id: str, year: int, pos: str) -> dict | None:
    """The player's fielding line at `pos`. 'OF' falls back to the sum of
    the corner splits when the combined row is absent."""
    lines = db.fielding_by_position(player_id, year)
    if pos in lines:
        return lines[pos]
    if pos == "OF":
        corners = [lines[p] for p in _OF_CORNERS if p in lines]
        if corners:
            total = {k: sum(c.get(k, 0) or 0 for c in corners)
                     for k in ("G", "GS", "InnOuts", "PO", "A", "E", "DP",
                               "PB", "SB", "CS")}
            total["lg"] = corners[0].get("lg", "?")
            return total
    return None


# --- error ratings -----------------------------------------------------------

# A season with fewer full games than this at a position is pooled with the
# two prior seasons; if still short, the cameo floor applies.
ERROR_POOL_GAMES = 15.0
# Cameo floor: an unproven fielder's rate is at least this multiple of the
# league rate (Linz 2B e41, Carey 2B e41, Linz OF e13 with zero errors).
ERROR_CAMEO_MULT = 2.0
# No rating exceeds this multiple of the league rate (Carey: 1 error in 2
# chances at SS prints e88, about 3x the 1953 league rate).
ERROR_CAP_MULT = 3.0
# Catchers: share of stolen-base attempts assumed to produce a throwing
# error that the card charges to the steal chart, not the e-rating.
CATCHER_THROW_ERRORS_PER_ATTEMPT = 0.055
# Caught-stealing per stolen base when no league in the season recorded CS
_DEFAULT_CS_PER_SB = 0.7


def _catcher_steal_attempts(db: LahmanDB, year: int, stats: dict,
                            games: float) -> float:
    """Steal attempts (SB + CS) against a catcher, recorded or estimated.

    When catcher SB/CS weren't recorded that season (Lahman: before 1890
    and 1949-1953), the league batting steals are spread over all catcher
    games, with caught-stealing scaled from the leagues that kept it.
    """
    norms = _peer_norms(db, year, "C")
    if norms["steals_tracked"]:
        return float((stats.get("SB", 0) or 0) + (stats.get("CS", 0) or 0))
    sb = sb_with_cs = cs = 0
    for lg in db.leagues_for_year(year):
        try:
            raw = db.league_batting(year, lg)["raw"]
        except KeyError:
            continue
        sb += raw.get("SB", 0) or 0
        if raw.get("CS"):
            sb_with_cs += raw.get("SB", 0) or 0
            cs += raw["CS"]
    cs_per_sb = cs / sb_with_cs if sb_with_cs else _DEFAULT_CS_PER_SB
    if not norms["games"]:
        return 0.0
    return sb * (1.0 + cs_per_sb) / norms["games"] * games


def _error_sample(db: LahmanDB, player_id: str, year: int,
                  pos: str) -> tuple[float, float] | None:
    """(errors, full games) for one season, catcher errors net of the
    estimated stolen-base throwing errors."""
    stats = _position_line(db, player_id, year, pos)
    if not stats or not stats.get("G"):
        return None
    norms = _peer_norms(db, year, pos)
    games = _games_eq(stats, norms["tc_per_game"])
    errors = float(stats.get("E", 0) or 0)
    if pos == "C":
        attempts = _catcher_steal_attempts(db, year, stats, games)
        errors = max(0.0, errors - CATCHER_THROW_ERRORS_PER_ATTEMPT * attempts)
    return errors, games


def error_rating(db: LahmanDB, player_id: str, year: int, pos: str) -> int | None:
    """Fielding error rating `eN` at a position (None if not played).

    Inputs: the Fielding row (E, G, InnOuts, PO+A) at `pos` for `year`,
    and the same-season league error rate at the position. Outfielders
    get one rating for all three spots (computed on the combined OF line,
    as every OF card prints a single e for lf/cf/rf). Pitchers delegate
    to `pitcher_error_rating`.

    Formula: e = round(errors per full game x season_games), where full
    games = InnOuts/27, or appearances capped by chances / the regulars'
    chances per game when innings weren't recorded. If the season gives
    fewer than ERROR_POOL_GAMES (15) full games, the two prior seasons at
    the position are pooled in; if still short, the rate is floored at
    ERROR_CAMEO_MULT (2x) the league rate. Every rate is capped at
    ERROR_CAP_MULT (3x) the league rate. Catchers first subtract
    CATCHER_THROW_ERRORS_PER_ATTEMPT (0.055) errors per steal attempt
    against them (estimated from league steals when catcher SB/CS weren't
    recorded): the card evidently charges those throwing errors
    elsewhere — without this Posada's 6 errors would print e8, not e1.

    Fitted on 19 official ratings (Benintendi, Carey x3, Combs,
    Henderson, Judge, LeMahieu x3, Linz x4, Pipp, Rizzuto, Strawberry,
    Posada, Silvera; a player's outfield e counts once). The per-season
    scale is not fitted — it is the natural "errors per full season"
    unit, and it reproduces the regulars to within a point (Henderson e7,
    Strawberry e3, Pipp e16, LeMahieu 2b e4 / 3b e29, Benintendi and
    Judge e0). The pool length and the cameo and cap multiples were set
    from the six cameo positions; the catcher constant from Posada
    (Silvera validates it within one). Agreement: 11/19 exact, 16/19
    within one, all 19 within three (Linz ss 32 vs 29, Carey ss 91 vs 88).
    """
    pos = pos.upper()
    if pos == "P":
        return pitcher_error_rating(db, player_id, year)
    key = "OF" if pos in _OF_CORNERS + ("OF",) else pos
    current = _error_sample(db, player_id, year, key)
    if current is None:
        return None
    stats = _position_line(db, player_id, year, key)
    league = stats.get("lg", "?")
    errors, games = current
    if games < ERROR_POOL_GAMES:
        for offset in (1, 2):
            prior = _error_sample(db, player_id, year - offset, key)
            if prior is not None:
                errors += prior[0]
                games += prior[1]
    rate = errors / games if games > 0 else 0.0
    lg_rate = _peer_norms(db, year, key)["e_rate"]
    if lg_rate > 0:
        if games < ERROR_POOL_GAMES:
            rate = max(rate, ERROR_CAMEO_MULT * lg_rate)
        rate = min(rate, ERROR_CAP_MULT * lg_rate)
    return _clamp(_round(rate * season_games(year, league)), 0, 99)


def pitcher_error_rating(db: LahmanDB, player_id: str, year: int) -> int | None:
    """Pitcher error rating `eN` (None if he didn't pitch).

    Inputs: pitcher-fielding errors (Fielding, POS='P') and innings
    pitched (Pitching IPouts). Formula: e = round(E / (IP/9) x
    season_games), capped at ERROR_CAP_MULT x the league pitcher rate.
    No small-sample floor: the 29- and 34-inning relievers Gibson and
    Bruney (0 errors) print e0, so — unlike out-of-position cameos —
    pitchers are not penalized for limited innings.

    Nothing fitted beyond the season-length unit shared with
    `error_rating`. Agreement: all 7 official pitcher cards exact
    (e0 x4, Capuano e15, Perez e10, Monroe e24); the 4 unofficial
    dead-ball cards land within one (Orth 33 vs 34, Shawkey 23 vs 24,
    Warhop 45 vs 46, Zuber 11 exact) — they fit a 162-game unit, the
    official 1958 Monroe card fits 154.
    """
    pitching = db.pitching_season(player_id, year)
    if not pitching:
        return None
    fld = db.fielding_by_position(player_id, year).get("P", {})
    errors = fld.get("E", 0) or 0
    ip = pitching.get("IP", 0.0) or 0.0
    if ip <= 0:
        ip = (fld.get("InnOuts", 0) or 0) / 3.0
    if ip <= 0:
        return 0 if errors == 0 else 99
    rate = errors / (ip / 9.0)
    lg_rate = _pitcher_league_error_rate(db, year)
    if lg_rate > 0:
        rate = min(rate, ERROR_CAP_MULT * lg_rate)
    return _clamp(_round(rate * season_games(year, pitching.get("league"))), 0, 99)


def _pitcher_league_error_rate(db: LahmanDB, year: int) -> float:
    """League pitcher errors per nine innings fielded."""
    peers = [p for p in db.fielding_peers(year, "P")
             if (p.get("InnOuts") or 0) > 0]
    inn = sum(p["InnOuts"] for p in peers)
    return sum(p.get("E", 0) or 0 for p in peers) / (inn / 27.0) if inn else 0.0


# --- arms, catcher detail ----------------------------------------------------

# Outfield arm: arm = round(-ARM_SLOPE x z), z = standardized log assist
# ratio among the season's regular outfielders.
ARM_SLOPE = 1.75
ARM_PSEUDO_ASSISTS = 2.0     # shrinkage toward the league rate
ARM_RANGE = (-6, 5)


def _outfield_spots(db: LahmanDB, year: int) -> tuple[str, ...]:
    """LF/CF/RF when the season has the splits (1891+), else OF."""
    if any(db.fielding_peers(year, p) for p in _OF_CORNERS):
        return _OF_CORNERS
    return ("OF",)


def _assists_vs_expected(db: LahmanDB, year: int,
                         lines: dict[str, dict]) -> tuple[float, float]:
    """(assists, expected assists) over a player's outfield spots, each
    spot's games at that spot's league assist rate."""
    actual = expected = 0.0
    for pos, stats in lines.items():
        norms = _peer_norms(db, year, pos)
        actual += stats.get("A", 0) or 0
        expected += _games_eq(stats, norms["tc_per_game"]) * norms["a_rate"]
    return actual, expected


def _log_assist_ratio(actual: float, expected: float) -> float:
    return math.log((actual + ARM_PSEUDO_ASSISTS) / (expected + ARM_PSEUDO_ASSISTS))


def _arm_population(db: LahmanDB, year: int) -> tuple[float, float]:
    """(mean, sd) of the log assist ratio among the season's regular
    outfielders: at each spot, those with 60%+ of the busiest fielder's
    games there, each against that spot's assist rate."""
    cache = _cache(db, "arms")
    if year in cache:
        return cache[year]
    xs = []
    for pos in _outfield_spots(db, year):
        peers = [p for p in db.fielding_peers(year, pos)
                 if (p.get("G") or 0) >= _fielding.MIN_PEER_GAMES]
        if not peers:
            continue
        max_g = max(p["G"] for p in peers)
        regulars = [p for p in peers if p["G"] >= 0.6 * max_g]
        xs += [_log_assist_ratio(*_assists_vs_expected(db, year, {pos: p}))
               for p in regulars]
    result = (0.0, 0.0)
    if len(xs) >= 3:
        mean = sum(xs) / len(xs)
        sd = (sum((x - mean) ** 2 for x in xs) / len(xs)) ** 0.5
        result = (mean, sd)
    cache[year] = result
    return result


def outfield_arm(db: LahmanDB, player_id: str, year: int) -> int | None:
    """Outfield arm rating (the `(+2)` in `cf-1(+2)`); lower = stronger.

    Inputs: the player's combined-outfield assists and full games, the
    season's league outfield assists per game, and the spread of that
    ratio among the season's regular outfielders. Formula: x = ln((A + 2)
    / (expected A + 2)) — 2 pseudo-assists at the league rate, so a
    cameo drifts to average — z = (x - regulars' mean) / regulars' sd,
    arm = round(-1.75 x z), clamped to -6..+5. By construction the median
    regular is 0, most regulars fall in -3..+3 and about 1% reach the
    extremes. Each spot is compared with its own league rate (a right
    fielder with right fielders).

    Fitted on 6 official arms (Henderson +2, Judge -4, Strawberry -2,
    Linz +2, Combs +3, Benintendi 0): only the slope, chosen under the
    constraint that the population of regulars stays centered with at
    most 10% at the extremes. (Unconstrained fits to these six reach 5/6
    within one but rate a third of all regulars -6: all four regulars'
    cards sit below the median in assists yet carry average-to-strong
    arms.) Agreement: 2/6 exact, 4/6 within one; Judge (0 vs -4) and
    Strawberry (+1 vs -2) have strong arms that deterred runners rather
    than collecting assists, which box scores can't see.
    Leave-one-out: 1/6 exact, 4/6 within one. The weakest-grounded
    measured rating here.
    """
    all_lines = db.fielding_by_position(player_id, year)
    lines = {p: all_lines[p] for p in _OF_CORNERS
             if (all_lines.get(p) or {}).get("G")}
    if not lines and (all_lines.get("OF") or {}).get("G"):
        lines = {"OF": all_lines["OF"]}
    if not lines:
        return None
    mean, sd = _arm_population(db, year)
    if sd <= 1e-9:
        return 0
    z = (_log_assist_ratio(*_assists_vs_expected(db, year, lines)) - mean) / sd
    return _clamp(_round(-ARM_SLOPE * z), *ARM_RANGE)


# Catcher arm: shrunk caught-stealing ratio (vs league CS%) or, when steals
# weren't recorded, assists-per-game ratio; arm = round(slope x (1 - r)).
CATCHER_ARM_SLOPE = 6.0
CATCHER_ARM_PSEUDO_ATTEMPTS = 20.0
CATCHER_ARM_PSEUDO_GAMES = 20.0
CATCHER_ARM_RANGE = (-5, 5)
# T-rating T-1-N: N = T_BASE + T_PER_ARM x arm (unvalidated, see docstring)
CATCHER_T_BASE = 7
CATCHER_T_PER_ARM = 2
# Passed balls: pb = round(PB per season / PB_PER_POINT)
PB_PER_POINT = 4.0
PB_PSEUDO_GAMES = 10.0


def catcher_arm(db: LahmanDB, player_id: str, year: int) -> int | None:
    """Catcher arm rating (the `(0)` in `c-3(0)`); lower = stronger.

    Inputs: the catcher's SB/CS allowed vs the same-season league CS%;
    in seasons where catcher steals weren't recorded (Lahman: before
    1890 and 1949-1953), assists per full game vs the league instead.
    Formula: r = shrunk CS% / league CS% (20 pseudo-attempts at the
    league rate), or shrunk assist ratio (20 pseudo-games);
    arm = round(6 x (1 - r)), clamped to -5..+5 — before shrinkage a 45%
    thrower in a 30% league is -3, a 20% thrower +2.

    Fitted on 2 official arms (Posada 0, Silvera +1): only the slope;
    both land within one (Posada exact). Treat as a reasoned scale more
    than a measurement.
    """
    stats = _position_line(db, player_id, year, "C")
    if not stats or not stats.get("G"):
        return None
    norms = _peer_norms(db, year, "C")
    sb = stats.get("SB", 0) or 0
    cs = stats.get("CS", 0) or 0
    if norms["steals_tracked"] and norms["cs_pct"] and sb + cs > 0:
        lg = norms["cs_pct"]
        rate = (cs + CATCHER_ARM_PSEUDO_ATTEMPTS * lg) / (
            sb + cs + CATCHER_ARM_PSEUDO_ATTEMPTS)
        ratio = rate / lg
    elif norms["a_rate"] > 0:
        games = _games_eq(stats, norms["tc_per_game"])
        expected = games * norms["a_rate"]
        pseudo = CATCHER_ARM_PSEUDO_GAMES * norms["a_rate"]
        ratio = ((stats.get("A", 0) or 0) + pseudo) / (expected + pseudo)
    else:
        return 0
    return _clamp(_round(CATCHER_ARM_SLOPE * (1.0 - ratio)), *CATCHER_ARM_RANGE)


def catcher_throwing(arm: int) -> int:
    """N of the catcher's `T-1-N` throwing rating.

    NOT grounded in data: the token's game meaning is unconfirmed and
    only two cards carry it (Posada arm 0 -> T-1-7, Silvera arm +1 ->
    T-1-9). Both cards increase N with a weaker arm, so N is a linear
    function of the arm through those two points: N = 7 + 2 x arm,
    clamped to 1..20. Revisit when the Advanced Strategy Chart is
    transcribed.
    """
    return _clamp(CATCHER_T_BASE + CATCHER_T_PER_ARM * arm, 1, 20)


def catcher_passed_balls(db: LahmanDB, player_id: str, year: int) -> int | None:
    """Passed-ball rating `pb-N`.

    Inputs: PB and full games caught, league PB per game. Formula:
    pb = round(((PB + 10 x league rate) / (games + 10)) x season_games / 4),
    clamped to 0..20 — about one point per four passed balls a full
    season, like the e-ratings an absolute per-season count. Fitted on 2
    official cards (Posada 13 PB -> pb-4, Silvera 0 -> pb-0): one
    constant (the divisor 4); both exact.
    """
    stats = _position_line(db, player_id, year, "C")
    if not stats or not stats.get("G"):
        return None
    norms = _peer_norms(db, year, "C")
    games = _games_eq(stats, norms["tc_per_game"])
    pb = stats.get("PB", 0) or 0
    rate = (pb + PB_PSEUDO_GAMES * norms["pb_rate"]) / (games + PB_PSEUDO_GAMES)
    per_season = rate * season_games(year, stats.get("lg"))
    return _clamp(_round(per_season / PB_PER_POINT), 0, 20)


# --- batter strategy ratings -------------------------------------------------

# Bunting score = SH / (expected SH + pseudo), expected = PA x league SH/PA
BUNT_PSEUDO_SH = 3.0
BUNT_THRESHOLDS = (("A", 1.15), ("B", 0.75), ("C", 0.4))   # else D

# Hit & run: strikeout ratio = shrunk K/PA / league K/PA
HIT_RUN_PSEUDO_PA = 20.0
HIT_RUN_THRESHOLDS = (("A", 0.33), ("B", 0.635), ("C", 0.93))   # else D


def _league_rate(db: LahmanDB, year: int, league: str, field: str) -> float:
    try:
        raw = db.league_batting(year, league)["raw"]
    except KeyError:
        return 0.0
    pa = _pa(raw)
    return (raw.get(field, 0) or 0) / pa if pa else 0.0


def bunting_rating(db: LahmanDB, stats: dict) -> str:
    """Batter bunting letter A-D.

    Inputs: season SH and PA, league SH per PA (same season and league).
    Formula: score = SH / (PA x league rate + 3); A >= 1.15, B >= 0.75,
    C >= 0.4, else D. The 3 pseudo-sacrifices keep a single bunt from
    making a bunter and, era-robustly, mean a modern player (league
    expectation ~1-2 SH) needs real volume. Seasons where SH wasn't
    recorded get the neutral C.

    Fitted on 12 official batters (Pipp A 1.36, Rizzuto A 1.82, Linz B
    0.92, Combs C 0.57, eight D <= 0.24): the cuts are class midpoints,
    the pseudo-count was chosen to separate Linz's 5 bunts in 209 PA
    from Pipp's 33 in 667. 12/12 exact; leave-one-out (cuts refitted
    without the card) 9/12 exact, 12/12 within one. Bunt hits (speed)
    aren't in Lahman, so a fast, rarely-sacrificing bunter can rate low.
    """
    if "SH" in (stats.get("missing") or []):
        return "C"
    pa = _pa(stats)
    lg = _league_rate(db, stats["year"], stats.get("league", "?"), "SH")
    if pa <= 0 or lg <= 0:
        return "C" if pa <= 0 else "D"
    score = (stats.get("SH", 0) or 0) / (pa * lg + BUNT_PSEUDO_SH)
    for letter, threshold in BUNT_THRESHOLDS:
        if score >= threshold:
            return letter
    return "D"


def hit_and_run_rating(db: LahmanDB, stats: dict) -> str:
    """Batter hit & run letter A-D (contact ability).

    Inputs: season SO and PA, league SO per PA. Formula:
    k = ((SO + 20 x lg) / (PA + 20)) / lg — strikeout rate relative to
    the league with 20 pseudo-PA at the league rate — then A < 0.33,
    B < 0.635, C < 0.93, else D. Seasons without strikeout data get C.

    Fitted on 12 official batters (6 B, 2 C, 4 D): the B and C cuts are
    class midpoints (B/C between LeMahieu 0.61 and Benintendi 0.68, C/D
    between Henderson 0.78 and Judge 1.08); the A cut is NOT fitted (no
    A card in the corpus) and is set where only extreme contact hitters
    reach it (a third of the league strikeout rate, Gwynn-like; 0-3% of
    regulars per season). 12/12 exact; leave-one-out 11/12 exact, 12/12
    within one.
    """
    if "SO" in (stats.get("missing") or []):
        return "C"
    pa = _pa(stats)
    lg = _league_rate(db, stats["year"], stats.get("league", "?"), "SO")
    if lg <= 0:
        return "C"
    ratio = (((stats.get("SO", 0) or 0) + HIT_RUN_PSEUDO_PA * lg)
             / (pa + HIT_RUN_PSEUDO_PA)) / lg
    for letter, threshold in HIT_RUN_THRESHOLDS:
        if ratio < threshold:
            return letter
    return "D"


# --- stealing detail (parsed, not generated) ---------------------------------

_STEAL_DETAIL = re.compile(
    r"^\s*(?P<star>\*)?\s*(?P<a>[\d,\-]*)\s*/\s*(?P<b>[\d,\-]*)\s*"
    r"\(\s*(?P<n1>\d+)\s*-\s*(?P<n2>\d+)\s*\)\s*$")


def _expand_rolls(text: str) -> list[int]:
    rolls: list[int] = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        if part == "-":
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            rolls.extend(range(int(lo), int(hi) + 1))
        else:
            rolls.append(int(part))
    return rolls


def parse_stealing_detail(text: str) -> dict | None:
    """Parse an advanced-side stealing detail like '*2-4,11/5-10,12 (15-1)'.

    Returns {"star": bool, "rolls_a": [...], "rolls_b": [...],
    "numbers": (n1, n2)} or None if it doesn't parse. Recorded, not
    generated: the leading reading is that the rolls before/after the
    slash are the dice results that give the runner a jump (`-` = none)
    and the parenthesized pair are d20 safe ranges, but the corpus doesn't
    pin it down (Linz's two roll sets partition 2-12; Judge's 10-for-10
    prints 20 while Linz's 1-for-7 prints 15). See SYMBOLS.md.
    """
    m = _STEAL_DETAIL.match(text or "")
    if not m:
        return None
    try:
        return {"star": bool(m.group("star")),
                "rolls_a": _expand_rolls(m.group("a")),
                "rolls_b": _expand_rolls(m.group("b")),
                "numbers": (int(m.group("n1")), int(m.group("n2")))}
    except ValueError:
        return None


# --- pitching norms (league start/relief length, pitchers' bunting) --------

def _league_pitching_lengths(db: LahmanDB, year: int, league: str) -> tuple[float, float]:
    """(innings per start, innings per relief appearance) for the league.

    Relief length comes from pure relievers (GS = 0, 3+ games); start
    length is everything else divided by starts, which stays sane in eras
    where nearly every pitcher both started and relieved.
    """
    try:
        a = db.league_pitching_usage(year, league)
    except KeyError:
        return 6.0, 1.2
    if not a["GS"]:
        return 6.0, 1.2
    relief = (a["relief_IPouts"] / 3.0 / a["relief_G"]) if a["relief_G"] else 2.0
    start = (a["IPouts"] / 3.0 - (a["G"] - a["GS"]) * relief) / a["GS"]
    return max(3.0, min(9.0, start)), max(0.5, min(4.0, relief))


def _pitchers_sacrifice_rate(db: LahmanDB, year: int) -> float:
    """Pitchers' sacrifice hits per PA as batters, that season (pooled
    leagues; widened to +-2 seasons when pitchers barely batted, as under
    the universal DH). Two-way players and position players who mopped
    up an inning (more batting games than pitching games) don't count."""
    cache = _cache(db, "bunt")
    if year in cache:
        return cache[year]
    sh = pa = 0
    for span in (0, 2):
        for y in range(year - span, year + span + 1):
            if span and y == year:
                continue
            for pid, pitched in db.season_pitchers(y).items():
                b = db.batting_season(pid, y)
                if b and (b.get("G", 0) or 0) <= pitched:
                    sh += b.get("SH", 0) or 0
                    pa += _pa(b)
        if pa >= 500:
            break
    rate = sh / pa if pa >= 100 and sh > 0 else 0.08
    cache[year] = rate
    return rate


# --- pitcher ratings ---------------------------------------------------------

# wp-N / bk-N: events per WP_IP_SCALE / BK_IP_SCALE innings, clamped 0..20
WP_IP_SCALE = 216.0
BK_IP_SCALE = 300.0
WP_BK_MAX = 20


def wild_pitch_rating(stats: dict) -> int | None:
    """Wild-pitch rating `wp-N`.

    Inputs: season WP and IP. Formula: wp = round(WP / IP x 216),
    clamped to 0..20 (wild pitches per 24 nine-inning games). No
    shrinkage — real cards don't shrink either (Bruney: 1 WP in 34 IP
    prints wp-6). Fitted on 7 official cards (one constant): 6/7 exact,
    7/7 within one (Pettitte 1 WP in 75 IP -> 3 vs card 2).
    None when WP wasn't recorded.
    """
    if "WP" in (stats.get("missing") or []):
        return None
    ip = stats.get("IP", 0.0) or 0.0
    wp = stats.get("WP", 0) or 0
    if ip <= 0:
        return 0 if wp == 0 else WP_BK_MAX
    return _clamp(_round(wp / ip * WP_IP_SCALE), 0, WP_BK_MAX)


def balk_rating(stats: dict) -> int | None:
    """Balk rating `bk-N`.

    Inputs: season BK and IP. Formula: bk = round(BK / IP x 300),
    clamped to 0..20. Fitted on 7 official cards (one constant; only
    three have a balk): 6/7 exact, 7/7 within one (Capuano 1 BK in 97 IP
    -> 3 vs card 4; Gibson 1 in 29 IP -> 10 exact). None when BK wasn't
    recorded.
    """
    if "BK" in (stats.get("missing") or []):
        return None
    ip = stats.get("IP", 0.0) or 0.0
    bk = stats.get("BK", 0) or 0
    if ip <= 0:
        return 0 if bk == 0 else WP_BK_MAX
    return _clamp(_round(bk / ip * BK_IP_SCALE), 0, WP_BK_MAX)


# Hold: a handedness prior (see docstring)
HOLD_LEFTY = -3
HOLD_RIGHTY = 0


def hold_rating(throws: str) -> int:
    """Pitcher hold rating (`hold -4`); negative = holds runners better.

    NOT measurable from Lahman: stolen bases are charged to catchers,
    never to pitchers, so there is no per-pitcher steal record (and no
    pickoffs). This is a handedness prior instead — left-handers face
    first base and hold runners better: LHP -3 (the median of the three
    official lefties, Capuano -4, Pettitte -3, Gibson +4), RHP 0 (the
    median of the four righties +3, 0, 0, -2). Sign convention from the
    cards: Pettitte, famous for his pickoff move, is -3.

    Agreement with the 7 official cards: 3/7 exact, 4/7 within one.
    Leave-one-out, this one-parameter prior (2/7 exact, 4/7 within one,
    mean error 2.1) beats both a constant 0 (mean error 2.9) and
    handedness plus a reliever term (mean error 3.7 — the corpus's
    relievers do print positive holds, but that doesn't survive
    leave-one-out), so the reliever term was dropped.
    """
    if (throws or "").upper().startswith("L"):
        return HOLD_LEFTY
    return HOLD_RIGHTY


# Endurance
STARTER_MIN_GS = _ratings.STARTER_MIN_GS   # Bruney's lone start earns none
RELIEF_MIN_GAMES = 2
STARTER_PSEUDO_STARTS = 4.0
STARTER_PRIOR_DROP = 1.5    # spot-start prior: league start length - 1.5
STARTER_EST_CAP = 0.5       # est. IP/start can't exceed league + 0.5
STARTER_RANGE = (1, 9)
STARTER_ROUNDING = 0.5      # floor(est + this)


def starter_endurance(db: LahmanDB, stats: dict) -> int | None:
    """Starter endurance N of `starter(N)` (None if under 2 starts).

    Inputs: G, GS, IP, and the league's innings per start and per relief
    appearance (LahmanDB.league_pitching_usage). Lahman doesn't split a swingman's
    innings, so innings per start are estimated as (IP - relief
    appearances x league relief length) / GS, capped at league start
    length + 0.5, then shrunk toward a spot-starter prior of league - 1.5
    with 4 pseudo-starts: est = (GS x est + 4 x (lg - 1.5)) / (GS + 4),
    starter = round(est), clamped 1..9. Era-robust by construction: a
    league-average 1906 workhorse lands at 8, a 2012 one at 6.

    Fitted on 5 official starters (Capuano 6, Mendoza 5, Monroe 5,
    Perez 6, Pettitte 6; the cap, the prior offset and the pseudo-count
    are fitted) with the 4 unofficial dead-ball starters (all 8) as a
    check. Agreement: 5/5 exact (unofficial 3/4, Zuber 7 vs 8);
    leave-one-out 3/5 exact, 5/5 within one. The swingmen are the hard
    cases: their real per-start innings are unknowable from season
    totals (Mendoza's 2001 line estimates 21 innings per start).
    """
    starts = stats.get("GS", 0) or 0
    if starts < STARTER_MIN_GS:
        return None
    games = stats.get("G", 0) or 0
    ip = stats.get("IP", 0.0) or 0.0
    lg_start, lg_relief = _league_pitching_lengths(
        db, stats["year"], stats.get("league", "?"))
    est = (ip - max(0, games - starts) * lg_relief) / starts
    est = max(1.0, min(lg_start + STARTER_EST_CAP, est))
    prior = lg_start - STARTER_PRIOR_DROP
    est = ((starts * est + STARTER_PSEUDO_STARTS * prior)
           / (starts + STARTER_PSEUDO_STARTS))
    return _clamp(int(math.floor(est + STARTER_ROUNDING)), *STARTER_RANGE)


def relief_endurance(db: LahmanDB, stats: dict,
                     starter: int | None) -> int | None:
    """Relief endurance N of `relief(N)` (None if under 2 relief games).

    Pure relievers: innings per relief appearance (net of league-length
    starts), rounded, clamped 1..5 (Bruney 0.9 -> 1, Gibson 0.97 -> 1).
    Pitchers who also start get ceil(starter / 2) instead: every official
    swingman/starter with a relief rating fits it (Capuano starter 6 ->
    relief 3, Mendoza 5 -> 3, Monroe 5 -> 3; the excluded McDaniel 8 -> 4
    too), while their actual relief innings would print 1-2. The
    unofficial dead-ball cards print relief 5 for starter 8 (ours: 4).
    Fitted: the rule's form, no constants. Officials 5/5 exact (7/7
    counting the two starters who correctly get no relief rating).
    A pitcher needs 2+ starts for a starter rating (Bruney's single start
    earns none) and 2+ relief games for a relief rating.
    """
    games = stats.get("G", 0) or 0
    starts = stats.get("GS", 0) or 0
    relief_games = games - starts
    if relief_games < RELIEF_MIN_GAMES:
        return None
    if starter is not None:
        return _clamp(math.ceil(starter / 2), 1, 5)
    ip = stats.get("IP", 0.0) or 0.0
    lg_start, _lg_relief = _league_pitching_lengths(
        db, stats["year"], stats.get("league", "?"))
    per_app = max(0.0, ip - starts * lg_start) / relief_games
    return _clamp(_round(per_app), 1, 5)


CLOSER_LOG_SCALE = 1.7


def closer_rating(stats: dict) -> str:
    """The suffix of `relief(N)/X`: 'N' (no saves) or 0..5.

    Inferred meaning: a closer rating (modern cards only; the dead-ball
    and McDaniel cards print no suffix). Lahman has saves but not blown
    saves, so: 'N' when SV = 0, else min(5, floor(1.7 x ln SV)) — 1 save
    -> 0, 6 -> 3, 20+ -> 5. Fitted on the 5 official relief ratings
    (Capuano /N, Gibson /N, Bruney 1 SV /0, Monroe 1 SV /0, Mendoza 6 SV
    /3): all exact, but only one card constrains the scale. Weakly
    grounded.
    """
    saves = stats.get("SV", 0) or 0
    if saves <= 0:
        return "N"
    return str(min(5, int(math.floor(CLOSER_LOG_SCALE * math.log(saves)))))


PITCHER_BUNT_PSEUDO_PA = 5.0
PITCHER_BUNT_THRESHOLDS = (("A", 2.2), ("B", 1.4), ("C", 0.8))   # else D


def pitcher_bunting_rating(db: LahmanDB, player_id: str, year: int) -> str:
    """Pitcher bunting letter A-D (pitchers' own sacrifice bunting).

    Inputs: the pitcher's batting SH and PA that season, and pitchers'
    league-wide SH per PA (p0). Formula: no plate appearances -> C (no
    information: Bruney, Gibson, Perez and Capuano's DH seasons are all
    C); else r = (SH + 5 p0) / ((PA + 5) p0) and B >= 1.4, C >= 0.8,
    else D (A >= 2.2 unfitted). Fitted on 7 official cards (Pettitte
    1-for-5 -> B; Mendoza 0 in 2 PA and Monroe 0 in 17 -> D): 7/7 exact,
    but the B and C cuts each rest on one or two cards.
    """
    batting = db.batting_season(player_id, year)
    pa = _pa(batting) if batting else 0
    if pa <= 0:
        return "C"
    if "SH" in (batting.get("missing") or []):
        return "C"
    p0 = _pitchers_sacrifice_rate(db, year)
    ratio = (((batting.get("SH", 0) or 0) + PITCHER_BUNT_PSEUDO_PA * p0)
             / ((pa + PITCHER_BUNT_PSEUDO_PA) * p0))
    for letter, threshold in PITCHER_BUNT_THRESHOLDS:
        if ratio >= threshold:
            return letter
    return "D"


# --- entry points ------------------------------------------------------------

_POS_ABBR = {"P": "p", "C": "c", "1B": "1b", "2B": "2b", "3B": "3b",
             "SS": "ss", "LF": "lf", "CF": "cf", "RF": "rf", "OF": "of",
             "DH": "dh"}


def advanced_batter_ratings(db: LahmanDB, player_id: str, year: int) -> dict:
    """Everything printed on a batter card's advanced-side header.

    Returns a dict with keys:
      player_id, year, bats ('L'/'R'/'S'/'?'),
      positions: [{pos, range (1-5), games, error (eN),
                   arm (OF: on the first outfield spot only; C),
                   throwing (C: N of T-1-N), passed_ball (C: pb-N)}],
      stealing (AA..E), running (N of 1-N), bunting (A-D),
      hit_and_run (A-D).
    Missing data never raises: a season without batting stats yields
    neutral letters and no positions.
    """
    stats = db.batting_season(player_id, year) or {
        "year": year, "league": "?", "missing": [], "SB": 0, "CS": 0}
    stats.setdefault("year", year)
    info = db.player_info(player_id) or {}
    bats = (info.get("bats") or "?").upper()
    if bats == "B":
        bats = "S"

    positions = []
    arm_done = False
    for pos, rng, games in _fielding.position_ratings(db, player_id, year,
                                                      max_positions=6):
        entry = {"pos": pos, "range": rng, "games": games,
                 "error": error_rating(db, player_id, year, pos)}
        if pos in _OF_CORNERS + ("OF",) and not arm_done:
            entry["arm"] = outfield_arm(db, player_id, year)
            arm_done = True
        if pos == "C":
            arm = catcher_arm(db, player_id, year)
            entry["arm"] = arm
            entry["throwing"] = catcher_throwing(arm if arm is not None else 0)
            entry["passed_ball"] = catcher_passed_balls(db, player_id, year)
        positions.append(entry)

    missing = stats.get("missing") or []
    has_batting = bool(stats.get("AB") or _pa(stats))
    catcher = bool(positions) and positions[0]["pos"] == "C"
    return {
        "player_id": player_id,
        "year": year,
        "bats": bats,
        "positions": positions,
        "stealing": _ratings.stealing_rating(stats.get("SB", 0) or 0,
                                             stats.get("CS", 0) or 0,
                                             cs_missing="CS" in missing,
                                             sb_missing="SB" in missing),
        "running": _ratings.running_rating(stats, catcher=catcher),
        "bunting": bunting_rating(db, stats) if has_batting else "C",
        "hit_and_run": hit_and_run_rating(db, stats) if has_batting else "C",
    }


def _signed(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def advanced_batter_header_lines(ratings: dict) -> list[str]:
    """Header lines in the advanced-card style, one per rating:

    'cf-1(+2) e7', 'lf-1 e7', 'c-3(0) e1, T-1-7(pb-4)', 'stealing-AA',
    'bunting-D', 'hit & run-C', 'running 1-17'. A player with no
    position gets 'dh'.
    """
    lines = []
    for p in ratings.get("positions") or []:
        text = f"{_POS_ABBR.get(p['pos'], p['pos'].lower())}-{p['range']}"
        if p.get("arm") is not None:
            text += f"({_signed(p['arm'])})"
        if p.get("error") is not None:
            text += f" e{p['error']}"
        if p["pos"] == "C" and p.get("throwing") is not None:
            text += f", T-1-{p['throwing']}"
            if p.get("passed_ball") is not None:
                text += f"(pb-{p['passed_ball']})"
        lines.append(text)
    if not lines:
        lines.append("dh")
    lines.append(f"stealing-{ratings['stealing']}")
    lines.append(f"bunting-{ratings['bunting']}")
    lines.append(f"hit & run-{ratings['hit_and_run']}")
    lines.append(f"running 1-{ratings['running']}")
    return lines


def advanced_pitcher_ratings(db: LahmanDB, player_id: str, year: int) -> dict:
    """Everything printed on a pitcher card's advanced-side header.

    Returns a dict with keys:
      player_id, year, throws ('L'/'R'/'?'),
      fielding (1-5, the pitcher-N range rating), error (eN),
      starter (N or None), relief (N or None), closer ('N'/'0'..'5' or
      None when no relief rating), hold (int, negative = better),
      wp (int or None if untracked), bk (int or None), bunting (A-D).
    A season with no pitching line returns the same keys with neutral
    values (no starter/relief, hold from handedness alone).
    """
    info = db.player_info(player_id) or {}
    throws = (info.get("throws") or "?").upper()
    stats = db.pitching_season(player_id, year)
    if not stats:
        stats = {"year": year, "league": "?", "G": 0, "GS": 0, "IP": 0.0,
                 "WP": 0, "BK": 0, "SV": 0, "missing": []}
    rng = _fielding.rate_position(db, player_id, year, "P")
    starter = starter_endurance(db, stats)
    relief = relief_endurance(db, stats, starter)
    return {
        "player_id": player_id,
        "year": year,
        "throws": throws,
        "fielding": rng if rng is not None else 3,
        "error": pitcher_error_rating(db, player_id, year) or 0,
        "starter": starter,
        "relief": relief,
        "closer": closer_rating(stats) if relief is not None else None,
        "hold": hold_rating(throws),
        "wp": wild_pitch_rating(stats),
        "bk": balk_rating(stats),
        "bunting": pitcher_bunting_rating(db, player_id, year),
    }


def advanced_pitcher_header_lines(ratings: dict) -> list[str]:
    """Header lines in the advanced-card style:

    'pitcher-2 e15', 'starter(6) relief(3)/N', 'hold -4', 'wp-18',
    'bk-4', 'bunting-C'. The endurance line lists whichever roles apply
    (a pitcher with neither prints 'relief(1)/N' — every pitcher can
    relieve); untracked wp/bk lines are omitted.
    """
    lines = [f"pitcher-{ratings['fielding']} e{ratings['error']}"]
    roles = []
    if ratings.get("starter") is not None:
        roles.append(f"starter({ratings['starter']})")
    if ratings.get("relief") is not None:
        closer = ratings.get("closer")
        roles.append(f"relief({ratings['relief']})"
                     + (f"/{closer}" if closer is not None else ""))
    if not roles:
        roles.append("relief(1)/N")
    lines.append(" ".join(roles))
    lines.append(f"hold {_signed(ratings['hold'])}")
    if ratings.get("wp") is not None:
        lines.append(f"wp-{ratings['wp']}")
    if ratings.get("bk") is not None:
        lines.append(f"bk-{ratings['bk']}")
    lines.append(f"bunting-{ratings['bunting']}")
    return lines
