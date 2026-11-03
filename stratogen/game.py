"""Simplified Strat-O-Matic basic-game engine: full innings, real baserunners,
and a running game calibrated to each league-season.

The per-PA statistical tester (simulate.py) validates outcome *frequencies*;
this module validates *game dynamics* — the things frequencies can't see:
how `*`/`**` advancement symbols, the no-asterisk running gamble, double
plays, sacrifice flies, steals, errors and wild pitches interact to score
runs.

Card readings (rulebook-faithful where the rule is known):
- `**` = every runner advances exactly two bases, on a single or a double,
  with no further advancement; `*` = exactly one base on a single (two on
  a double).
- No asterisk = one base (singles) / two bases (doubles), plus an optional
  gamble by the lead runner *already on base* (never the batter): d20 vs
  his running rating (+2 with two outs), attempted when the effective
  rating is at least GAMBLE_THRESHOLD. Make it and he and every trailing
  runner take an extra base; miss it and he is out while the trailing
  runners still advance. The batter-runner never takes the extra base.
- LINEOUT "into as many outs as possible": batter out, then
  runners are doubled off, lead runner first, until the inning ends — a
  triple play with two on and nobody out.
- Groundballs, as SOM league rule sheets and card-reading guides describe
  the basic chart (the official chart isn't reproduced here):
  A = double play (batter and runner from first) when first is occupied
  with fewer than two outs; B = force at second, batter safe at first, in
  the same situation; otherwise (and always for C) the batter is out at
  first. Other runners advance one base, except that an *unforced* runner
  on third scores on an A/B grounder only when it is hit to the middle
  infield (2b/ss) with the infield back. C (slow roller) moves everyone up.
  `+`/`++` (infield-in / runner-held alternates) read as ordinary outs.
- Flyballs: A = deep, every runner advances one base; B = runner on third
  tags and scores (sacrifice fly), others hold; C = shallow, all hold. No
  advancement once the catch is the third out.
- X-chart chances resolve with league-average defense: X_SINGLE_RATE
  singles, an era-scaled share of one-base errors, otherwise an out of the
  X's batted-ball type (a groundout is a DP-ball A at an era-aware share,
  else B/C as printed on real pitcher cards; a flyout B or C; a lineout or
  popout X an air out that holds the runners).
- `N-HR` reads as a home run, or as SINGLE** for a batter whose power
  rating is W (see card_power_rating / the `power_of` hook). Transcription
  shorthand (`gb (ss) A+`, `fly (lf) B?`, `SI**`, `lo (2b) max`, `HBP
  plus injury`) reads like the canonical text, and a printed hit location
  (`SINGLE** (lf)`) is ignored; anything unrecognizable is a plain out.
- Platoon play (advanced cards, see platoon_grid): an AdvancedCard batter
  reads his grid for the pitcher's throwing hand, an AdvancedCard pitcher
  his grid for the batter's effective hand (switch hitters bat opposite
  the pitcher; unknown hands and basic cards count as right-handed), and
  `N-HR` follows the power of the grid the batter reads. Advanced batter
  grids print all of the batter's HBP, so none is added in his PAs.

League context (LeagueContext, built per (year, league) and cached by
league_context): what cards don't carry is added at the league-season's
own rates, each a closed-form function of Lahman league totals (Teams,
Pitching, catchers' Fielding — see league_game_rates):
- hit-by-pitch: league HBP per PA, taken out of the out readings of any
  card that prints no HBP results (card outs absorbed that mass);
- errors: league E per PA. ROE_SHARE of them put the batter on (one-base
  error): X chances carry an error rate X_ERROR_PROPENSITY times that of
  an ordinary out reading (anchored so modern seasons average X_ERROR_RATE;
  ~40% of all errors), ordinary out readings the rest; the others are
  extra-base errors on hits (every runner, batter included, takes a base).
  Card outs derive from AB - H, so they already contain every ROE: nothing
  is double counted;
- stolen bases: a runner who reaches first with second open may steal
  second before the next PA, at league (SB+CS) per time on first and
  SB/(SB+CS) (imputed from the nearest seasons where CS wasn't recorded),
  scaled by the runner's stealing letter (multipliers measured from
  1951-2024 player-seasons; no letter = league-average runner);
- wild pitches, passed balls and balks: every runner advances one base, at
  league WP/PB/BK per PA with runners aboard;
- sacrifice bunts (nobody out, runner on first or second, third open) and
  intentional walks (first open, runner in scoring position), at league
  SH and IBB rates — both are outside the cards' effective PA;
- double plays: the average card's DP-grounder share comes from the
  league's GIDP rate normalized to DP_REF_ON_BASE (the engine creates the
  DP situations itself, so high-OBP eras mustn't count them twice).
Opportunity counts (PAs with runners on, bunt and IBB situations, arrivals
at first) are linear in the league's times-on-base rate; those constants,
ROE_SHARE and X_DP_SHARE were calibrated on training league-seasons
(1904-2024, years divisible by 4) and verified on the other 1901-2024
seasons. Pickoffs, hit-and-run, outfield arms, the infield-in / holding
decisions, and double plays other than DP grounders and max-effort
lineouts (strike-'em-out-throw-'em-out, liners or flies doubling a runner
off, outfield assists) are not simulated.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import NamedTuple

from .model import (
    AdvancedCard, Card, CHANCES_PER_CYCLE, PlatoonSide, X_CHANCES_PER_PITCHER_CARD,
    HR, TRIPLE, DOUBLE, SINGLE, WALK, HBP, SO, OUT, XCHANCE, categorize,
)
from . import platoon
from .platoon import effective_hand
from .simulate import X_SINGLE_RATE

X_ERROR_RATE = 0.05         # one-base error share of X chances, modern era
GAMBLE_THRESHOLD = 14       # send the runner when effective rating >= this
DEFAULT_RUNNING = 13

# Share of plate appearances that read an X chance off the pitcher card.
X_CHANCE_SHARE = X_CHANCES_PER_PITCHER_CARD / CHANCES_PER_CYCLE

_DICE_SUMS = [d1 + d2 for d1 in range(1, 7) for d2 in range(1, 7)]
_RUNNING_RE = re.compile(r"running\s*1-(\d+)", re.I)
_STEALING_RE = re.compile(r"(?i:stealing)\s*-?\s*\(?\s*\*?\s*(AAA|AA|A|B|C|D|E)\b")
_POWER_RE = re.compile(r"\bpower\s*-?\s*([NW])\b", re.I)


# --- card ratings ---------------------------------------------------------------

def card_running_rating(card: Card) -> int:
    for line in card.header_lines:
        m = _RUNNING_RE.search(line)
        if m:
            return int(m.group(1))
    return DEFAULT_RUNNING


def card_stealing_rating(card: Card) -> str | None:
    """The stealing letter from a 'stealing-X' header line, or None (a
    league-average runner, e.g. the average card)."""
    for line in card.header_lines:
        m = _STEALING_RE.search(line)
        if m:
            return m.group(1)
    return None


def card_power_rating(card: Card) -> str | None:
    """'N' or 'W' from a 'Power-N'/'Power-W' header line, else None (treated
    as N: an N-HR reading is a home run)."""
    for line in card.header_lines:
        m = _POWER_RE.search(line)
        if m:
            return m.group(1).upper()
    return None


@dataclass(eq=False)
class Runner:
    """A baserunner: running rating (1-N) and stealing letter (None = the
    league-average runner). Identity matters, so equality is identity."""
    running: int = DEFAULT_RUNNING
    stealing: str | None = None


def _speed(runner) -> int:
    """Running rating of whatever occupies a base (a Runner or a bare int)."""
    if isinstance(runner, Runner):
        return runner.running
    return runner if isinstance(runner, int) and runner > 0 else DEFAULT_RUNNING


# --- base/out state ----------------------------------------------------------------

@dataclass
class HalfInning:
    # bases hold the occupying runner (a Runner, or a bare running rating)
    bases: list = field(default_factory=lambda: [None, None, None])
    outs: int = 0
    runs: int = 0
    events: Counter = field(default_factory=Counter)
    fresh: object = None   # runner who just reached first (steal candidate)

    def _score_from(self, base: int):
        if self.bases[base] is not None:
            self.runs += 1
            self.bases[base] = None

    def _place(self, base: int, runner):
        if base >= 3:
            self.runs += 1
        else:
            self.bases[base] = runner

    def advance_all(self, n: int):
        """Every runner moves exactly n bases."""
        for _ in range(n):
            self._score_from(2)
            self.bases[2] = self.bases[1]
            self.bases[1] = self.bases[0]
            self.bases[0] = None

    def lead_base(self) -> int | None:
        for base in (2, 1, 0):
            if self.bases[base] is not None:
                return base
        return None

    def force_advance(self):
        """Walk/HBP: only forced runners move."""
        if self.bases[0] is None:
            return
        if self.bases[1] is None:
            self.bases[1] = self.bases[0]
        elif self.bases[2] is None:
            self.bases[2] = self.bases[1]
            self.bases[1] = self.bases[0]
        else:
            self.runs += 1
            self.bases[2] = self.bases[1]
            self.bases[1] = self.bases[0]
        self.bases[0] = None

    def move_up(self, bases=(2, 1, 0)):
        """Runners on the given bases (processed lead first) each advance one
        base if the next base is free; a runner on third scores."""
        for base in bases:
            runner = self.bases[base]
            if runner is None:
                continue
            if base == 2:
                self.runs += 1
                self.bases[2] = None
            elif self.bases[base + 1] is None:
                self.bases[base + 1] = runner
                self.bases[base] = None


# --- reading card texts ------------------------------------------------------------

_NHR_RE = re.compile(r"^\s*N-?HR\b", re.I)
_LETTER_RE = re.compile(r"\)\s*([ABC])(?![a-z])", re.I)
_TRAIL_LETTER_RE = re.compile(r"\s([ABC])\+*\s*[?●]*\s*$")
_POS_RE = re.compile(r"\(\s*([A-Za-z0-9]+)\s*\)")
_MAX_RE = re.compile(r"as many outs|\bmax\b", re.I)
_STARS_RE = re.compile(r"\s*[A-Za-z-]+\s*(\**)")   # the stars of the hit word
_AIR_X_RE = re.compile(r"(LINEOUT|LO|POPOUT|PO)\b")    # lineout/popout X chances
_MIDDLE_INFIELD = {"2b", "ss"}


def canonical_text(text: str) -> str:
    """Card text the engine can classify. Canonical texts pass through;
    transcription shorthand (`gb (ss) A`, `SI** (lf)`, `lo (2b) max`, `HBP
    plus injury`) is normalized via card_json; `N-HR` is kept as is (power-
    dependent, see apply_outcome). Unknown text reads as a plain out."""
    if _NHR_RE.match(text):
        return "N-HR"
    try:
        categorize(text)
        return text
    except ValueError:
        pass
    if text.strip().upper().startswith("HBP"):
        return "HBP"
    try:
        from .card_json import parse_result
        canon, _injury = parse_result(text)
        categorize(canon)
        return canon
    except ValueError:
        return "out"


def _category(text: str) -> str:
    if text == "N-HR":
        return HR
    try:
        return categorize(text)
    except ValueError:
        return OUT


def batted_ball_letter(text: str) -> str:
    """The A/B/C class of a groundball/flyball text ('B' when absent)."""
    m = _LETTER_RE.search(text) or _TRAIL_LETTER_RE.search(text)
    return m.group(1).upper() if m else "B"


def _fielder(text: str) -> str | None:
    m = _POS_RE.search(text)
    return m.group(1).lower() if m else None


class _Reading(NamedTuple):
    """Everything the engine needs from one card text (parsed once)."""
    text: str
    category: str
    stars: int
    kind: str              # out kind: strikeout/groundball/flyball/lineout/other
    letter: str
    fielder: str | None
    max_outs: bool


@lru_cache(maxsize=None)
def _reading(raw: str) -> _Reading:
    text = canonical_text(raw)
    category = _category(text)
    lower = text.lower().lstrip()
    kind = ""
    if category == OUT or category == SO:
        kind = next((k for k in ("strikeout", "groundball", "flyball", "lineout")
                     if lower.startswith(k)), "other")
    stars = 0
    if category in (SINGLE, DOUBLE, TRIPLE, HR):
        stars = min(2, len(_STARS_RE.match(text).group(1)))
    return _Reading(text, category, stars, kind,
                    batted_ball_letter(text), _fielder(text),
                    kind == "lineout" and bool(_MAX_RE.search(text)))


# --- league context ------------------------------------------------------------------

# Stealing letter -> attempt frequency relative to the league-average runner,
# and success log-odds shift relative to the league success rate. Measured
# from 1951-2024 player-seasons with 150+ PA (CS tracked): attempts per time
# on first (1B+BB+HBP) and SB/(SB+CS), pooled by the ratings.stealing_rating
# letter. E is "0 steals" by definition, so its success is set, not measured.
STEAL_ATTEMPT_RELATIVE = {"AAA": 4.5, "AA": 3.9, "A": 2.7, "B": 1.7,
                          "C": 0.94, "D": 0.39, "E": 0.12}
STEAL_SUCCESS_SHIFT = {"AAA": 1.2, "AA": 0.95, "A": 0.5, "B": 0.2,
                       "C": -0.25, "D": -0.7, "E": -1.4}

# Free constants, calibrated on the training league-seasons (every year
# divisible by 4, 1904-2024, AL+NL) and verified on all other 1901-2024
# league-seasons — see tests/test_game.py and the README. "on base" is the
# league's times on base per PA (hits less HR, BB, HBP, reached on error).
STEAL_ATTEMPTS_PER_ARRIVAL = 1.28   # fresh arrivals at 1st per time on first
RUNNERS_ON_BASE = (0.146, 1.015)    # P(runners on at a PA) = a + b * on base
BUNT_SITUATION = (0.035, 0.161)     # P(0 out, on 1st/2nd, 3rd open) = a + b * on base
IBB_SITUATION = (-0.047, 0.618)     # P(1st open, on 2nd/3rd) = a + b * on base
ROE_SHARE = 0.56    # share of league errors that put the batter on (fit to training runs)
# Error odds of an X chance relative to an ordinary out reading, anchored
# so 1993-2024 seasons average X_ERROR_RATE.
X_ERROR_PROPENSITY = 2.65
# Lahman SH include sacrifice flies in these seasons; bunts are estimated as
# SH minus SF_PER_RUN * R (the 1954-2024 league SF/R ratio).
SF_IN_SH_YEARS = frozenset(range(1908, 1931)) | {1939}
SF_PER_RUN = 0.062
# X-chart out letters. Real pitcher cards print no groundball-A (data/
# real_cards: their grounders are 40% B / 60% C, flyballs 83% B / 17% C), so
# double plays on pitcher-card balls in play come through the fielding
# chart: the A share of X groundouts is X_DP_SHARE times the league-average
# batter card's A share (so it follows the era's GIDP rate), with X_DP_SHARE
# calibrated on training-season GIDP; B and C keep the printed 40/60 split.
X_DP_SHARE = 0.38
X_GROUND_B_SHARE = 0.40
X_FLY_B_SHARE = 0.83
# League GIDP / double plays turned, 1933-2024 (0.79-0.86 by era): estimates
# an average card's GIDP rate for seasons that didn't track GIDP.
GIDP_PER_DP = 0.82
# On-base level (times on base per PA) at which a league's GIDP per PA maps
# straight to the average card's DP-grounder share; calibrated on training.
DP_REF_ON_BASE = 0.31


@dataclass(frozen=True)
class LeagueContext:
    """Per-league-season rates for what cards don't carry (see module doc).

    Probabilities are per opportunity: `hbp_per_out`/`roe_per_out` per
    non-strikeout out reading, `x_error` per X chance, `x_double_play` per
    X groundout, `hit_error` per non-HR hit, `steal_attempt` per runner
    arriving at first with second open (league-average runner),
    `wild_pitch`/`passed_ball`/`balk` per plate appearance with runners on,
    `sac_bunt` per bunt situation, `intentional_walk` per IBB situation.
    The default instance is the rules-only engine (no league mechanics).
    """
    year: int | None = None
    league: str | None = None
    hbp_per_out: float = 0.0
    roe_per_out: float = 0.0
    x_error: float = X_ERROR_RATE
    x_double_play: float = 0.35
    batter_gb_a: float = 0.70   # groundball-A share of the league-average batter
    hit_error: float = 0.0
    steal_attempt: float = 0.0
    steal_success: float = 0.7
    wild_pitch: float = 0.0
    passed_ball: float = 0.0
    balk: float = 0.0
    sac_bunt: float = 0.0
    intentional_walk: float = 0.0
    on_base: float = 0.0        # league times on base per PA (for reference)


NEUTRAL_CONTEXT = LeagueContext()


def steal_attempt_probability(context: LeagueContext, letter: str | None) -> float:
    rel = STEAL_ATTEMPT_RELATIVE.get(letter, 1.0) if letter else 1.0
    return min(0.95, context.steal_attempt * rel)


def steal_success_probability(context: LeagueContext, letter: str | None) -> float:
    p = min(0.99, max(0.01, context.steal_success))
    if not letter:
        return p
    z = math.log(p / (1 - p)) + STEAL_SUCCESS_SHIFT.get(letter, 0.0)
    return 1.0 / (1.0 + math.exp(-z))


def _db():
    from .lahman import default_db
    return default_db()


def _near_complete(total) -> bool:
    """Pitching / fielding rows: accept near-complete tracking (a few blank
    cameos). `total` is a lahman.StatTotal or None."""
    return total is not None and total.total > 0 and total.coverage >= 0.95


def league_game_rates(year: int, league: str) -> dict:
    """Real league rates per 27 outs (nine innings) from the Lahman league
    totals (LahmanDB.league_team_totals / league_pitching_totals /
    league_fielding_totals of catchers): R, SB, CS, HBP, E, DP (turned),
    GIDP, SF, WP, BK, PB, SH, IBB. A stat is None when that league-season
    didn't track it for every team (pitching and catching stats: for
    nearly every player row). Per-27-outs (not per game) because games
    average ~8.9 innings; the simulator plays whole nine-inning games.
    Raises KeyError without complete team innings."""
    db = _db()
    team = db.league_team_totals(year, league)
    if not team["IPouts"].complete:
        raise KeyError(f"no team data for {league} {year}")
    per = 27.0 / team["IPouts"].total
    out = {stat: team[stat].total * per if team[stat].complete else None
           for stat in ("R", "SB", "CS", "E", "DP", "SF")}
    try:
        pitching = db.league_pitching_totals(year, league)
    except KeyError:
        pitching = {}
    pitch_outs = pitching["IPouts"].total if pitching else 0
    pitch_per = 27.0 / pitch_outs if pitch_outs else per
    for stat in ("WP", "BK", "HBP", "IBB", "SH", "GIDP"):
        total = pitching.get(stat)
        out[stat] = total.total * pitch_per if _near_complete(total) else None
    try:
        pb = db.league_fielding_totals(year, league, "C")["PB"]
    except KeyError:
        pb = None
    out["PB"] = pb.total * per if _near_complete(pb) else None
    if out["HBP"] is None and team["HBP"].complete:
        out["HBP"] = team["HBP"].total * per
    out["innings_per_game"] = team["IPouts"].total / 3.0 / team["G"].total
    return out


@lru_cache(maxsize=None)
def _steal_success_by_year() -> dict[int, tuple[float, float]]:
    """{year: (SB, CS)} pooled over league-seasons with complete CS data."""
    db = _db()
    out: dict[int, list] = {}
    for year, lg in db.league_seasons():
        try:
            team = db.league_team_totals(year, lg)
        except KeyError:
            continue
        sb, cs = team["SB"], team["CS"]
        if cs.complete and sb.complete and cs.total > 0:
            slot = out.setdefault(year, [0, 0])
            slot[0] += sb.total
            slot[1] += cs.total
    return {y: tuple(v) for y, v in out.items()}


def _imputed_steal_success(year: int) -> float:
    """SB/(SB+CS) pooled over the nearest seasons that tracked CS (+-10
    years, widening if needed) — for leagues that didn't record CS."""
    table = _steal_success_by_year()
    for radius in (10, 25, 200):
        sb = sum(v[0] for y, v in table.items() if abs(y - year) <= radius)
        cs = sum(v[1] for y, v in table.items() if abs(y - year) <= radius)
        if sb + cs > 0:
            return sb / (sb + cs)
    return 0.6


def _context_from_rates(year, league, *, pa_per_27, h, bb, so, hr, singles,
                        hbp, sh=0.0, ibb=0.0, gidp=None,
                        game: dict) -> LeagueContext:
    """Turn league per-PA batting rates (per effective PA, as the cards use)
    plus per-27-out game rates into the engine's per-opportunity
    probabilities. `pa_per_27` is the league's effective PA per 27 outs."""
    def per_pa(stat):
        value = game.get(stat)
        return (value or 0.0) / pa_per_27

    if not hbp:                     # batting HBP untracked: pitchers' HBP
        hbp = per_pa("HBP")

    # Errors. Out readings (non-K, X outs included) carry the HBP mass and
    # every reached-on-error, since card outs derive from AB - H.
    out_reading = max(0.05, 1.0 - h - bb - so)
    e_pa = per_pa("E")
    roe_pa = ROE_SHARE * e_pa
    x_error = min(0.5, X_ERROR_PROPENSITY * roe_pa / out_reading) \
        if e_pa else X_ERROR_RATE
    x_roe_pa = x_error * X_CHANCE_SHARE
    plain_out = max(0.05, out_reading - X_CHANCE_SHARE * (1.0 - X_SINGLE_RATE))
    hbp_per_out = min(0.5, hbp / plain_out)
    roe_per_out = min(0.5, max(0.0, roe_pa - x_roe_pa) / max(0.05, plain_out - hbp))
    non_hr_hits = max(0.01, h - hr)
    hit_error = min(0.5, (1.0 - ROE_SHARE) * e_pa / non_hr_hits)

    # Steals: league attempts per time on first base, per fresh arrival.
    on_first = singles + bb + hbp + roe_pa
    sb, cs = per_pa("SB"), game.get("CS")
    success = (game["SB"] / (game["SB"] + cs)) if (cs and game.get("SB")) \
        else _imputed_steal_success(year or 2000)
    attempts = (sb / success) if sb else 0.0
    steal_attempt = min(0.95, STEAL_ATTEMPTS_PER_ARRIVAL * attempts / on_first) \
        if on_first > 0 else 0.0

    # Wild pitches / passed balls / balks per PA with runners aboard.
    on_base = h - hr + bb + hbp + roe_pa

    # Double plays. A card's groundball-A share comes from GIDP per PA
    # (generate.hit_profile), but the engine creates the DP situations
    # itself, so the league rate is first normalized to DP_REF_ON_BASE
    # (else high-OBP eras count their extra DP chances twice). X groundouts
    # are A at X_DP_SHARE times that share.
    from .generate import _DEFAULT_PROFILE, hit_profile
    if gidp is None and game.get("DP"):
        gidp = GIDP_PER_DP * per_pa("DP")
    if gidp:
        gidp *= DP_REF_ON_BASE / max(0.1, on_base)
        batter_gb_a = hit_profile({"AB": 600, "GIDP": gidp * 600}, pa=600)["gb_a"]
    else:
        batter_gb_a = _DEFAULT_PROFILE["gb_a"]
    runners_on = min(0.95, RUNNERS_ON_BASE[0] + RUNNERS_ON_BASE[1] * on_base)
    wp, pb, bk = (per_pa(s) / runners_on for s in ("WP", "PB", "BK"))

    # Sacrifice bunts and intentional walks (both outside the cards' PA).
    if year in SF_IN_SH_YEARS:
        sh = max(0.0, sh - SF_PER_RUN * per_pa("R"))
    bunt_spots = BUNT_SITUATION[0] + BUNT_SITUATION[1] * on_base
    ibb_spots = IBB_SITUATION[0] + IBB_SITUATION[1] * on_base
    return LeagueContext(
        year=year, league=league, hbp_per_out=hbp_per_out,
        roe_per_out=roe_per_out, x_error=x_error,
        x_double_play=min(0.9, X_DP_SHARE * batter_gb_a), batter_gb_a=batter_gb_a,
        hit_error=hit_error, steal_attempt=steal_attempt, steal_success=success,
        wild_pitch=wp, passed_ball=pb, balk=bk,
        sac_bunt=min(0.9, sh / bunt_spots) if bunt_spots > 0 else 0.0,
        intentional_walk=min(0.9, ibb / ibb_spots) if ibb_spots > 0 else 0.0,
        on_base=on_base)


@lru_cache(maxsize=None)
def league_context(year: int, league: str | None = None) -> LeagueContext:
    """The cached LeagueContext for a league-season. `league=None` pools
    every league of that year (used when only a card's year is known)."""
    db = _db()
    leagues = [league] if league else db.leagues_for_year(year)
    tot: Counter = Counter()
    game: Counter = Counter()
    tracked: dict[str, bool] = {}
    for lg in leagues:
        lgd = db.league_batting(year, lg)
        raw = lgd["raw"]
        tot["pa"] += lgd["PA_eff"]
        for key in ("H", "BB", "IBB", "SO", "HR", "2B", "3B", "HBP", "SH", "GIDP"):
            tot[key] += raw.get(key, 0) or 0
        try:
            rates = league_game_rates(year, lg)
        except KeyError:
            continue
        outs = db.league_team_totals(year, lg)["IPouts"].total
        tot["outs"] += outs
        tot["pa_with_outs"] += lgd["PA_eff"]
        for stat, value in rates.items():
            if value is None:
                tracked[stat] = False
            else:
                tracked.setdefault(stat, True)
                game[stat] += value * outs
    if not tot["pa"]:
        raise KeyError(f"no batting data for {league or 'any league'} {year}")
    pa = tot["pa"]
    game_rates = {stat: (game[stat] / tot["outs"] if tracked.get(stat) else None)
                  for stat in tracked}
    pa_per_27 = (27.0 * tot["pa_with_outs"] / tot["outs"]) if tot["outs"] \
        else 27.0 / max(0.05, 1.0 - (tot["H"] + tot["BB"] - tot["IBB"]) / pa)
    singles = tot["H"] - tot["2B"] - tot["3B"] - tot["HR"]
    return _context_from_rates(
        year, league, pa_per_27=pa_per_27, h=tot["H"] / pa,
        bb=(tot["BB"] - tot["IBB"]) / pa, so=tot["SO"] / pa,
        hr=tot["HR"] / pa, singles=singles / pa, hbp=tot["HBP"] / pa,
        sh=tot["SH"] / pa, ibb=tot["IBB"] / pa,
        gidp=(tot["GIDP"] / pa) if tot["GIDP"] else None, game=game_rates)


def resolve_context(context, pitcher: Card | None = None) -> LeagueContext:
    """Accept a LeagueContext, a league dict from LahmanDB.league_batting
    (or anything with 'year'/'league'), or None. None uses the pitcher
    card's year pooled over that year's leagues when known, else the
    rules-only NEUTRAL_CONTEXT."""
    if isinstance(context, LeagueContext):
        return context
    if isinstance(context, dict):
        return league_context(context["year"], context.get("league"))
    if context is None and pitcher is not None and pitcher.year:
        try:
            return league_context(int(pitcher.year))
        except (KeyError, ValueError):
            return NEUTRAL_CONTEXT
    return NEUTRAL_CONTEXT


# --- outcome resolution ------------------------------------------------------------

def _maybe_gamble(state: HalfInning, rng: random.Random, batter_base: int):
    """The no-asterisk extra-base attempt (rulebook 2.2) by the lead runner
    who was already on base; the batter (on `batter_base`) never goes."""
    lead = None
    for base in (2, 1, 0):
        if base > batter_base and state.bases[base] is not None:
            lead = base
            break
    if lead is None:
        return
    runner = state.bases[lead]
    effective = _speed(runner) + (2 if state.outs == 2 else 0)
    if effective < GAMBLE_THRESHOLD:
        return
    state.events["XB_try"] += 1
    state.bases[lead] = None
    if rng.randint(1, 20) <= effective:
        state._place(lead + 1, runner)
    else:
        state.outs += 1
        state.events["XB_out"] += 1
        if state.outs >= 3:
            return
    # trailing runners (not the batter) take the extra base either way
    state.move_up(range(lead - 1, batter_base, -1))


def _reach_on_error(state: HalfInning, batter):
    """One-base error: every runner advances one base, batter to first."""
    state.advance_all(1)
    state.bases[0] = batter
    state.events["E"] += 1


def _groundball(state: HalfInning, reading: _Reading, batter):
    letter = reading.letter
    b = state.bases
    if b[0] is not None and state.outs < 2 and letter in "AB":
        state.outs += 1
        b[0] = None                    # runner from first is out at second
        if letter == "A":
            state.outs += 1            # ... and the batter at first: DP
            state.events["DP"] += 1
            state.events["GIDP"] += 1
            if state.outs >= 3:
                return
            state.move_up((2, 1))
        else:
            state.move_up((2, 1))      # fielder's choice: batter safe
            b[0] = batter
        return
    state.outs += 1
    if state.outs >= 3:
        return
    forced_third = b[0] is not None and b[1] is not None
    if b[2] is not None and not forced_third and letter != "C":
        fielder = reading.fielder
        if fielder is not None and fielder not in _MIDDLE_INFIELD:
            state.move_up((1, 0))      # runner on third holds (infield back)
            return
    state.move_up()


def _flyball(state: HalfInning, reading: _Reading):
    letter = reading.letter
    state.outs += 1
    if state.outs >= 3:
        return
    if letter in "AB" and state.bases[2] is not None:
        state.events["SF"] += 1
    if letter == "A":                  # deep: every runner tags up
        state.advance_all(1)
    elif letter == "B":                # medium: runner on third tags
        state._score_from(2)


def _lineout(state: HalfInning, reading: _Reading):
    state.outs += 1
    if not reading.max_outs:
        return
    doubled = 0
    for base in (2, 1, 0):
        if state.outs >= 3:
            break
        if state.bases[base] is not None:
            state.bases[base] = None
            state.outs += 1
            doubled += 1
    if doubled:
        state.events["DP"] += 1
        if doubled >= 2:
            state.events["TP"] += 1


def _x_out(reading: _Reading, rng: random.Random, ctx: LeagueContext) -> _Reading:
    """The batted-ball out an X chance becomes when the fielder converts it:
    a groundout is an A (double-play ball) with the context's share, else
    B/C in the proportion printed on real pitcher cards; a flyout is B or C;
    a lineout or popout X is an air out that holds the runners."""
    upper = reading.text.upper().lstrip()
    if "CATCH" in upper:
        return _reading("foulout (c)")
    air = _AIR_X_RE.match(upper)
    if air:
        kind = "lineout" if air.group(1).startswith("L") else "popout"
        return _reading(f"{kind} ({reading.fielder or 'ss'})")
    u = rng.random()
    if upper.startswith("FLY"):
        letter = "B" if u < X_FLY_B_SHARE else "C"
        return _reading(f"flyball ({reading.fielder or 'cf'}){letter}")
    a = ctx.x_double_play
    letter = "A" if u < a else ("B" if u < a + (1 - a) * X_GROUND_B_SHARE else "C")
    return _reading(f"groundball ({reading.fielder or 'ss'}){letter}")


def apply_outcome(state: HalfInning, text: str, batter_running, rng: random.Random,
                  context: LeagueContext | None = None, *, power: str | None = None,
                  inject_hbp: bool = False) -> None:
    """Resolve one card reading against the base/out state.

    `batter_running` is what goes on base for the batter (a Runner or a
    bare running rating). Without a `context` only the card rules apply;
    with one, out readings may become HBP (`inject_hbp`: the read card
    prints no HBP results) or reached-on-error, hits may carry an
    extra-base error, and X chances use the era's error rate.
    """
    ctx = context or NEUTRAL_CONTEXT
    events = state.events
    events["PA"] += 1
    reading = _reading(text)
    if reading.text == "N-HR":
        reading = _reading("SINGLE**" if power == "W" else "HOMERUN")
    category, stars = reading.category, reading.stars

    if category == XCHANCE:
        events["X"] += 1
        roll = rng.random()
        if roll < X_SINGLE_RATE:
            category, stars = SINGLE, 0
        elif roll < X_SINGLE_RATE + ctx.x_error:
            events["E_X"] += 1
            _reach_on_error(state, batter_running)
            return
        else:
            reading = _x_out(reading, rng, ctx)
            category = OUT
    elif category == OUT:
        if inject_hbp and ctx.hbp_per_out and rng.random() < ctx.hbp_per_out:
            category = HBP
        elif ctx.roe_per_out and rng.random() < ctx.roe_per_out:
            events["E_ROE"] += 1
            _reach_on_error(state, batter_running)
            return

    if category in (SINGLE, DOUBLE, TRIPLE, HR):
        events["H"] += 1
    if category == HR:
        events["HR"] += 1
        state.advance_all(3)
        state.runs += 1
        return
    if category == TRIPLE:
        state.advance_all(3)
        state.bases[2] = batter_running
    elif category == DOUBLE:            # * and ** alike: exactly two bases
        state.advance_all(2)
        state.bases[1] = batter_running
        if stars == 0:
            _maybe_gamble(state, rng, batter_base=1)
    elif category == SINGLE:
        state.advance_all(1)
        if stars >= 2:
            state.advance_all(1)
        state.bases[0] = batter_running
        if stars == 0:
            _maybe_gamble(state, rng, batter_base=0)
    elif category in (WALK, HBP):
        events["BB" if category == WALK else "HBP"] += 1
        state.force_advance()
        state.bases[0] = batter_running
        return
    else:
        _out(state, reading, batter_running)
        return
    # a hit: maybe an outfield error lets everyone take one more base
    if ctx.hit_error and state.outs < 3 and rng.random() < ctx.hit_error:
        events["E"] += 1
        events["E_HIT"] += 1
        state.advance_all(1)


def _out(state: HalfInning, reading: _Reading, batter):
    kind = reading.kind
    if kind == "strikeout":
        state.events["SO"] += 1
        state.outs += 1
    elif kind == "groundball":
        _groundball(state, reading, batter)
    elif kind == "flyball":
        _flyball(state, reading)
    elif kind == "lineout":
        _lineout(state, reading)
    else:                               # popout, foulout, unrecognized
        state.outs += 1


# --- league-average cards ------------------------------------------------------------

def synthetic_average_stats(league: dict, pa: int = 600) -> dict:
    """A league-average player-season, scaled to one batter's workload —
    used to lay out average cards with realistic symbol profiles. Stats the
    league didn't track (league['tracked']) are listed under 'missing' (so
    e.g. an untracked SB reads as "unknown", not as a real zero); an
    untracked GIDP is estimated from the league's double plays turned."""
    raw = league.get("raw") or {}
    pa_eff = league.get("PA_eff") or 1
    scale = pa / pa_eff

    def s(key):
        return round((raw.get(key, 0) or 0) * scale)

    tracked = league.get("tracked") or {}
    missing = [stat for stat, ok in tracked.items() if not ok]
    gidp = s("GIDP")
    if not raw.get("GIDP") or not tracked.get("GIDP", True):
        # Untracked: estimate from the league's double plays turned.
        gidp = None
        try:
            dp = _db().league_team_totals(league["year"], league["league"])["DP"]
            if dp.complete:
                gidp = round(GIDP_PER_DP * dp.total * scale)
        except KeyError:
            pass
        if gidp is None:
            missing.append("GIDP")
            gidp = 0
        elif "GIDP" in missing:
            missing.remove("GIDP")
    return {"name": "LEAGUE AVERAGE", "year": league.get("year"),
            "AB": s("AB"), "H": s("H"), "2B": s("2B"), "3B": s("3B"),
            "HR": s("HR"), "BB": s("BB"), "SO": s("SO"), "SB": s("SB"),
            "CS": s("CS"), "HBP": s("HBP"), "SF": s("SF"), "IBB": s("IBB"),
            "GIDP": gidp, "missing": sorted(set(missing))}


def average_cards(league: dict, variant: int = 0) -> tuple[Card, Card]:
    """(average batter card, average pitcher card), fully laid out. The
    batter carries no stealing letter: he is the league-average runner.

    Out types, letters and fielders are allocated by quota against the
    real-card mix and the profile's groundball-A share (generate.
    _OutFlavors), so every layout realizes them as closely as its cells
    allow; where the hits and outs sit still varies by layout. `variant`
    > 0 gives another, independent layout of the same chances (see
    average_lineup)."""
    return (_average_card(league, "batter", variant),
            _average_card(league, "pitcher", variant))


def _average_card(league: dict, card_type: str, variant: int = 0) -> Card:
    from .generate import (average_batter_chances, average_pitcher_chances,
                           hit_profile, layout_card, pitcher_hit_profile)
    extra = f"v{variant}" if variant else ""
    if card_type == "batter":
        profile = hit_profile(synthetic_average_stats(league))
        try:   # DP grounders per DP situation (see _context_from_rates)
            profile["gb_a"] = league_context(league["year"], league["league"]).batter_gb_a
        except (KeyError, TypeError):
            pass
        return layout_card(
            average_batter_chances(league), card_type="batter",
            name="LEAGUE AVERAGE", year=league.get("year"), team=None,
            stats={}, header_lines=["running 1-13"],
            profile=profile, seed_extra=extra)
    return layout_card(
        average_pitcher_chances(league), card_type="pitcher",
        name="LEAGUE AVERAGE", year=league.get("year"), team=None,
        stats={}, header_lines=[],
        profile=pitcher_hit_profile({"TBF": 600}, league), seed_extra=extra)


def average_lineup(league: dict, size: int = 9, first_variant: int = 0) -> list[Card]:
    """Independently laid-out league-average batter cards (same chances,
    different layouts), so layout noise averages out across the lineup."""
    return [_average_card(league, "batter", v)
            for v in range(first_variant, first_variant + size)]


def average_advanced_card(league: dict, card_type: str, hand: str,
                          power: str = "N", variant: int = 0) -> AdvancedCard:
    """A league-average advanced card: a batter who bats `hand` ('L'/'R'/
    'S') with grids of `power` ('N' or 'W', the same on both), or a
    pitcher who throws `hand`. Each grid holds the league's rates in its
    matchup (platoon.league_context(league).cell_league), laid out like
    the average basic cards: generate.average_advanced_batter_chances
    (weak share 0 for N, 1 for W: a Power-W grid carries the N-HR it can't
    read off pitcher grids as its own homers) or average_advanced_pitcher_
    chances (home runs printed N-HR). Printed shares are the league's
    matchup frequencies."""
    from .generate import (average_advanced_batter_chances,
                           average_advanced_pitcher_chances, hit_profile,
                           layout_card, pitcher_hit_profile)
    ctx = platoon.league_context(league)
    year, tag = league.get("year"), f"{hand}{power}v{variant}"
    sides = []
    if card_type == "batter":
        profile = hit_profile(synthetic_average_stats(league))
        try:
            profile["gb_a"] = league_context(year, league["league"]).batter_gb_a
        except (KeyError, TypeError):
            pass
        for p in platoon.HANDS:
            cell = ctx.cell_league(p, effective_hand(hand, p))
            grid = layout_card(
                average_advanced_batter_chances(cell, 1.0 if power == "W" else 0.0),
                card_type="batter", name="LEAGUE AVERAGE", year=year, team=None,
                stats={}, header_lines=["running 1-13"], profile=profile,
                seed_extra=f"advanced vs {p}HP {tag}")
            share = ctx.lhp_share if p == "L" else 1.0 - ctx.lhp_share
            sides.append(PlatoonSide(vs=f"{p}HP", share=share, card=grid, power=power))
        header = ["running 1-13"]
    else:
        profile = pitcher_hit_profile({"TBF": 600}, league)
        freq = {h: ctx.freq(hand, h) for h in platoon.HANDS}
        for h in platoon.HANDS:
            grid = layout_card(
                average_advanced_pitcher_chances(ctx.cell_league(hand, h)),
                card_type="pitcher", name="LEAGUE AVERAGE", year=year, team=None,
                stats={}, header_lines=[], profile=profile,
                seed_extra=f"advanced vs {h}HB {tag}", hr_text="N-HR")
            sides.append(PlatoonSide(vs=f"{h}HB", share=freq[h] / sum(freq.values()),
                                     card=grid))
        header = []
    return AdvancedCard(name="LEAGUE AVERAGE", card_type=card_type, hand=hand,
                        year=year, header_lines=header, sides=sides)


def league_average_rates(league: dict, half_innings: int = 24000, seed: int = 0,
                         lineups: int = 3, pitchers: int = 4,
                         context: LeagueContext | None = None) -> dict[str, float]:
    """The engine's league-level prediction: per-nine-inning rates (R, SB,
    CS, HBP, E, DP, ...) for `lineups` average lineups (9 layouts each)
    against `pitchers` average pitcher layouts, every pairing playing an
    equal share of `half_innings` in the league-season's own context (or
    the given one)."""
    if context is None:
        context = league_context(league["year"], league.get("league"))
    teams = [average_lineup(league, 9, 9 * i) for i in range(lineups)]
    staff = [_average_card(league, "pitcher", v) for v in range(pitchers)]
    pairs = [(lineup, pitcher) for lineup in teams for pitcher in staff]
    share = max(1, half_innings // len(pairs))
    totals: Counter = Counter()
    for i, (lineup, pitcher) in enumerate(pairs):
        sim = GameSimulator(lineup, pitcher, seed=seed + i, context=context)
        for key, value in sim.game_rates(share).items():
            totals[key] += value / len(pairs)
    return dict(totals)


# --- platoon (advanced) cards ----------------------------------------------------

def _throws(card) -> str:
    """A pitcher's throwing hand: an AdvancedCard's, else right-handed (basic
    cards carry no hand; unknown hands count as right-handed, as the
    generator treats them)."""
    hand = card.hand if isinstance(card, AdvancedCard) else None
    return hand if hand in ("L", "R") else "R"


def platoon_grid(card, opponent) -> Card:
    """The default grid_selector: the grid `card` reads against `opponent`.
    An AdvancedCard batter reads his grid for the pitcher's throwing hand;
    an AdvancedCard pitcher his grid for the batter's effective hand
    (platoon.effective_hand: switch hitters bat opposite the pitcher,
    unknown hands and basic cards count as right-handed). A basic card
    reads itself."""
    if not isinstance(card, AdvancedCard):
        return card
    if card.card_type == "pitcher":
        bats = opponent.hand if isinstance(opponent, AdvancedCard) else None
        return card.side(f"{effective_hand(bats, _throws(card))}HB").card
    return card.side(f"{_throws(opponent)}HP").card


def platoon_power(batter, pitcher) -> str | None:
    """'N'/'W' for a batter's N-HR readings: an AdvancedCard batter's power
    on the grid he reads against `pitcher`, else card_power_rating."""
    if isinstance(batter, AdvancedCard) and batter.card_type == "batter":
        return batter.side(f"{_throws(pitcher)}HP").power
    return card_power_rating(batter)


# --- the simulator -------------------------------------------------------------------

class GameSimulator:
    """Plays half-innings with a lineup of batter cards vs one pitcher card.

    Cards may be basic (Card) or advanced (AdvancedCard, read by platoon:
    see platoon_grid), mixed freely. `context` is a LeagueContext, a league
    dict (LahmanDB.league_batting), or None (the pitcher card's year,
    pooled over its leagues; rules-only when the year is unknown). Hooks:
    `grid_selector(card, opponent)` returns the card/grid to read (default
    platoon_grid), and `power_of(card)` returns 'N'/'W' for N-HR readings
    (default platoon_power against this pitcher: an advanced batter's grid
    power, else a 'Power-X' header line).
    """

    def __init__(self, lineup: list, pitcher, seed: int = 0,
                 context=None, *, grid_selector=None, power_of=None):
        self.lineup = list(lineup)
        self.pitcher = pitcher
        self.rng = random.Random(seed)
        self.context = resolve_context(context, pitcher)
        self.grid_selector = grid_selector or platoon_grid
        self._next_batter = 0
        self._runners = [Runner(card_running_rating(c), card_stealing_rating(c))
                         for c in self.lineup]
        self._power = [power_of(c) if power_of else platoon_power(c, pitcher)
                       for c in self.lineup]
        # Advanced batter grids print all of a batter's HBP (pitcher grids
        # none), so his plate appearances get no league HBP added.
        self._add_hbp = [not isinstance(c, AdvancedCard) for c in self.lineup]
        self._grids: dict[int, tuple] = {}
        self.totals: Counter = Counter()

    @property
    def _running(self) -> list[int]:
        """Running ratings by lineup slot (kept for compatibility)."""
        return [r.running for r in self._runners]

    def _grid(self, card: Card) -> tuple:
        """(card, 2160 texts indexed by column x 2d6 x d20, prints HBP?),
        built once per card so a reading costs one random number."""
        entry = self._grids.get(id(card))
        if entry is None or entry[0] is not card:
            texts = []
            for column in card.column_numbers:
                rows = {}
                for dice_sum, splits in card.columns[column].items():
                    row = [None] * 20
                    for s in splits:
                        row[s.lo - 1:s.hi] = [s.text] * (s.hi - s.lo + 1)
                    if None in row:
                        raise AssertionError("d20 ranges must cover 1-20")
                    rows[dice_sum] = row
                for dice_sum in _DICE_SUMS:
                    texts.extend(rows[dice_sum])
            has_hbp = any(_reading(t).category == HBP for t in set(texts))
            entry = self._grids[id(card)] = (card, texts, has_hbp)
        return entry

    def _card_has_hbp(self, card: Card) -> bool:
        return self._grid(card)[2]

    def _read_card(self, batter: Card) -> tuple[str, Card]:
        """White die (batter card on 1-3, pitcher card on 4-6, which also
        picks the column), two dice for the row, a d20 for the split."""
        i = int(self.rng.random() * 4320)
        if i < 2160:
            card = self.grid_selector(batter, self.pitcher)
        else:
            card = self.grid_selector(self.pitcher, batter)
            i -= 2160
        return self._grid(card)[1][i], card

    def _before_pitch(self, state: HalfInning, batter) -> bool:
        """What happens before the card is read: a steal attempt by a runner
        who just reached first with second open; a wild pitch / passed ball
        / balk; then the manager's call — an intentional walk (first base
        open, a runner in scoring position) or a sacrifice bunt (nobody out,
        a runner on first or second, third open). Returns True when the
        batter's turn was used up without reading a card."""
        ctx, rng, bases, events = self.context, self.rng, state.bases, state.events
        fresh, state.fresh = state.fresh, None
        if fresh is not None and bases[0] is fresh and bases[1] is None:
            events["opp_steal"] += 1
            letter = fresh.stealing if isinstance(fresh, Runner) else None
            if ctx.steal_attempt and \
                    rng.random() < steal_attempt_probability(ctx, letter):
                bases[0] = None
                if rng.random() < steal_success_probability(ctx, letter):
                    bases[1] = fresh
                    events["SB"] += 1
                else:
                    state.outs += 1
                    events["CS"] += 1
                    if state.outs >= 3:
                        return False
        if bases[0] is None and bases[1] is None and bases[2] is None:
            return False
        events["opp_runners"] += 1
        u = rng.random()
        free = ctx.wild_pitch + ctx.passed_ball + ctx.balk
        if u < free:
            kind = ("WP" if u < ctx.wild_pitch else
                    "PB" if u < ctx.wild_pitch + ctx.passed_ball else "BK")
            events[kind] += 1
            state.advance_all(1)
        if bases[0] is None and (bases[1] is not None or bases[2] is not None):
            events["opp_ibb"] += 1
            if ctx.intentional_walk and rng.random() < ctx.intentional_walk:
                events["IBB"] += 1
                bases[0] = state.fresh = batter
                return True
        if (state.outs == 0 and bases[2] is None
                and (bases[0] is not None or bases[1] is not None)):
            events["opp_bunt"] += 1
            if ctx.sac_bunt and rng.random() < ctx.sac_bunt:
                events["SH"] += 1
                state.outs += 1
                state.move_up((1, 0))
                return True
        return False

    def play_half_inning(self) -> int:
        state = HalfInning()
        n = len(self.lineup)
        while state.outs < 3:
            idx = self._next_batter % n
            runner = self._runners[idx]
            if self._before_pitch(state, runner):
                self._next_batter += 1   # bunted or walked intentionally
                continue
            if state.outs >= 3:
                break                    # caught stealing: batter leads off next
            self._next_batter += 1
            text, card = self._read_card(self.lineup[idx])
            apply_outcome(state, text, runner, self.rng, self.context,
                          power=self._power[idx],
                          inject_hbp=(self._add_hbp[idx]
                                      and not self._card_has_hbp(card)))
            if state.bases[0] is runner:
                state.fresh = runner
        self.totals.update(state.events)
        self.totals["R"] += state.runs
        self.totals["half_innings"] += 1
        return state.runs

    def game_rates(self, half_innings: int = 20000) -> dict[str, float]:
        """Play `half_innings`; per-nine-inning rates of runs and events
        (R, SB, CS, HBP, E, DP, GIDP, SF, WP, PB, BK, PA, H, ...)."""
        before = Counter(self.totals)
        for _ in range(half_innings):
            self.play_half_inning()
        delta = self.totals - before
        games = half_innings / 9.0
        return {k: v / games for k, v in delta.items() if k != "half_innings"}

    def runs_per_game(self, half_innings: int = 20000) -> float:
        total = sum(self.play_half_inning() for _ in range(half_innings))
        return total / half_innings * 9.0
