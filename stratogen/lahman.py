"""Offline baseball statistics from the Lahman database (1871-2025).

Reads the CSVs in data/lahman/ (Batting, Pitching, People, Teams,
Fielding, FieldingOFsplit, and Appearances when present). Each table may
be gzipped (`Batting.csv.gz`) or plain (`Batting.csv`); when both exist the
newer file wins, so a new season's plain CSVs can simply be dropped in.
Everything works offline; no scraping. League averages are computed per
(year, league) by aggregating every player row, so any year/league
combination present in the data is supported — all eras.

Each table is read once. Rows are converted to compact tuples of ints and
league totals (batting, pitching, fielding, team), player-year indexes,
handedness shares and fielding peer pools are built in the same pass, so
nothing ever rescans a file. After warm() the process holds roughly
250 MB, mostly the per-season stat tuples (raw CSV row dicts would cost
several times that).

Conventions for the season dicts returned by batting_season /
pitching_season:

* ``missing`` lists stats not recorded at all that season (summed as 0);
  ``partial`` lists stats recorded for some stints but not others (the sum
  undercounts). A batter's SO is also ``missing`` when his league's batting
  strikeouts weren't kept (19th-century AA/UA, most Negro-league seasons).
* Innings pitched: ``IPouts`` is the exact out count. ``IP`` is an
  `InningsPitched` float equal to IPouts / 3 exactly (use it for math)
  whose str() is the baseball notation, where the digit after the point
  counts outs: 273.1 = 273 1/3 innings, 273.2 = 273 2/3. ``IP_display`` is
  that string. ERA is computed from IPouts (None when runs scored without
  an out recorded).
* ``league`` is the league where the player did most of his work (PA for
  batters, batters faced for pitchers); ``league_weights`` maps every
  league he played in to that work; ``team`` is his final team that
  season (as Strat-O-Matic labels traded players) and ``teams`` lists every
  team in order. season_league(stats) gives the matching league baseline.

To update for a new season: download the latest CSV release from
https://sabr.org/lahman-database/ and drop the new .csv (or .csv.gz)
files into data/lahman/.
"""

from __future__ import annotations

import csv
import gzip
import logging
import random
import threading
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from operator import itemgetter
from pathlib import Path
from sys import intern
from typing import NamedTuple

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "lahman"

log = logging.getLogger(__name__)

# Stats summed across a player's stints in one season
_BATTING_FIELDS = ["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS",
                   "BB", "SO", "IBB", "HBP", "SH", "SF", "GIDP"]
_PITCHING_FIELDS = ["W", "L", "G", "GS", "CG", "SHO", "SV", "IPouts", "H", "ER",
                    "HR", "BB", "SO", "IBB", "WP", "HBP", "BK", "BFP", "GF", "R",
                    "SH", "SF", "GIDP"]
# Fielding stats kept per position (stints summed)
_FIELDING_STATS = ["G", "GS", "InnOuts", "PO", "A", "E", "DP", "PB", "SB", "CS"]
# Teams columns kept as league totals (the integer ones)
_TEAM_FIELDS = ["G", "Ghome", "W", "L", "R", "AB", "H", "2B", "3B", "HR", "BB",
                "SO", "SB", "CS", "HBP", "SF", "RA", "ER", "CG", "SHO", "SV",
                "IPouts", "HA", "HRA", "BBA", "SOA", "E", "DP"]
# Appearances columns used to split a combined outfield into corners
_APPEARANCE_FIELDS = ["G_lf", "G_cf", "G_rf", "G_dh"]

_BAT_IDX = {f: i for i, f in enumerate(_BATTING_FIELDS)}
_PIT_IDX = {f: i for i, f in enumerate(_PITCHING_FIELDS)}
_FLD_IDX = {f: i for i, f in enumerate(_FIELDING_STATS)}

# The major leagues. From 1901 the AL, NL (and the 1914-15 Federal League)
# are one competitive pool; the rest are Negro-league and independent
# "leagues", some of them only a few clubs.
MAJOR_LEAGUES = frozenset({"NA", "NL", "AA", "UA", "PL", "AL", "FL"})
MODERN_MAJOR_LEAGUES = frozenset({"AL", "NL", "FL"})

# League-average baselines need volume: below this many effective PA a
# (year, league) is pooled with comparable leagues (see league_batting).
MIN_LEAGUE_PA = 5000
# A league's batting strikeouts are distrusted when they fall below this
# share of its pitchers' strikeouts (blank or zero-filled batting SO).
_SO_RECORDED_SHARE = 0.8
# A batting stat counts as tracked when rows carrying it hold at least
# this share of the league's effective PA.
_TRACKED_COVERAGE = 0.5
# Recorded batters faced below this share of IPouts + H + BB + HBP is a
# partial count (1925 NNL/ECL), treated as not recorded.
_BFP_PLAUSIBLE_SHARE = 0.5

# Handedness buckets for the league matchup accumulators. People.bats uses
# 'B' (both) for switch hitters; we call them 'S'. Blank or odd values
# (e.g. throws 'B'/'S' for the handful of ambidextrous pitchers) are
# unknown and left out of the shares.
_BAT_HANDS = ("L", "R", "S", "?")
_PIT_HANDS = ("L", "R", "?")
_BAT_HAND_IDX = {"L": 0, "R": 1, "B": 2, "S": 2}
_PIT_HAND_IDX = {"L": 0, "R": 1}
_PA_TERMS = tuple((_BAT_IDX[k], sign) for k, sign in
                  (("AB", 1), ("BB", 1), ("IBB", -1), ("HBP", 1), ("SF", 1)))


def _pa_eff(values: tuple) -> int:
    """AB + BB - IBB + HBP + SF from a compact batting tuple (None -> 0)."""
    return sum((values[i] or 0) * sign for i, sign in _PA_TERMS)


_BFP_I, _OUTS_I = _PIT_IDX["BFP"], _PIT_IDX["IPouts"]
_EST_I = tuple(_PIT_IDX[k] for k in ("IPouts", "H", "BB"))
_HBP_I, _PIBB_I = _PIT_IDX["HBP"], _PIT_IDX["IBB"]


def _batters_faced(values: tuple) -> int:
    """Batters faced from a compact pitching tuple: BFP when recorded,
    else estimated the way the card generator does (3 per inning + hits
    + walks)."""
    return values[_BFP_I] or sum(values[i] or 0 for i in _EST_I)


def _plausible_bfp(bfp: int | None, est: int) -> int | None:
    """BFP, or None when it is a partial count far below the outs and
    baserunners on record (1925 NNL/ECL: 8 batters faced in 124 innings).
    Legitimate tiny lines (one batter, a double play) pass."""
    if bfp is not None and 0 < bfp < _BFP_PLAUSIBLE_SHARE * est:
        return None
    return bfp


_QUOTES = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'"})
_SEPARATORS = str.maketrans({".": " ", ",": " ", "-": " ", "'": None})
_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv"})


def _norm_name(s: str) -> str:
    """Normalize a name for matching: accents, case, curly quotes,
    punctuation and spacing folded; runs of initials joined ('A. J.' and
    'AJ' -> 'aj'); trailing Jr./Sr./II-IV dropped (Lahman has no suffix
    field, so 'Ken Griffey Jr.' must find 'Ken Griffey')."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().translate(_QUOTES).translate(_SEPARATORS)
    out: list[str] = []
    initials = ""
    for token in s.split():
        if len(token) == 1:
            initials += token
            continue
        if initials:
            out.append(initials)
            initials = ""
        out.append(token)
    if initials:
        out.append(initials)
    while len(out) > 1 and out[-1] in _NAME_SUFFIXES:
        out.pop()
    return " ".join(out)


def _int_or_none(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _add(a: int | None, b: int | None) -> int | None:
    """None-aware sum: unrecorded + unrecorded stays unrecorded."""
    if a is None:
        return b
    if b is None:
        return a
    return a + b


def innings_display(outs: int) -> str:
    """Baseball innings notation for an out count: 820 -> '273.1'
    (273 1/3 innings), 3 -> '1.0'."""
    outs = int(outs)
    return f"{outs // 3}.{outs % 3}"


class InningsPitched(float):
    """Innings pitched: equal to outs / 3 exactly (arithmetic stays exact)
    but printed in baseball notation — str(InningsPitched(820)) == '273.1',
    meaning 273 1/3 innings. `.outs` is the out count."""

    def __new__(cls, outs: int):
        self = super().__new__(cls, int(outs) / 3.0)
        self.outs = int(outs)
        return self

    def __getnewargs__(self):
        return (self.outs,)

    def __str__(self) -> str:
        return innings_display(self.outs)

    def __format__(self, spec: str) -> str:
        return str(self) if not spec else float.__format__(self, spec)


class StatTotal(NamedTuple):
    """A league total: (sum over rows that recorded the stat, rows that
    recorded it, all rows). A blank cell is "not recorded"; a 0 counts."""
    total: int
    tracked: int
    rows: int

    @property
    def complete(self) -> bool:
        """Every row recorded the stat."""
        return self.rows > 0 and self.tracked == self.rows

    @property
    def coverage(self) -> float:
        """Share of rows that recorded the stat."""
        return self.tracked / self.rows if self.rows else 0.0


class _TotalsAcc:
    """Per-key [sums], [rows with a value], rows accumulator."""

    __slots__ = ("sums", "counts", "rows")

    def __init__(self, n: int):
        self.sums = [0] * n
        self.counts = [0] * n
        self.rows = 0

    def add(self, values) -> None:
        self.rows += 1
        sums, counts = self.sums, self.counts
        for i, v in enumerate(values):
            if v is not None:
                sums[i] += v
                counts[i] += 1

    def result(self, fields: list[str]) -> dict[str, StatTotal]:
        return {f: StatTotal(s, c, self.rows)
                for f, s, c in zip(fields, self.sums, self.counts)}


class SearchResults(list):
    """search_players' hits (a list) plus `.total`: how many players
    matched before the list was cut to `limit`."""

    total: int = 0


@dataclass
class PlayerHit:
    player_id: str
    name: str
    first_year: int | None
    last_year: int | None
    bats: str
    throws: str
    batting_years: list[int]     # seasons that can make a batter card
    pitching_years: list[int]    # seasons that can make a pitcher card


class LahmanDB:
    """Lazy-loading access layer over the Lahman CSVs."""

    def __init__(self, data_dir: str | Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        self._lock = threading.RLock()
        self._people: dict[str, dict] | None = None
        self._full_index: dict[str, list[str]] = {}
        self._last_index: dict[str, list[str]] = {}
        self._name_keys: list[tuple[str, str, tuple[str, ...]]] = []
        self._career: dict[str, int] | None = None
        # (pid, year) -> list of stints (teamID, lgID, values tuple)
        self._batting: dict | None = None
        self._pitching: dict | None = None
        # seasons that can generate a card (effective PA / batters faced > 0)
        self._batting_years: dict[str, list[int]] = {}
        self._pitching_years: dict[str, list[int]] = {}
        # every season with a row, playable or not
        self._seasons_any: dict[str, tuple[int, int]] = {}
        # (year, lg) -> ([sums], [PA_eff of rows recording each field], PA_eff)
        self._league_acc: dict[tuple[int, str], tuple[list, list, list]] = {}
        self._year_leagues: dict[int, set] = {}
        self._pitching_totals: dict[tuple[int, str], _TotalsAcc] = {}
        self._pitching_usage: dict[tuple[int, str], dict] = {}
        self._season_pitchers: dict[int, dict[str, int]] | None = None
        # (pid, year) -> {pos: (values tuple, lg)}
        self._fielding: dict | None = None
        # (year, pos) -> [(lg, values tuple)]
        self._fielding_peer_pool: dict[tuple[int, str], list] = {}
        self._fielding_peers_cache: dict[tuple, list[dict]] = {}
        self._fielding_totals: dict[tuple[int, str, str], _TotalsAcc] = {}
        # (pid, year) -> (G_lf, G_cf, G_rf, G_dh); empty without Appearances
        self._appearances: dict[tuple[str, int], tuple] = {}
        self._team_names: dict[tuple[int, str], str] | None = None
        self._team_totals: dict[tuple[int, str], _TotalsAcc] = {}
        self._league_rg: dict[tuple[int, str], list[int]] = {}
        self._league_teams: dict[tuple[int, str], int] = {}
        self._league_totals: dict[tuple[int, str], dict] = {}
        # (year, lg) -> effective PA by batter hand (_BAT_HANDS order) and
        # batters faced by pitcher hand (_PIT_HANDS order): the platoon
        # matchup frequencies, built in the same single load pass.
        self._league_bat_hands: dict[tuple[int, str], list[int]] = {}
        self._league_pit_hands: dict[tuple[int, str], list[int]] = {}
        self._random_pool: list[tuple[str, int, str]] | None = None

    # --- files -------------------------------------------------------------

    def table_path(self, table: str) -> Path | None:
        """The file a table is read from: `<table>.csv` or `<table>.csv.gz`
        in the data directory, the newer one when both exist (so dropped-in
        plain CSVs from a new release win over the bundled .gz). None when
        neither exists."""
        found = [p for p in (self.data_dir / f"{table}.csv",
                             self.data_dir / f"{table}.csv.gz") if p.is_file()]
        if not found:
            return None
        return max(found, key=lambda p: p.stat().st_mtime)

    def _open(self, table: str):
        path = self.table_path(table)
        if path is None:
            raise FileNotFoundError(
                f"no {table}.csv or {table}.csv.gz in {self.data_dir}")
        log.info("Lahman %s: reading %s", table, path.name)
        if path.suffix == ".gz":
            return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
        return open(path, "r", encoding="utf-8-sig", newline="")

    def _rows(self, table: str):
        """Every row of a table as a dict."""
        with self._open(table) as fh:
            yield from csv.DictReader(fh)

    def _read(self, table: str, columns: list[str]):
        """Every row of a table as a tuple of the named columns ('' for a
        column the file lacks). Faster and leaner than _rows."""
        with self._open(table) as fh:
            reader = csv.reader(fh)
            header = next(reader, [])
            idx = {h: i for i, h in enumerate(header)}
            pad = len(header)
            getter = itemgetter(*[idx.get(c, pad) for c in columns])
            for row in reader:
                if not row:
                    continue
                if len(row) < pad:
                    row.extend([""] * (pad - len(row)))
                row.append("")
                yield getter(row)

    def warm(self):
        """Load everything up front (e.g. in a background thread)."""
        self._load_people()
        self._load_batting()
        self._load_pitching()
        self._load_fielding()
        self._load_teams()

    # --- people / search -------------------------------------------------

    def _load_people(self):
        if self._people is not None:   # lock-free fast path once loaded
            return
        with self._lock:
            if self._people is not None:
                return
            people: dict[str, dict] = {}
            full: dict[str, list[str]] = defaultdict(list)
            last_index: dict[str, list[str]] = defaultdict(list)
            keys = []
            cols = ["playerID", "nameFirst", "nameLast", "bats", "throws",
                    "debut", "finalGame"]
            for pid, first, last, bats, throws, debut, final in self._read(
                    "People", cols):
                if not pid:
                    continue
                name = f"{first} {last}".strip()
                people[pid] = {
                    "name": name or pid,
                    "bats": intern(bats or "?"),
                    "throws": intern(throws or "?"),
                    "first_year": int(debut[:4]) if debut[:4].isdigit() else None,
                    "last_year": int(final[:4]) if final[:4].isdigit() else None,
                }
                key = _norm_name(name)
                if key:
                    full[key].append(pid)
                last_key = _norm_name(last)
                if last_key:
                    last_index[last_key].append(pid)
                keys.append((pid, key, tuple(key.split())))
            self._full_index = dict(full)
            self._last_index = dict(last_index)
            self._name_keys = keys
            self._people = people

    def _load_batting(self):
        if self._batting is not None:
            return
        with self._lock:
            if self._batting is not None:
                return
            self._load_people()  # hands are accumulated in this pass
            people = self._people
            table: dict = defaultdict(list)
            n = len(_BATTING_FIELDS)
            league_acc: dict = {}
            bat_hands: dict = {}
            year_leagues: dict = {}
            cols = ["playerID", "yearID", "teamID", "lgID"] + _BATTING_FIELDS
            for row in self._read("Batting", cols):
                pid = row[0]
                year = int(row[1])
                team = intern(row[2])
                lg = intern(row[3] or "?")
                values = tuple(map(_int_or_none, row[4:]))
                table[(pid, year)].append((team, lg, values))
                pa = _pa_eff(values)
                key = (year, lg)
                hands = bat_hands.get(key)
                if hands is None:
                    hands = bat_hands[key] = [0] * len(_BAT_HANDS)
                bats = people.get(pid, {}).get("bats", "?")
                hands[_BAT_HAND_IDX.get(bats, 3)] += pa
                acc = league_acc.get(key)
                if acc is None:
                    acc = league_acc[key] = ([0] * n, [0] * n, [0])
                sums, cover, total = acc
                total[0] += pa
                for i, v in enumerate(values):
                    if v is not None:
                        sums[i] += v
                        cover[i] += pa
                year_leagues.setdefault(year, set()).add(lg)
            years: dict[str, list[int]] = defaultdict(list)
            for (pid, year), stints in table.items():
                if sum(_pa_eff(s[2]) for s in stints) > 0:
                    years[pid].append(year)
            self._league_acc = league_acc
            self._league_bat_hands = bat_hands
            self._year_leagues = year_leagues
            self._batting_years = {p: sorted(ys) for p, ys in years.items()}
            self._batting = dict(table)

    def _load_pitching(self):
        if self._pitching is not None:
            return
        with self._lock:
            if self._pitching is not None:
                return
            self._load_people()  # hands are accumulated in this pass
            people = self._people
            table: dict = defaultdict(list)
            totals: dict = {}
            pit_hands: dict = {}
            n = len(_PITCHING_FIELDS)
            cols = ["playerID", "yearID", "teamID", "lgID"] + _PITCHING_FIELDS
            for row in self._read("Pitching", cols):
                pid = row[0]
                year = int(row[1])
                team = intern(row[2])
                lg = intern(row[3] or "?")
                values = list(map(_int_or_none, row[4:]))
                est = (sum(values[i] or 0 for i in _EST_I)
                       + (values[_HBP_I] or 0))
                values[_BFP_I] = _plausible_bfp(values[_BFP_I], est)
                values = tuple(values)
                table[(pid, year)].append((team, lg, values))
                key = (year, lg)
                acc = totals.get(key)
                if acc is None:
                    acc = totals[key] = _TotalsAcc(n)
                acc.add(values)
                hands = pit_hands.get(key)
                if hands is None:
                    hands = pit_hands[key] = [0] * len(_PIT_HANDS)
                throws = people.get(pid, {}).get("throws", "?")
                hands[_PIT_HAND_IDX.get(throws, 2)] += _batters_faced(values)
            # Per-league usage (innings per start / relief appearance) and
            # the seasons that can make a pitcher card, from the index.
            g_i, gs_i = _PIT_IDX["G"], _PIT_IDX["GS"]
            usage: dict = {}
            years: dict[str, list[int]] = defaultdict(list)
            for (pid, year), stints in table.items():
                per_lg: dict[str, list[int]] = {}
                faced = 0
                for _team, lg, v in stints:
                    a = per_lg.setdefault(lg, [0, 0, 0])
                    a[0] += v[g_i] or 0
                    a[1] += v[gs_i] or 0
                    a[2] += v[_OUTS_I] or 0
                    faced += _batters_faced(v) - (v[_PIBB_I] or 0)
                if faced > 0:
                    years[pid].append(year)
                for lg, (g, gs, outs) in per_lg.items():
                    u = usage.get((year, lg))
                    if u is None:
                        u = usage[(year, lg)] = {"G": 0, "GS": 0, "IPouts": 0,
                                                 "relief_G": 0, "relief_IPouts": 0}
                    u["G"] += g
                    u["GS"] += gs
                    u["IPouts"] += outs
                    if gs == 0 and g >= 3:
                        u["relief_G"] += g
                        u["relief_IPouts"] += outs
            self._pitching_totals = totals
            self._pitching_usage = usage
            self._league_pit_hands = pit_hands
            self._pitching_years = {p: sorted(ys) for p, ys in years.items()}
            self._pitching = dict(table)

    def _load_fielding(self):
        if self._fielding is not None:
            return
        with self._lock:
            if self._fielding is not None:
                return
            self._load_pitching()   # pitchers' innings fill blank InnOuts
            table: dict = {}
            totals: dict = {}
            n = len(_FIELDING_STATS)
            cols = ["playerID", "yearID", "lgID", "POS"] + _FIELDING_STATS
            for source in ("Fielding", "FieldingOFsplit"):
                for row in self._read(source, cols):
                    pid = row[0]
                    year = int(row[1])
                    lg = intern(row[2] or "?")
                    pos = intern(row[3])
                    values = tuple(map(_int_or_none, row[4:]))
                    key = (year, lg, pos)
                    acc = totals.get(key)
                    if acc is None:
                        acc = totals[key] = _TotalsAcc(n)
                    acc.add(values)
                    entry = table.setdefault((pid, year), {})
                    old = entry.get(pos)
                    if old is not None:
                        values = tuple(map(_add, old[0], values))
                    entry[pos] = (values, lg)
            # Pitchers: InnOuts is blank for most of 1913-1954, so take the
            # innings from Pitching wherever the fielding row lacks them
            # (range for pitchers is chances per nine innings, not per game).
            inn_i = _FLD_IDX["InnOuts"]
            for (pid, year), entry in table.items():
                line = entry.get("P")
                if line is None or line[0][inn_i]:
                    continue
                stints = self._pitching.get((pid, year))
                if not stints:
                    continue
                outs = sum(s[2][_OUTS_I] or 0 for s in stints)
                if outs:
                    values = list(line[0])
                    values[inn_i] = outs
                    entry["P"] = (tuple(values), line[1])
            pools: dict[tuple[int, str], list] = defaultdict(list)
            for (pid, year), positions in table.items():
                for pos, (values, lg) in positions.items():
                    pools[(year, pos)].append((lg, values))
            appearances: dict = {}
            if self.table_path("Appearances") is not None:
                cols = ["playerID", "yearID"] + _APPEARANCE_FIELDS
                for row in self._read("Appearances", cols):
                    key = (row[0], int(row[1]))
                    values = tuple(_int_or_none(v) or 0 for v in row[2:])
                    old = appearances.get(key)
                    appearances[key] = (tuple(a + b for a, b in zip(old, values))
                                        if old else values)
            self._fielding_peer_pool = dict(pools)
            self._fielding_totals = totals
            self._appearances = appearances
            self._fielding = table

    def _load_teams(self):
        if self._team_names is not None:
            return
        with self._lock:
            if self._team_names is not None:
                return
            names = {}
            totals: dict = {}
            league_rg: dict[tuple[int, str], list[int]] = {}
            league_teams: dict[tuple[int, str], int] = {}
            n = len(_TEAM_FIELDS)
            cols = ["yearID", "lgID", "teamID", "name"] + _TEAM_FIELDS
            r_i, g_i = _TEAM_FIELDS.index("R"), _TEAM_FIELDS.index("G")
            for row in self._read("Teams", cols):
                year = int(row[0])
                key = (year, intern(row[1] or "?"))
                names[(year, row[2])] = row[3]
                values = tuple(map(_int_or_none, row[4:]))
                acc = totals.get(key)
                if acc is None:
                    acc = totals[key] = _TotalsAcc(n)
                acc.add(values)
                rg = league_rg.setdefault(key, [0, 0])
                rg[0] += values[r_i] or 0
                rg[1] += values[g_i] or 0
                league_teams[key] = league_teams.get(key, 0) + 1
            self._team_totals = totals
            self._league_rg = league_rg
            self._league_teams = league_teams
            self._team_names = names

    def _load_career(self):
        """Career workload (effective PA + batters faced) and first/last
        season per player: search ranking and missing debut dates."""
        if self._career is not None:
            return
        self._load_batting()
        self._load_pitching()
        with self._lock:
            if self._career is not None:
                return
            career: dict[str, int] = defaultdict(int)
            span: dict[str, list[int]] = {}
            for index, work in ((self._batting, _pa_eff),
                                (self._pitching, _batters_faced)):
                for (pid, year), stints in index.items():
                    career[pid] += sum(max(0, work(s[2])) for s in stints)
                    s = span.get(pid)
                    if s is None:
                        span[pid] = [year, year]
                    else:
                        s[0] = min(s[0], year)
                        s[1] = max(s[1], year)
            self._seasons_any = {p: (a, b) for p, (a, b) in span.items()}
            self._career = dict(career)

    def search_players(self, query: str, limit: int = 25, year: int | None = None,
                       kind: str | None = None) -> SearchResults:
        """Find players by name, best matches first.

        Matching ignores accents, case, punctuation and curly quotes, joins
        initials ('A.J.', 'A. J.', 'AJ') and drops a trailing Jr./Sr./II-IV.
        Every player is scored before the list is cut: exact full name,
        then every word matching a whole name word in any order ('Smith',
        'Mays Willie'), then word prefixes ('Pierz', 'Ken Grif'), then a
        plain substring; ties go to the bigger career (PA + batters faced),
        so the famous player of a common name comes first.

        `year` keeps only players with a card-ready season that year, and
        `kind` ('batter' / 'pitcher') only that kind of season; both apply
        before `limit`. The result is a list with `.total`, the number of
        players that matched.
        """
        self._load_people()
        self._load_career()
        q = _norm_name(query)
        results = SearchResults()
        if not q:
            return results
        q_tokens = q.split()
        tier: dict[str, int] = {}
        # An exact one-word match is no better than a whole-word one: the
        # nameless 'Smith' records must not outrank Ozzie Smith.
        for pid in self._full_index.get(q, []):
            tier[pid] = 0 if len(q_tokens) > 1 else 1
        for pid, key, tokens in self._name_keys:
            if pid in tier:
                continue
            if all(t in tokens for t in q_tokens):
                tier[pid] = 1
            elif all(any(n.startswith(t) for n in tokens) for t in q_tokens):
                tier[pid] = 2
            elif q in key:
                tier[pid] = 3

        def usable(pid: str) -> bool:
            bat = self._batting_years.get(pid, [])
            pit = self._pitching_years.get(pid, [])
            if kind == "batter":
                pools = (bat,)
            elif kind == "pitcher":
                pools = (pit,)
            else:
                pools = (bat, pit)
            if year is None:
                return any(pools)
            return any(year in p for p in pools)

        if year is not None or kind is not None:
            tier = {p: t for p, t in tier.items() if usable(p)}
        career = self._career
        ranked = sorted(tier, key=lambda p: (tier[p], -career.get(p, 0),
                                             self._people[p]["name"], p))
        for pid in ranked[:limit]:
            results.append(self._hit(pid))
        results.total = len(ranked)
        return results

    def _hit(self, pid: str) -> PlayerHit:
        person = self._people[pid]
        first, last = person["first_year"], person["last_year"]
        if first is None or last is None:
            span = self._seasons_any.get(pid)
            if span:
                first = first if first is not None else span[0]
                last = last if last is not None else span[1]
        return PlayerHit(
            player_id=pid, name=person["name"],
            first_year=first, last_year=last,
            bats=person["bats"], throws=person["throws"],
            batting_years=self._batting_years.get(pid, []),
            pitching_years=self._pitching_years.get(pid, []),
        )

    def player_name(self, player_id: str) -> str:
        self._load_people()
        return self._people.get(player_id, {}).get("name", player_id)

    def batting_years(self, player_id: str) -> list[int]:
        """Seasons that can generate a batter card (effective PA > 0).
        batting_season() still returns the stat line of other seasons."""
        self._load_batting()
        return self._batting_years.get(player_id, [])

    def pitching_years(self, player_id: str) -> list[int]:
        """Seasons that can generate a pitcher card (batters faced, net of
        intentional walks, > 0)."""
        self._load_pitching()
        return self._pitching_years.get(player_id, [])

    def player_info(self, player_id: str) -> dict:
        self._load_people()
        return dict(self._people.get(player_id, {}))

    # --- season stats -----------------------------------------------------

    @staticmethod
    def _aggregate(stints: list, fields: list[str]) -> tuple[dict, set, set]:
        """Sum stat fields across stints. Returns (stats, missing, partial):
        missing = recorded in no stint (summed as 0), partial = recorded in
        some stints only (the sum undercounts)."""
        stats: dict = {}
        missing: set = set()
        partial: set = set()
        for i, field in enumerate(fields):
            known = [stint[2][i] for stint in stints if stint[2][i] is not None]
            stats[field] = sum(known)
            if not known:
                missing.add(field)
            elif len(known) < len(stints):
                partial.add(field)
        return stats, missing, partial

    def batting_season(self, player_id: str, year: int) -> dict | None:
        """Aggregated batting line for a season (stints summed), or None."""
        self._load_batting()
        stints = self._batting.get((player_id, year))
        if not stints:
            return None
        stats, missing, partial = self._aggregate(stints, _BATTING_FIELDS)
        if any(self._batter_so_unrecorded(year, lg) for _t, lg, _v in stints):
            # Zero-filled or blank: not a measurement of this batter.
            missing.add("SO")
            partial.discard("SO")
        return self._finish_season(stats, missing, partial, stints, _pa_eff,
                                   _BAT_IDX["G"], player_id, year)

    def pitching_season(self, player_id: str, year: int) -> dict | None:
        self._load_pitching()
        stints = self._pitching.get((player_id, year))
        if not stints:
            return None
        stats, missing, partial = self._aggregate(stints, _PITCHING_FIELDS)
        outs = stats["IPouts"]
        stats["IP"] = InningsPitched(outs)
        stats["IP_display"] = innings_display(outs)
        stats["TBF"] = stats.pop("BFP")
        est = outs + stats["H"] + stats["BB"] + stats["HBP"]
        if "BFP" in partial or _plausible_bfp(stats["TBF"], est) is None:
            # A partial count would read 100 innings of hits as coming from
            # a handful of batters: estimate instead (the generator does
            # when TBF is 0).
            stats["TBF"] = 0
            partial.discard("BFP")
            missing.add("BFP")
        for old, new in (("IPouts", "IP"), ("BFP", "TBF")):
            for group in (missing, partial):
                if old in group:
                    group.discard(old)
                    group.add(new)
        if outs:
            stats["ERA"] = round(stats["ER"] * 27.0 / outs, 2)
        else:   # runs without an out recorded: an infinite ERA
            stats["ERA"] = None if stats["ER"] else 0.0
        return self._finish_season(stats, missing, partial, stints,
                                   _batters_faced, _PIT_IDX["G"], player_id, year)

    def _finish_season(self, stats, missing, partial, stints, work, g_index,
                       player_id, year):
        self._load_teams()
        weights: dict[str, int] = {}
        for _team, lg, values in stints:
            weights[lg] = weights.get(lg, 0) + max(0, work(values))
        if any(weights.values()):
            primary = max(weights, key=weights.get)
        else:   # no work recorded: the stint with the most games
            primary = max(stints, key=lambda s: s[2][g_index] or 0)[1]
        names = [self._team_names.get((year, s[0]), s[0]) for s in stints]
        stats["year"] = year
        stats["league"] = primary or "?"
        stats["league_weights"] = weights
        stats["team_ids"] = [s[0] for s in stints]
        stats["team"] = names[-1]       # the final team, as cards print it
        stats["teams"] = list(dict.fromkeys(names))
        stats["player_id"] = player_id
        stats["name"] = self.player_name(player_id)
        stats["multi_team"] = len(stints) > 1
        stats["missing"] = sorted(missing)
        stats["partial"] = sorted(partial)
        if stats.get("AB"):
            stats["BA"] = round(stats.get("H", 0) / stats["AB"], 3)
        return stats

    # --- fielding -----------------------------------------------------------

    def fielding_by_position(self, player_id: str, year: int) -> dict[str, dict]:
        """{position: fielding stats} for the season ('OF' combined plus
        'LF'/'CF'/'RF' corners where FieldingOFsplit has them: 1954+ for
        the AL/NL, scattered seasons before). A stat is None when the
        season didn't record it (PO/A/E for 1925 NNL/ECL, InnOuts for most
        of 1913-1954 — except pitchers, whose innings come from Pitching)."""
        self._load_fielding()
        entry = self._fielding.get((player_id, year), {})
        out = {}
        for pos, (values, lg) in entry.items():
            stats = dict(zip(_FIELDING_STATS, values))
            stats["lg"] = lg
            out[pos] = stats
        return out

    def fielding_peers(self, year: int, pos: str,
                       leagues=None) -> list[dict]:
        """All player fielding lines at a position in one season (for
        rating a player against contemporaries). `leagues` (an iterable of
        lgIDs) limits the pool to those leagues; None means every league.
        Each line carries its 'lg'."""
        self._load_fielding()
        lg_key = None if leagues is None else frozenset(leagues)
        key = (year, pos, lg_key)
        cached = self._fielding_peers_cache.get(key)
        if cached is None:
            cached = []
            for lg, values in self._fielding_peer_pool.get((year, pos), []):
                if lg_key is None or lg in lg_key:
                    line = dict(zip(_FIELDING_STATS, values))
                    line["lg"] = lg
                    cached.append(line)
            self._fielding_peers_cache[key] = cached
        return cached

    def fielding_leagues(self, year: int, pos: str) -> list[str]:
        """The leagues with fielding lines at a position in one season."""
        self._load_fielding()
        return sorted({lg for lg, _v in
                       self._fielding_peer_pool.get((year, pos), [])})

    def positions(self, player_id: str, year: int) -> list[tuple[str, int]]:
        """[(position, games)] for the season, most games first.

        Outfield is broken into LF/CF/RF where FieldingOFsplit has the
        season (AL/NL from 1954; before that only scattered Negro-league
        and independent seasons) or, when Appearances.csv is bundled, from
        its games by outfield spot; otherwise the combined 'OF' is
        reported. Such appearance-only corners have no fielding line:
        fielding.rate_position rates them on the combined 'OF' line.
        """
        self._load_fielding()
        entry = self._fielding.get((player_id, year), {})
        has_corners = any(p in entry for p in ("LF", "CF", "RF"))
        g_index = _FLD_IDX["G"]
        out = []
        for pos, (values, _lg) in entry.items():
            if pos == "OF" and has_corners:
                continue  # corners supersede the combined row
            out.append((pos, values[g_index] or 0))
        app = self._appearances.get((player_id, year))
        if "OF" in entry and not has_corners and app and any(app[:3]):
            out = [(p, g) for p, g in out if p != "OF"]
            out += [(p, g) for p, g in zip(("LF", "CF", "RF"), app[:3]) if g]
        return sorted(out, key=lambda kv: -kv[1])

    # --- league totals (pitching / fielding / teams) -----------------------

    def league_seasons(self) -> list[tuple[int, str]]:
        """Every (year, league) with batting, pitching or team rows."""
        self._load_batting()
        self._load_pitching()
        self._load_teams()
        return sorted(set(self._league_acc) | set(self._pitching_totals)
                      | set(self._team_totals))

    def league_pitching_totals(self, year: int, league: str) -> dict[str, StatTotal]:
        """League pitching totals from the Pitching rows of a (year, league):
        {field: StatTotal(total, rows recording it, rows)} for W, L, G, GS,
        CG, SHO, SV, IPouts, H, ER, HR, BB, SO, IBB, WP, HBP, BK, BFP, GF,
        R, SH, SF, GIDP. BFP leaves out implausible partial counts (as
        pitching_season does). Raises KeyError when the league-season has
        no pitching rows."""
        self._load_pitching()
        acc = self._pitching_totals.get((year, league))
        if acc is None:
            raise KeyError(f"no pitching data for {league} {year}")
        return acc.result(_PITCHING_FIELDS)

    def league_fielding_totals(self, year: int, league: str,
                               pos: str) -> dict[str, StatTotal]:
        """League fielding totals at one position from the Fielding rows
        (LF/CF/RF from FieldingOFsplit) of a (year, league): {field:
        StatTotal} for G, GS, InnOuts, PO, A, E, DP, PB, SB, CS. Raises
        KeyError when nobody played the position there."""
        self._load_fielding()
        acc = self._fielding_totals.get((year, league, pos))
        if acc is None:
            raise KeyError(f"no {pos} fielding data for {league} {year}")
        return acc.result(_FIELDING_STATS)

    def league_team_totals(self, year: int, league: str) -> dict[str, StatTotal]:
        """League totals from the Teams rows of a (year, league): {field:
        StatTotal} for G, Ghome, W, L, R, AB, H, 2B, 3B, HR, BB, SO, SB,
        CS, HBP, SF, RA, ER, CG, SHO, SV, IPouts, HA, HRA, BBA, SOA, E, DP
        (rows = teams). Raises KeyError when the league-season has no team
        rows."""
        self._load_teams()
        acc = self._team_totals.get((year, league))
        if acc is None:
            raise KeyError(f"no team data for {league} {year}")
        return acc.result(_TEAM_FIELDS)

    def league_pitching_usage(self, year: int, league: str) -> dict[str, int]:
        """How a league used its pitchers: {"G", "GS", "IPouts" (all
        pitchers), "relief_G", "relief_IPouts" (pure relievers: no starts
        and 3+ games in the league)}, each pitcher's stints in the league
        summed first. Raises KeyError when there are no pitching rows."""
        self._load_pitching()
        usage = self._pitching_usage.get((year, league))
        if usage is None:
            raise KeyError(f"no pitching data for {league} {year}")
        return dict(usage)

    def season_pitchers(self, year: int) -> dict[str, int]:
        """{player_id: games pitched} for everyone who pitched in a season
        (all leagues). Empty for a year without pitching rows."""
        self._load_pitching()
        if self._season_pitchers is None:
            with self._lock:
                if self._season_pitchers is None:
                    g_i = _PIT_IDX["G"]
                    by_year: dict[int, dict[str, int]] = defaultdict(dict)
                    for (pid, y), stints in self._pitching.items():
                        by_year[y][pid] = sum(s[2][g_i] or 0 for s in stints)
                    self._season_pitchers = dict(by_year)
        return dict(self._season_pitchers.get(year, {}))

    def season_league(self, stats: dict) -> dict:
        """The league baseline for a batting_season / pitching_season dict:
        league_batting of the player's league or, when he played in several
        leagues (traded across leagues, or MLB plus a Negro league), the
        blend of their rates weighted by his work in each (stats
        ['league_weights']). A blend carries 'league' = his primary league,
        'blend' = {league: share}, summed warnings, and 'raw' totals scaled
        so every raw ratio is the weighted blend too."""
        year = stats["year"]
        weights = {lg: w for lg, w in (stats.get("league_weights") or {}).items()
                   if w > 0 and (year, lg) in self._league_keys()}
        if len(weights) <= 1:
            return self.league_batting(year, stats["league"])
        total = sum(weights.values())
        parts = [(w / total, self.league_batting(year, lg))
                 for lg, w in weights.items()]
        pa = sum(s * lg["PA_eff"] for s, lg in parts)
        blended = {"year": year, "league": stats["league"], "PA_eff": pa,
                   "blend": {lg["league"]: s for s, lg in parts}}
        for key in ("H_per_PA", "1B_per_PA", "2B_per_PA", "3B_per_PA",
                    "HR_per_PA", "BB_per_PA", "K_per_PA", "HBP_per_PA"):
            blended[key] = sum(s * lg[key] for s, lg in parts)
        raw: dict = {}
        for s, lg in parts:
            scale = s * pa / lg["PA_eff"] if lg["PA_eff"] else 0.0
            for field, value in lg["raw"].items():
                raw[field] = raw.get(field, 0.0) + scale * value
        blended["raw"] = raw
        blended["BA"] = raw["H"] / raw["AB"] if raw.get("AB") else 0.0
        blended["batter_so_unrecorded"] = any(
            lg["batter_so_unrecorded"] for _s, lg in parts)
        blended["warnings"] = list(dict.fromkeys(
            w for _s, lg in parts for w in lg["warnings"]))
        return blended

    def _league_keys(self):
        self._load_batting()
        return self._league_acc

    # --- random pick --------------------------------------------------------

    def random_season(self, rng: random.Random | None = None,
                      ) -> tuple[str, int, str]:
        """A uniformly random substantial player-season.

        Returns (player_id, year, kind) where kind is 'batter' or
        'pitcher'. Only meaty seasons qualify: 150+ effective PA (AB + BB
        - IBB + HBP + SF) batting, or 200+ batters faced pitching (estimated
        from innings, hits and walks where not recorded). The card always
        generates, but seasons from eras that didn't track every stat
        still carry those notes (and extreme seasons their own warnings).
        """
        if self._random_pool is None:
            self._load_batting()
            self._load_pitching()
            pool: list[tuple[str, int, str]] = []
            for (pid, year), stints in self._batting.items():
                if sum(_pa_eff(s[2]) for s in stints) >= 150:
                    pool.append((pid, year, "batter"))
            for (pid, year), stints in self._pitching.items():
                if sum(_batters_faced(s[2]) for s in stints) >= 200:
                    pool.append((pid, year, "pitcher"))
            self._random_pool = pool
        return (rng or random).choice(self._random_pool)

    # --- handedness (platoon matchups) --------------------------------------

    def league_handedness(self, year: int, league: str) -> dict:
        """Who faced whom in a (year, league), by hand.

        Returns {"pitchers": {"L", "R"} shares of batters faced, "batters":
        {"L", "R", "S"} shares of effective PA ('S' = switch hitter,
        People.bats 'B'), "pitcher_coverage"/"batter_coverage": the share
        of each total whose hand is known}. Unknown hands are left out of
        the shares; a share dict is empty when no hand is known at all.
        Raises KeyError when the year/league has no data.
        """
        self._load_batting()
        self._load_pitching()
        bat = self._league_bat_hands.get((year, league))
        pit = self._league_pit_hands.get((year, league))
        if bat is None and pit is None:
            raise KeyError(f"no data for {league} {year}")

        def shares(counts, labels):
            counts = counts or [0] * (len(labels) + 1)
            known = sum(counts[:-1])
            total = known + counts[-1]
            dist = ({h: c / known for h, c in zip(labels, counts)}
                    if known else {})
            return dist, (known / total if total else 0.0)

        pitchers, pcov = shares(pit, _PIT_HANDS[:-1])
        batters, bcov = shares(bat, _BAT_HANDS[:-1])
        return {"pitchers": pitchers, "pitcher_coverage": pcov,
                "batters": batters, "batter_coverage": bcov}

    def league_batter_lines(self, year: int, league: str,
                            ) -> list[tuple[str, int, int, int]]:
        """Every batter who appeared in a (year, league), as compact
        (bats, PA in this league, season PA, season HR) tuples.

        Season PA/HR sum all of the player's stints that year (what his
        card is built from); PA in this league weights him in league
        aggregates. PA are effective PA (AB + BB - IBB + HBP + SF). Scans
        the batting index, so callers should cache the result.
        """
        self._load_batting()
        hr_i = _BAT_IDX["HR"]
        out = []
        for (pid, y), stints in self._batting.items():
            if y != year:
                continue
            in_lg = sum(_pa_eff(v) for _t, lg, v in stints if lg == league)
            if in_lg <= 0:
                continue
            season_pa = sum(_pa_eff(v) for _t, _lg, v in stints)
            season_hr = sum(v[hr_i] or 0 for _t, _lg, v in stints)
            bats = self._people.get(pid, {}).get("bats", "?")
            out.append((bats, in_lg, season_pa, season_hr))
        return out

    # --- league averages ---------------------------------------------------

    def leagues_for_year(self, year: int) -> list[str]:
        self._load_batting()
        return sorted(self._year_leagues.get(year, set()))

    def max_year(self) -> int:
        self._load_batting()
        return max(self._year_leagues)

    def league_runs_per_game(self, year: int, league: str) -> float:
        """Actual league runs per team-game (for game-dynamics validation)."""
        self._load_teams()
        runs, games = self._league_rg.get((year, league), (0, 0))
        if not games:
            raise KeyError(f"no team data for {league} {year}")
        return runs / games

    def league_games_per_team(self, year: int, league: str) -> float:
        """Average schedule length (games per team) of a (year, league).
        Raises KeyError when the league has no team data."""
        self._load_teams()
        games = self._league_rg.get((year, league), (0, 0))[1]
        teams = self._league_teams.get((year, league), 0)
        if not games or not teams:
            raise KeyError(f"no team data for {league} {year}")
        return games / teams

    def _batter_so_unrecorded(self, year: int, league: str) -> bool:
        """True when a league's batting strikeouts aren't a real record:
        blank or zero-filled (under 80% of its pitchers' strikeouts, or
        carried by under half its PA) while its pitchers' were kept."""
        acc = self._league_acc.get((year, league))
        if acc is None:
            return False
        self._load_pitching()
        pit = self._pitching_totals.get((year, league))
        pit_so = pit.sums[_PIT_IDX["SO"]] if pit is not None else 0
        sums, cover, (pa,) = acc
        so_i = _BAT_IDX["SO"]
        recorded = cover[so_i] >= _TRACKED_COVERAGE * pa if pa > 0 else sums[so_i] > 0
        return pit_so > 0 and (sums[so_i] < _SO_RECORDED_SHARE * pit_so
                               or not recorded)

    def _baseline_pool(self, year: int, league: str) -> tuple[list, str]:
        """The (year, league) keys a league average is built from, and a
        description when that isn't just the league itself: leagues under
        MIN_LEAGUE_PA (a few independent clubs; 1894 IND has 42 PA) pool
        with the year's comparable leagues (other Negro/independent ones,
        or the majors), then neighboring seasons of those, then the whole
        year."""
        def pa(keys):
            return sum(self._league_acc[k][2][0] for k in keys)

        own = [(year, league)]
        if pa(own) >= MIN_LEAGUE_PA:
            return own, ""
        major = league in MAJOR_LEAGUES
        same_kind = [(year, lg) for lg in sorted(self._year_leagues.get(year, ()))
                     if (lg in MAJOR_LEAGUES) == major]
        if pa(same_kind) >= MIN_LEAGUE_PA:
            kind = "major" if major else "Negro-league/independent"
            return same_kind, f"all {year} {kind} leagues"
        for radius in (1, 2, 3):
            keys = [(y, lg) for y in range(year - radius, year + radius + 1)
                    for lg in sorted(self._year_leagues.get(y, ()))
                    if (lg in MAJOR_LEAGUES) == major]
            if pa(keys) >= MIN_LEAGUE_PA:
                kind = "major" if major else "Negro-league/independent"
                return keys, (f"{kind} leagues of {year - radius}-"
                              f"{year + radius}")
        keys = [(year, lg) for lg in sorted(self._year_leagues.get(year, ()))]
        return keys, f"all {year} leagues"

    def _league_rates(self, year: int, league: str) -> dict:
        keys, pooled = self._baseline_pool(year, league)
        n = len(_BATTING_FIELDS)
        sums, cover, pa_total = [0] * n, [0] * n, 0
        pit_so = 0
        for key in keys:
            s, c, (p,) = self._league_acc[key]
            sums = [a + b for a, b in zip(sums, s)]
            cover = [a + b for a, b in zip(cover, c)]
            pa_total += p
            acc = self._pitching_totals.get(key)
            if acc is not None:
                pit_so += acc.sums[_PIT_IDX["SO"]]
        totals = dict(zip(_BATTING_FIELDS, sums))
        tracked = {f: (c >= _TRACKED_COVERAGE * pa_total if pa_total > 0
                       else s > 0)
                   for f, s, c in zip(_BATTING_FIELDS, sums, cover)}

        warnings = []
        if pooled:
            warnings.append(
                f"{league} {year} is too small for a reliable league average "
                f"({self._league_acc[(year, league)][2][0]:,} PA): "
                f"using {pooled}")
        so_unrecorded = pit_so > 0 and (
            totals["SO"] < _SO_RECORDED_SHARE * pit_so or not tracked["SO"])
        if so_unrecorded:
            totals["SO_batting"] = totals["SO"]
            totals["SO"] = pit_so
            tracked["SO"] = True
            warnings.append(
                f"batter strikeouts weren't recorded in {league} {year}: the "
                f"league strikeout rate comes from its pitchers' totals")
        warnings += [f"{f} not tracked in {league} {year} (treated as 0)"
                     for f in ("IBB", "SF", "HBP", "SO", "SB", "CS")
                     if not tracked[f]]
        pa_eff = (totals["AB"] + (totals["BB"] - totals["IBB"])
                  + totals["HBP"] + totals["SF"])
        singles = totals["H"] - totals["2B"] - totals["3B"] - totals["HR"]
        return {
            "year": year,
            "league": league,
            "PA_eff": pa_eff,
            "BA": totals["H"] / totals["AB"] if totals["AB"] else 0.0,
            "H_per_PA": totals["H"] / pa_eff,
            "1B_per_PA": singles / pa_eff,
            "2B_per_PA": totals["2B"] / pa_eff,
            "3B_per_PA": totals["3B"] / pa_eff,
            "HR_per_PA": totals["HR"] / pa_eff,
            "BB_per_PA": (totals["BB"] - totals["IBB"]) / pa_eff,
            "K_per_PA": totals["SO"] / pa_eff,
            "HBP_per_PA": totals["HBP"] / pa_eff,
            "raw": totals,
            "tracked": tracked,
            "batter_so_unrecorded": (so_unrecorded
                                     or self._batter_so_unrecorded(year, league)),
            "pooled_from": keys if pooled else [],
            "warnings": warnings,
        }

    def league_batting(self, year: int, league: str) -> dict:
        """League-wide batting rates for a (year, league).

        Returns rates per effective PA plus the raw totals, 'tracked'
        ({stat: recorded on at least half the league's PA}), warnings for
        stats that weren't tracked that year, and two era flags:
        'batter_so_unrecorded' (batting strikeouts blank or zero-filled —
        the 19th-century AA/UA and most Negro-league seasons — so K_per_PA
        and raw['SO'] come from the league's pitching strikeouts, with the
        batting sum kept as raw['SO_batting']) and 'pooled_from' (the
        (year, league) keys of a pooled baseline, for leagues under
        MIN_LEAGUE_PA). Raises KeyError when the year/league combination
        has no data.
        """
        key = (year, league)
        if key in self._league_totals:
            return self._league_totals[key]
        self._load_batting()
        self._load_pitching()
        if key not in self._league_acc:
            raise KeyError(f"no batting data for {league} {year}")
        result = self._league_rates(year, league)
        self._league_totals[key] = result
        return result


@lru_cache(maxsize=1)
def default_db() -> LahmanDB:
    return LahmanDB()
