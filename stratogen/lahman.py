"""Offline baseball statistics from the Lahman database (1871-2025).

Reads the gzipped CSVs in data/lahman/ (Batting, Pitching, People, Teams,
Fielding, FieldingOFsplit). Everything works offline; no scraping. League
averages are computed per (year, league) by aggregating every player row,
so any year/league combination present in the data is supported — all eras.

Rows are converted to compact tuples of ints at load time (raw CSV row
dicts cost ~500 MB of resident memory; this representation costs ~a tenth
of that) and league totals, player-year indexes, and fielding peer pools
are built in the same pass, so nothing ever rescans a table.

To update for a new season: download the latest CSV release from
https://sabr.org/lahman-database/ and replace the .csv.gz files.
"""

from __future__ import annotations

import csv
import gzip
import random
import threading
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "lahman"

# Stats summed across a player's stints in one season
_BATTING_FIELDS = ["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS",
                   "BB", "SO", "IBB", "HBP", "SH", "SF", "GIDP"]
_PITCHING_FIELDS = ["W", "L", "G", "GS", "CG", "SHO", "SV", "IPouts", "H", "ER",
                    "HR", "BB", "SO", "IBB", "WP", "HBP", "BK", "BFP", "GF", "R",
                    "SH", "SF", "GIDP"]
# Fielding stats kept per position (stints summed)
_FIELDING_STATS = ["G", "GS", "InnOuts", "PO", "A", "E", "DP", "PB", "SB", "CS"]

_BAT_IDX = {f: i for i, f in enumerate(_BATTING_FIELDS)}
_PIT_IDX = {f: i for i, f in enumerate(_PITCHING_FIELDS)}

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


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _int_or_none(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


@dataclass
class PlayerHit:
    player_id: str
    name: str
    first_year: int | None
    last_year: int | None
    bats: str
    throws: str
    batting_years: list[int]
    pitching_years: list[int]


class LahmanDB:
    """Lazy-loading access layer over the Lahman CSVs."""

    def __init__(self, data_dir: str | Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        self._lock = threading.RLock()
        self._people: dict[str, dict] | None = None
        self._name_index: dict[str, list[str]] | None = None
        # (pid, year) -> list of stints (teamID, lgID, values tuple)
        self._batting: dict | None = None
        self._pitching: dict | None = None
        self._batting_years: dict[str, list[int]] = {}
        self._pitching_years: dict[str, list[int]] = {}
        # (year, lg) -> ([sums per _BATTING_FIELDS], [tracked flags])
        self._league_acc: dict[tuple[int, str], tuple[list, list]] = {}
        self._year_leagues: dict[int, set] = {}
        # (pid, year) -> {pos: (values tuple, lg)}
        self._fielding: dict | None = None
        self._fielding_peer_pool: dict[tuple[int, str], list] = {}
        self._fielding_peers_cache: dict[tuple[int, str], list[dict]] = {}
        self._team_names: dict[tuple[int, str], str] | None = None
        self._league_rg: dict[tuple[int, str], list[int]] = {}
        self._league_teams: dict[tuple[int, str], int] = {}
        self._league_totals: dict[tuple[int, str], dict] = {}
        # (year, lg) -> effective PA by batter hand (_BAT_HANDS order) and
        # batters faced by pitcher hand (_PIT_HANDS order): the platoon
        # matchup frequencies, built in the same single load pass.
        self._league_bat_hands: dict[tuple[int, str], list[int]] = {}
        self._league_pit_hands: dict[tuple[int, str], list[int]] = {}
        self._random_pool: list[tuple[str, int, str]] | None = None

    def _rows(self, table: str):
        path = self.data_dir / f"{table}.csv.gz"
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as fh:
            yield from csv.DictReader(fh)

    def warm(self):
        """Load everything up front (e.g. in a background thread)."""
        self._load_people()
        self._load_batting()
        self._load_pitching()
        self._load_fielding()
        self._load_teams()

    # --- people / search -------------------------------------------------

    def _load_people(self):
        with self._lock:
            if self._people is not None:
                return
            people: dict[str, dict] = {}
            index: dict[str, list[str]] = defaultdict(list)
            for row in self._rows("People"):
                pid = row["playerID"]
                if not pid:
                    continue
                name = f"{row.get('nameFirst', '')} {row.get('nameLast', '')}".strip()
                debut = row.get("debut") or ""
                final = row.get("finalGame") or ""
                people[pid] = {
                    "name": name or pid,
                    "bats": row.get("bats") or "?",
                    "throws": row.get("throws") or "?",
                    "first_year": int(debut[:4]) if debut[:4].isdigit() else None,
                    "last_year": int(final[:4]) if final[:4].isdigit() else None,
                }
                index[_norm_name(name)].append(pid)
                last = _norm_name(row.get("nameLast") or "")
                if last:
                    index[last].append(pid)
            self._people = people
            self._name_index = dict(index)

    def _load_batting(self):
        with self._lock:
            if self._batting is not None:
                return
            self._load_people()  # hands are accumulated in this pass
            people = self._people
            table: dict = defaultdict(list)
            years: dict[str, set] = defaultdict(set)
            for row in self._rows("Batting"):
                pid = row["playerID"]
                year = int(row["yearID"])
                lg = row["lgID"]
                values = tuple(_int_or_none(row.get(f, ""))
                               for f in _BATTING_FIELDS)
                table[(pid, year)].append((row["teamID"], lg, values))
                years[pid].add(year)
                hands = self._league_bat_hands.setdefault(
                    (year, lg), [0] * len(_BAT_HANDS))
                bats = people.get(pid, {}).get("bats", "?")
                hands[_BAT_HAND_IDX.get(bats, 3)] += _pa_eff(values)
                sums, tracked = self._league_acc.setdefault(
                    (year, lg), ([0] * len(_BATTING_FIELDS),
                                 [False] * len(_BATTING_FIELDS)))
                for i, v in enumerate(values):
                    if v is not None:
                        sums[i] += v
                        tracked[i] = True
                self._year_leagues.setdefault(year, set()).add(lg)
            self._batting = dict(table)
            self._batting_years = {p: sorted(ys) for p, ys in years.items()}

    def _load_pitching(self):
        with self._lock:
            if self._pitching is not None:
                return
            self._load_people()  # hands are accumulated in this pass
            people = self._people
            bfp_i = _PIT_IDX["BFP"]
            est_i = [_PIT_IDX[k] for k in ("IPouts", "H", "BB")]
            table: dict = defaultdict(list)
            years: dict[str, set] = defaultdict(set)
            for row in self._rows("Pitching"):
                pid = row["playerID"]
                year = int(row["yearID"])
                values = tuple(_int_or_none(row.get(f, ""))
                               for f in _PITCHING_FIELDS)
                table[(pid, year)].append((row["teamID"], row["lgID"], values))
                years[pid].add(year)
                # Batters faced; where BFP wasn't tracked, estimate it the
                # way pitching rates do (3 per inning + hits + walks).
                bfp = values[bfp_i] or sum(values[i] or 0 for i in est_i)
                hands = self._league_pit_hands.setdefault(
                    (year, row["lgID"]), [0] * len(_PIT_HANDS))
                throws = people.get(pid, {}).get("throws", "?")
                hands[_PIT_HAND_IDX.get(throws, 2)] += bfp
            self._pitching = dict(table)
            self._pitching_years = {p: sorted(ys) for p, ys in years.items()}

    def _load_fielding(self):
        with self._lock:
            if self._fielding is not None:
                return
            table: dict = {}

            def add(pid: str, year: int, pos: str, row: dict):
                entry = table.setdefault((pid, year), {})
                old = entry.get(pos)
                values = [_int_or_none(row.get(f, "")) or 0
                          for f in _FIELDING_STATS]
                if old is not None:
                    values = [a + b for a, b in zip(old[0], values)]
                entry[pos] = (values, row.get("lgID") or "?")

            for row in self._rows("Fielding"):
                add(row["playerID"], int(row["yearID"]), row["POS"], row)
            for row in self._rows("FieldingOFsplit"):
                add(row["playerID"], int(row["yearID"]), row["POS"], row)
            pools: dict[tuple[int, str], list] = defaultdict(list)
            for (pid, year), positions in table.items():
                for pos, (values, _lg) in positions.items():
                    pools[(year, pos)].append(values)
            self._fielding = table
            self._fielding_peer_pool = dict(pools)

    def _load_teams(self):
        with self._lock:
            if self._team_names is not None:
                return
            names = {}
            league_rg: dict[tuple[int, str], list[int]] = {}
            league_teams: dict[tuple[int, str], int] = {}
            for row in self._rows("Teams"):
                year = int(row["yearID"])
                names[(year, row["teamID"])] = row["name"]
                acc = league_rg.setdefault((year, row["lgID"]), [0, 0])
                acc[0] += _int_or_none(row.get("R", "")) or 0
                acc[1] += _int_or_none(row.get("G", "")) or 0
                key = (year, row["lgID"])
                league_teams[key] = league_teams.get(key, 0) + 1
            self._league_rg = league_rg
            self._league_teams = league_teams
            self._team_names = names

    def search_players(self, query: str, limit: int = 25) -> list[PlayerHit]:
        """Find players by full name, last name, or substring."""
        self._load_people()
        self._load_batting()
        self._load_pitching()
        q = _norm_name(query)
        ids: list[str] = []
        seen = set()
        for pid in self._name_index.get(q, []):
            if pid not in seen:
                ids.append(pid)
                seen.add(pid)
        if not ids:  # substring fallback
            for name_key, pids in self._name_index.items():
                if q in name_key:
                    for pid in pids:
                        if pid not in seen:
                            ids.append(pid)
                            seen.add(pid)
                if len(ids) >= limit * 2:
                    break
        hits = []
        for pid in ids[: limit * 2]:
            person = self._people[pid]
            hits.append(PlayerHit(
                player_id=pid, name=person["name"],
                first_year=person["first_year"], last_year=person["last_year"],
                bats=person["bats"], throws=person["throws"],
                batting_years=self._batting_years.get(pid, []),
                pitching_years=self._pitching_years.get(pid, []),
            ))
        hits.sort(key=lambda h: (h.first_year or 9999))
        return hits[:limit]

    def player_name(self, player_id: str) -> str:
        self._load_people()
        return self._people.get(player_id, {}).get("name", player_id)

    def batting_years(self, player_id: str) -> list[int]:
        self._load_batting()
        return self._batting_years.get(player_id, [])

    def pitching_years(self, player_id: str) -> list[int]:
        self._load_pitching()
        return self._pitching_years.get(player_id, [])

    def player_info(self, player_id: str) -> dict:
        self._load_people()
        return dict(self._people.get(player_id, {}))

    # --- season stats -----------------------------------------------------

    @staticmethod
    def _aggregate(stints: list, fields: list[str]) -> tuple[dict, set]:
        """Sum stat fields across stints. Returns (stats, missing_fields)."""
        stats: dict = {}
        missing: set = set()
        for i, field in enumerate(fields):
            values = [stint[2][i] for stint in stints]
            if all(v is None for v in values):
                stats[field] = 0
                missing.add(field)
            else:
                stats[field] = sum(v or 0 for v in values)
        return stats, missing

    def batting_season(self, player_id: str, year: int) -> dict | None:
        """Aggregated batting line for a season (stints summed), or None."""
        self._load_batting()
        stints = self._batting.get((player_id, year))
        if not stints:
            return None
        stats, missing = self._aggregate(stints, _BATTING_FIELDS)
        return self._finish_season(stats, missing, stints,
                                   _BAT_IDX["G"], player_id, year)

    def pitching_season(self, player_id: str, year: int) -> dict | None:
        self._load_pitching()
        stints = self._pitching.get((player_id, year))
        if not stints:
            return None
        stats, missing = self._aggregate(stints, _PITCHING_FIELDS)
        stats["IP"] = round(stats.pop("IPouts", 0) / 3.0, 1)
        stats["TBF"] = stats.pop("BFP", 0)
        if "IPouts" in missing:
            missing.discard("IPouts")
            missing.add("IP")
        if "BFP" in missing:
            missing.discard("BFP")
            missing.add("TBF")
        # ERA from aggregated ER/IP
        stats["ERA"] = round(stats["ER"] * 9.0 / stats["IP"], 2) if stats["IP"] else 0.0
        return self._finish_season(stats, missing, stints,
                                   _PIT_IDX["G"], player_id, year)

    def _finish_season(self, stats, missing, stints, g_index, player_id, year):
        self._load_teams()
        # league/team: take from the stint with the most games
        biggest = max(stints, key=lambda s: s[2][g_index] or 0)
        stats["year"] = year
        stats["league"] = biggest[1] or "?"
        stats["team_ids"] = [s[0] for s in stints]
        stats["team"] = self._team_names.get((year, biggest[0]), biggest[0])
        stats["player_id"] = player_id
        stats["name"] = self.player_name(player_id)
        stats["multi_team"] = len(stints) > 1
        stats["missing"] = sorted(missing)
        if stats.get("AB"):
            stats["BA"] = round(stats.get("H", 0) / stats["AB"], 3)
        return stats

    # --- fielding -----------------------------------------------------------

    def fielding_by_position(self, player_id: str, year: int) -> dict[str, dict]:
        """{position: fielding stats} for the season ('OF' combined plus
        'LF'/'CF'/'RF' corners where the era has them)."""
        self._load_fielding()
        entry = self._fielding.get((player_id, year), {})
        out = {}
        for pos, (values, lg) in entry.items():
            stats = dict(zip(_FIELDING_STATS, values))
            stats["lg"] = lg
            out[pos] = stats
        return out

    def fielding_peers(self, year: int, pos: str) -> list[dict]:
        """All player fielding lines at a position in one season (for
        rating a player against contemporaries)."""
        self._load_fielding()
        key = (year, pos)
        if key not in self._fielding_peers_cache:
            self._fielding_peers_cache[key] = [
                dict(zip(_FIELDING_STATS, values))
                for values in self._fielding_peer_pool.get(key, [])]
        return self._fielding_peers_cache[key]

    def positions(self, player_id: str, year: int) -> list[tuple[str, int]]:
        """[(position, games)] for the season, most games first.

        Outfield is broken into LF/CF/RF when the era's data allows
        (1891+); otherwise the combined 'OF' is reported.
        """
        self._load_fielding()
        entry = self._fielding.get((player_id, year), {})
        has_corners = any(p in entry for p in ("LF", "CF", "RF"))
        g_index = _FIELDING_STATS.index("G")
        out = []
        for pos, (values, _lg) in entry.items():
            if pos == "OF" and has_corners:
                continue  # corners supersede the combined row
            out.append((pos, values[g_index]))
        return sorted(out, key=lambda kv: -kv[1])

    # --- random pick --------------------------------------------------------

    def random_season(self, rng: random.Random | None = None,
                      ) -> tuple[str, int, str]:
        """A uniformly random substantial player-season.

        Returns (player_id, year, kind) where kind is 'batter' or
        'pitcher'. Only meaty seasons qualify (roughly 150+ PA batting,
        200+ batters faced pitching) so the result always generates a
        warning-free card.
        """
        if self._random_pool is None:
            self._load_batting()
            self._load_pitching()
            ab_i, bb_i = _BAT_IDX["AB"], _BAT_IDX["BB"]
            bfp_i, ipouts_i = _PIT_IDX["BFP"], _PIT_IDX["IPouts"]
            pool: list[tuple[str, int, str]] = []
            for (pid, year), stints in self._batting.items():
                pa = sum((s[2][ab_i] or 0) + (s[2][bb_i] or 0) for s in stints)
                if pa >= 150:
                    pool.append((pid, year, "batter"))
            for (pid, year), stints in self._pitching.items():
                bfp = sum(s[2][bfp_i] or 0 for s in stints)
                ipouts = sum(s[2][ipouts_i] or 0 for s in stints)
                if bfp >= 200 or (bfp == 0 and ipouts >= 150):
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

    def league_batting(self, year: int, league: str) -> dict:
        """League-wide batting rates for a (year, league).

        Returns rates per effective PA plus the raw totals and warnings for
        stats that weren't tracked that year. Raises KeyError when the
        year/league combination has no data.
        """
        key = (year, league)
        if key in self._league_totals:
            return self._league_totals[key]
        self._load_batting()
        if key not in self._league_acc:
            raise KeyError(f"no batting data for {league} {year}")
        sums, tracked_flags = self._league_acc[key]
        totals = dict(zip(_BATTING_FIELDS, sums))
        tracked = dict(zip(_BATTING_FIELDS, tracked_flags))

        warnings = [f"{f} not tracked in {league} {year} (treated as 0)"
                    for f in ("IBB", "SF", "HBP", "SO", "CS")
                    if not tracked[f]]
        pa_eff = (totals["AB"] + (totals["BB"] - totals["IBB"])
                  + totals["HBP"] + totals["SF"])
        singles = totals["H"] - totals["2B"] - totals["3B"] - totals["HR"]
        result = {
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
            "warnings": warnings,
        }
        self._league_totals[key] = result
        return result


@lru_cache(maxsize=1)
def default_db() -> LahmanDB:
    return LahmanDB()
