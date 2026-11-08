"""Advanced-side (L/R platoon) model: who faces whom, and how much it matters.

An advanced Strat-O-Matic card has two full 108-chance grids per player:
batters one vs left-handed and one vs right-handed pitchers, pitchers one
vs left-handed and one vs right-handed batters. A plate appearance reads
the batter's grid for the pitcher's hand or the pitcher's grid for the
batter's (effective) hand with equal probability, so the basic-card
identity holds per matchup:

    side_chances = (2 * player_rate_in_matchup - league_rate_in_matchup) * 108

Lahman has no platoon split data, so this module supplies what a split
needs from league-level facts:

1. Matchup factors (SAME_HAND_RATIO): how a same-handed matchup changes
   each outcome relative to an opposite-handed one, per batter hand —
   league-wide platoon effects, not per-player splits. One season of an
   individual's split is mostly noise (individual splits regress toward
   the league norm with ~1000 PA vs LHP for lefty hitters and ~2200 for
   righties), so the league-average split for the player's hand is the
   principled estimate. The official cards encode actual splits (Carey
   1953 carries 2 walk chances vs LHP and 19 vs RHP); cards made without
   split data print identical grids, as the four unofficial cards do.
   Switch hitters always bat opposite-handed, so they have no individual
   split; their grids differ only through the opposing average cards.
2. Matchup frequencies per league-year from Lahman handedness (share of
   batters faced by lefty pitchers, share of PA by L/R/switch hitters).
   Matchup league rates are the league rates scaled by the factors and
   renormalized so the frequency-weighted mix is exactly the league line.
3. A usage model for the percentage printed on each grid.
4. The Power rating (N/W) per batter grid, and the share of each
   matchup's PA taken by Power-W batters, which the exact pitcher HR
   accounting needs (stratogen.generate._amplify_n_hr).
"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass

from .model import HR, TRIPLE, DOUBLE, SINGLE, WALK, HBP, SO, OUT

PLATOON_CATEGORIES = (HR, TRIPLE, DOUBLE, SINGLE, WALK, SO, HBP)
HIT_CATEGORIES = (HR, TRIPLE, DOUBLE, SINGLE)
HANDS = ("L", "R")

# --- matchup factors -----------------------------------------------------------

# Same-handed / opposite-handed per-PA rate, by batter hand. From the
# platoon literature: righty hitters' ISO is ~.184 vs LHP against ~.161 vs
# RHP (HR same/opp ~0.88); typical platoon OPS gaps run 30-50 points with
# lefty hitters' splits roughly twice righties'; strikeouts rise and walks
# fall in same-handed matchups; HBP is taken as hand-neutral. One table of
# league norms, deliberately NOT fitted to the (very noisy) splits printed
# on individual real cards.
SAME_HAND_RATIO = {
    "R": {SO: 1.08, WALK: 0.88, HR: 0.88, DOUBLE: 0.95, TRIPLE: 0.95,
          SINGLE: 0.98, HBP: 1.0},
    "L": {SO: 1.22, WALK: 0.82, HR: 0.76, DOUBLE: 0.92, TRIPLE: 0.92,
          SINGLE: 0.95, HBP: 1.0},
}


def opposite(hand: str) -> str:
    return "R" if hand == "L" else "L"


def batting_hand(bats: str | None) -> str:
    """Normalize People.bats: 'L', 'R', 'S' (switch; Lahman 'B') or '?'."""
    b = (bats or "").strip().upper()
    if b in ("B", "S"):
        return "S"
    return b if b in ("L", "R") else "?"


def throwing_hand(throws: str | None) -> str:
    """Normalize People.throws: 'L', 'R' or '?' (unknown/ambidextrous)."""
    t = (throws or "").strip().upper()
    return t if t in ("L", "R") else "?"


def effective_hand(bats: str | None, pitcher_hand: str) -> str:
    """The side a batter hits from against a pitcher's hand. Switch
    hitters take the opposite side; unknown hands count as right-handed
    (the large majority in every era)."""
    b = batting_hand(bats)
    if b == "S":
        return opposite(pitcher_hand)
    return "R" if b == "?" else b


def matchup_factor(cat: str, pitcher_hand: str, batter_hand: str) -> float:
    """Relative rate of `cat` in a matchup (opposite-handed = 1)."""
    h = effective_hand(batter_hand, pitcher_hand)
    if h != pitcher_hand:
        return 1.0
    return SAME_HAND_RATIO[h].get(cat, 1.0)


def split_rates(rates: dict[str, float], factors: dict[str, dict[str, float]],
                shares: dict[str, float]) -> dict[str, dict[str, float]]:
    """Spread one overall rate line over matchup sides.

    `factors[side][cat]` are relative matchup factors and `shares[side]`
    the share of PA on each side. Each category is scaled by its factor
    and renormalized so that sum(share * side_rate) equals the overall
    rate exactly. Categories without factors are copied unchanged.
    """
    out: dict[str, dict[str, float]] = {side: {} for side in factors}
    for cat, r in rates.items():
        norm = sum(shares[s] * factors[s].get(cat, 1.0) for s in factors)
        for side in factors:
            f = factors[side].get(cat, 1.0)
            out[side][cat] = r * f / norm if norm > 0 else r
    return out


def soften(factors: dict[str, dict[str, float]],
           strength: float) -> dict[str, dict[str, float]]:
    """Matchup factors at a fraction of full strength (factor ** strength:
    1 = the league norm, 0 = no split)."""
    if strength == 1.0:
        return factors
    return {side: {cat: f ** strength for cat, f in fac.items()}
            for side, fac in factors.items()}


# --- usage (printed percentage) model --------------------------------------------
#
# Fitted to the transcribed advanced cards (printed share vs the league's
# handedness from Lahman):
# - Batters: share vs LHP = the league's share of batters faced by LHP.
#   A per-hand factor fitted to 1.07 (L, 4 cards) / 1.02 (R, 7) / 0.86
#   (switch, 1 card): within noise of 1, so it is left out. Part-time
#   righties run far higher (Linz 46% vs .29, Silvera 49% vs .35, Carey
#   41% vs .31): they are platoon players who start against lefties, so
#   their share moves toward an even split as playing time drops. Mean
#   absolute error 3.3 points over the 12 official batters (5.7 without
#   the part-time term; bias -0.6).
#   Playing time alone can't tell a platoon player from a regular who
#   missed time, and the larger corpus has three such righties printed
#   near the league share: Adcock 1957 (broken leg, 228 PA: 19%), Ramos
#   2010 (call-up, 82 PA: 20%) and Cespedes's 2015 Mets stint (246 PA:
#   25%). They started 85-95% of the games they played; the platoon
#   righties started 25-64% (Linz 1963 .63, Silvera 1949 .64, Carey 1953
#   .25). So the part-time term is scaled by the start rate (Appearances
#   GS / G_all): in full at or below BENCH_START_RATE, fading to nothing
#   at STARTER_START_RATE; without GS data (most seasons before 1910, a
#   fifth of 1910-49) it applies in full as before. Over the 21 official
#   batters: MAE 4.4 points (5.7 without the gate). The rest is the real
#   splits' spread among regulars (Bautista 2015 printed 19% against a
#   league .30; Strawberry 1985 40% against .31).
# - Pitchers: share vs (effective) LHB = the league's L + switch (for a
#   right-hander) share of PA times a factor for the pitcher's hand and
#   role. Relievers are deployed against same-handed hitters and starters
#   face lineups stacked against them, so on the 13 official pitchers the
#   printed/league ratio splits four ways: right-handed starters 1.04
#   (Drysdale 1965, Perez 1994), right-handed relievers 0.89 (Bruney,
#   Gossage, Mendoza, Zamora), left-handed starters 0.81 (Cuellar 1971,
#   Pettitte 2012, Capuano 2014), left-handed relievers 1.30 (Choate 2014
#   59%, Gibson 1994, Mingori 1973); each the median of its pitchers. A
#   pitcher's factor mixes the two roles by his share of innings in relief
#   (relief_share). Leave-one-out MAE 4.3 points against 7.5 for one
#   common factor (fitted at 0.91 on the first 7, where it beat per-hand
#   factors, and still used when the role is unknown); in sample 3.0. The
#   4 unofficial cards, made without split data, miss by 7.8.

PART_TIME_RHB_TARGET = 0.5      # where a pure platoon righty's share heads
FULL_TIME_PA_PER_GAME = 3.7     # an everyday player's PA per team game
BENCH_START_RATE = 0.65         # starts / games at or below: a platoon role
STARTER_START_RATE = 0.90       # at or above: a regular who missed time
PITCHER_LHB_FACTORS = {("R", "start"): 1.04, ("R", "relief"): 0.89,
                       ("L", "start"): 0.81, ("L", "relief"): 1.30}
PITCHER_LHB_FACTOR = 0.91       # role unknown


def printed_share(share: float) -> float:
    """Round a share to the whole percentage printed on the card."""
    return max(0, min(100, round(share * 100))) / 100.0


def batter_lhp_share(bats: str | None, pa: float, ctx: "PlatoonContext",
                     start_rate: float | None = None) -> float:
    """Share of a batter's PA against left-handed pitchers (unrounded).
    `start_rate` is games started / games played (None: unknown)."""
    f = ctx.lhp_share
    if batting_hand(bats) == "R" and ctx.full_time_pa > 0:
        part_time = max(0.0, min(1.0, 1.0 - pa / ctx.full_time_pa))
        if start_rate is not None:
            part_time *= max(0.0, min(1.0, (STARTER_START_RATE - start_rate)
                                      / (STARTER_START_RATE - BENCH_START_RATE)))
        f += (PART_TIME_RHB_TARGET - f) * part_time
    return f


def relief_share(stats: dict, innings_per_start: float) -> float | None:
    """Share of a pitcher's innings thrown in relief: his starts are
    credited the league's innings per start (capped at his total). None
    without innings."""
    outs = stats.get("IPouts") or 0
    if outs <= 0:
        return None
    ip = outs / 3.0
    start_ip = min(ip, (stats.get("GS") or 0) * innings_per_start)
    return 1.0 - start_ip / ip


def pitcher_lhb_share(throws: str | None, ctx: "PlatoonContext",
                      relief: float | None = None) -> float:
    """Share of a pitcher's batters faced who hit left-handed (switch
    hitters bat left against a right-hander), unrounded. `relief` is his
    share of innings in relief (relief_share; None: role unknown)."""
    g = ctx.batter_shares
    left = throwing_hand(throws) == "L"
    lhb = g["L"] + (0.0 if left else g["S"])
    if relief is None:
        factor = PITCHER_LHB_FACTOR
    else:
        hand = "L" if left else "R"
        factor = (relief * PITCHER_LHB_FACTORS[(hand, "relief")]
                  + (1.0 - relief) * PITCHER_LHB_FACTORS[(hand, "start")])
    return max(0.0, min(1.0, factor * lhb))


# --- power rating -----------------------------------------------------------------
#
# Fitted to the 24 Power labels on the 12 official advanced batter cards
# with a season (side HR rates from the split model above). An absolute
# threshold and a league-relative one both top out at 20/24; absolute wins
# on the evidence: Pipp 1921 hit 1.26% HR/PA (1.24x his league) yet is W
# on both sides, so one side's real rate was >= 1.26% and still W, while
# Combs 1930 (1.16% overall) is N vs RHP. A relative threshold can't
# satisfy both; an absolute one in (1.26%, 1.43%] is consistent with all
# 24 labels given suitable real splits. 1.35% sits mid-window. Final
# agreement 20/24. The misses are all printed N where we say W: Combs vs
# RHP (estimated 1.23%, under the bar), and LeMahieu vs RHP, Linz vs LHP
# and Rizzuto vs LHP, where the forced-W rule below applies (estimated
# side rate under half the league's) — their real splits must have been
# higher on that side.
#
# In low-HR eras an absolute bar makes nearly everyone W (95%+ of 1906-13
# AL PA), which leaves pitcher N-HR almost unreadable and pitchers' HR
# allowed uncontrollable. So the bar is also capped at 1.35x the league's
# matchup HR rate. The cap never binds in a league of the corpus (lowest:
# 1921 AL, 1.01%), so the fit above is unchanged; in 1913 AL it lowers the
# W share to ~0.7 and halves dead-ball pitchers' HR error. No dead-ball
# official card was available to check it against.

POWER_HR_THRESHOLD = 0.0135
POWER_LEAGUE_MULTIPLE = 1.35


def power_rating(side_hr_rate: float, league_side_hr_rate: float) -> str:
    """'N' (normal) or 'W' (weak) power for one batter grid.

    Forced W whenever the N formula would clamp (2r < league rate: the
    opposing average pitcher's N-HR alone exceed his home runs) — W is
    always exactly feasible, so this never costs accuracy. Otherwise N at
    or above min(1.35% of PA, 1.35x the league's matchup HR rate).
    """
    if 2.0 * side_hr_rate < league_side_hr_rate:
        return "W"
    bar = min(POWER_HR_THRESHOLD, POWER_LEAGUE_MULTIPLE * league_side_hr_rate)
    return "N" if side_hr_rate >= bar else "W"


# --- league context ---------------------------------------------------------------

@dataclass(frozen=True)
class PlatoonContext:
    """Platoon facts for one league-year (see league_context)."""
    year: int | None
    league: str | None
    lhp_share: float                     # share of batters faced by LHP
    batter_shares: dict[str, float]      # 'L'/'R'/'S' shares of PA
    full_time_pa: float                  # PA of an everyday player
    league_rates: dict[str, float]       # overall per-PA rates
    rates: dict[tuple[str, str], dict[str, float]]   # (p hand, eff b hand)
    weak_share: dict[tuple[str, str], float]          # Power-W share of PA
    warnings: tuple[str, ...] = ()
    innings_per_start: float = 6.0       # the league's (relief_share)

    def freq(self, pitcher_hand: str, batter_hand: str) -> float:
        """Share of league PA in a matchup (effective batter hand)."""
        f = self.lhp_share if pitcher_hand == "L" else 1.0 - self.lhp_share
        g = self.batter_shares
        h = g[batter_hand] + (g["S"] if batter_hand != pitcher_hand else 0.0)
        return f * h

    def batter_factors(self, bats: str | None) -> dict[str, dict[str, float]]:
        """{pitcher hand: {cat: factor}} for a batter's individual split."""
        return {p: {cat: matchup_factor(cat, p, bats)
                    for cat in PLATOON_CATEGORIES} for p in HANDS}

    def pitcher_factors(self, throws: str | None) -> dict[str, dict[str, float]]:
        """{effective batter hand: {cat: factor}} for a pitcher's split,
        plus 'H' (total hits; the hit factors weighted by the league mix)."""
        t = throwing_hand(throws)
        p = "R" if t == "?" else t
        lg = self.league_rates
        out = {}
        for h in HANDS:
            fac = {cat: matchup_factor(cat, p, h) for cat in PLATOON_CATEGORIES}
            fac["H"] = (sum(lg[c] * fac[c] for c in HIT_CATEGORIES)
                        / sum(lg[c] for c in HIT_CATEGORIES))
            out[h] = fac
        return out

    def cell_league(self, pitcher_hand: str, batter_hand: str) -> dict:
        """A league-like dict (LahmanDB.league_batting keys) holding the
        league's rates in one matchup — what the opposing average grid
        supplies there."""
        r = self.rates[(pitcher_hand, batter_hand)]
        return {
            "year": self.year, "league": self.league,
            "HR_per_PA": r[HR], "3B_per_PA": r[TRIPLE], "2B_per_PA": r[DOUBLE],
            "1B_per_PA": r[SINGLE], "BB_per_PA": r[WALK], "K_per_PA": r[SO],
            "HBP_per_PA": r[HBP],
            "H_per_PA": r[HR] + r[TRIPLE] + r[DOUBLE] + r[SINGLE],
        }


def _base_rates(league: dict) -> dict[str, float]:
    return {HR: league["HR_per_PA"], TRIPLE: league["3B_per_PA"],
            DOUBLE: league["2B_per_PA"], SINGLE: league["1B_per_PA"],
            WALK: league["BB_per_PA"], SO: league["K_per_PA"],
            HBP: league.get("HBP_per_PA", 0.0)}


# Fallback handedness when a league has no known hands at all.
_DEFAULT_LHP_SHARE = 0.27
_DEFAULT_BATTER_SHARES = {"L": 0.33, "R": 0.57, "S": 0.10}


def build_context(league: dict, handedness: dict | None = None,
                  full_time_pa: float = FULL_TIME_PA_PER_GAME * 162,
                  batter_lines: list | None = None,
                  innings_per_start: float = 6.0) -> PlatoonContext:
    """Build the platoon context for a league.

    `handedness` is LahmanDB.league_handedness() output (None -> typical
    shares, with a warning); `batter_lines` is
    LahmanDB.league_batter_lines(), used to estimate the Power-W share of
    each matchup (None -> no Power-W batters).
    """
    warnings = []
    pit = (handedness or {}).get("pitchers") or {}
    bat = (handedness or {}).get("batters") or {}
    if pit:
        lhp = pit.get("L", 0.0)
    else:
        lhp = _DEFAULT_LHP_SHARE
        warnings.append("pitcher handedness unknown for this league: assumed "
                        f"{lhp:.0%} of batters faced by left-handers")
    if bat:
        g = {h: bat.get(h, 0.0) for h in ("L", "R", "S")}
    else:
        g = dict(_DEFAULT_BATTER_SHARES)
        warnings.append("batter handedness unknown for this league: assumed "
                        "typical left/right/switch shares")
    for key, label in (("pitcher_coverage", "pitchers"),
                       ("batter_coverage", "batters")):
        cov = (handedness or {}).get(key, 1.0)
        if 0 < cov < 0.9:
            warnings.append(f"handedness unknown for {1 - cov:.0%} of this "
                            f"league's {label}: shares use the known ones")

    base = _base_rates(league)
    ctx = PlatoonContext(
        year=league.get("year"), league=league.get("league"), lhp_share=lhp,
        batter_shares=g, full_time_pa=full_time_pa, league_rates=base,
        rates={}, weak_share={}, warnings=tuple(warnings),
        innings_per_start=innings_per_start)
    for p in HANDS:
        for h in HANDS:
            ctx.rates[(p, h)] = {}
    for cat, r in base.items():
        z = sum(ctx.freq(p, h) * matchup_factor(cat, p, h)
                for p in HANDS for h in HANDS)
        for (p, h), cell in ctx.rates.items():
            cell[cat] = r * matchup_factor(cat, p, h) / z
    for cell in ctx.rates.values():
        cell[OUT] = 1.0 - sum(cell[c] for c in PLATOON_CATEGORIES)
    ctx.weak_share.update(_weak_shares(ctx, batter_lines or []))
    return ctx


def batter_sides(bats: str | None, pa: float, hr_rate: float,
                 ctx: PlatoonContext, start_rate: float | None = None,
                 ) -> dict[str, tuple[float, float, str]]:
    """{pitcher hand: (share, side HR rate, power)} for a batter, exactly
    as the advanced generator computes them."""
    s_l = printed_share(batter_lhp_share(bats, pa, ctx, start_rate))
    shares = {"L": s_l, "R": 1.0 - s_l}
    factors = {p: {HR: matchup_factor(HR, p, bats)} for p in HANDS}
    side = split_rates({HR: hr_rate}, factors, shares)
    out = {}
    for p in HANDS:
        r = side[p][HR]
        lg_hr = ctx.rates[(p, effective_hand(bats, p))][HR]
        out[p] = (shares[p], r, power_rating(r, lg_hr))
    return out


def _weak_shares(ctx: PlatoonContext, batter_lines) -> dict[tuple[str, str], float]:
    """Share of each matchup's PA taken by Power-W batters: the power rule
    applied to every batter of the league-year (season line, PA in this
    league)."""
    pa = {(p, h): 0.0 for p in HANDS for h in HANDS}
    weak = dict(pa)
    for bats, pa_lg, pa_season, hr, start_rate in batter_lines:
        if pa_season <= 0:
            continue
        for p, (share, _r, power) in batter_sides(
                bats, pa_season, hr / pa_season, ctx, start_rate).items():
            cell = (p, effective_hand(bats, p))
            pa[cell] += pa_lg * share
            if power == "W":
                weak[cell] += pa_lg * share
    return {cell: (weak[cell] / pa[cell] if pa[cell] else 0.0) for cell in pa}


_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_CACHE_LOCK = threading.Lock()


def league_context(league: dict, db=None) -> PlatoonContext:
    """PlatoonContext for a league dict from LahmanDB.league_batting,
    cached per database and league-year. Falls back to typical shares
    (with a warning) when the database has no handedness for it."""
    from .lahman import default_db
    db = db or default_db()
    # A traded player's blended baseline (LahmanDB.season_league) is its own
    # context: its rates differ from the primary league's.
    blend = league.get("blend")
    key = (league.get("year"), league.get("league"),
           tuple(sorted(blend.items())) if blend else None)
    with _CACHE_LOCK:
        cached = _CACHE.get(db, {}).get(key)
    if cached is not None:
        return cached
    year, lg, _blend = key
    try:
        hands = db.league_handedness(year, lg)
        lines = db.league_batter_lines(year, lg)
    except (KeyError, TypeError):
        hands, lines = None, None
    try:
        full_pa = FULL_TIME_PA_PER_GAME * db.league_games_per_team(year, lg)
    except (KeyError, TypeError):
        full_pa = FULL_TIME_PA_PER_GAME * 162
    from .advanced_ratings import _league_pitching_lengths
    try:
        start_ip = _league_pitching_lengths(db, year, lg)[0]
    except (KeyError, TypeError):
        start_ip = 6.0
    ctx = build_context(league, hands, full_time_pa=full_pa, batter_lines=lines,
                        innings_per_start=start_ip)
    with _CACHE_LOCK:
        _CACHE.setdefault(db, {})[key] = ctx
    return ctx
