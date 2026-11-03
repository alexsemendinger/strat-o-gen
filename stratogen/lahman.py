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

    # --- teams / rosters ------------------------------------------------------
    #
    # Read-only views for the product layer (web app, CLI, team sets): career
    # summaries, name autocomplete, season roles, teams and rosters. Each
    # index is built once from the compact tables above (plus one small
    # read of Teams for W-L) and cached on the instance, so requests never
    # rescan anything. Attributes are created lazily here so this section
    # stays self-contained.

    _SUGGEST_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv"})

    def warm_rosters(self):
        """Build this section's indexes up front (career table, name
        autocomplete, teams, rosters), e.g. in a background thread."""
        self._career_table()
        self._suggest_index()
        self._team_table()
        self._roster_index()

    @staticmethod
    def _suggest_tokens(text: str) -> list[str]:
        """Name tokens for autocomplete: accents, case, dots, apostrophes
        (straight or curly) and commas dropped; hyphens split; runs of
        single-letter initials joined ('A. J.' -> 'aj'); Jr/Sr/II.. dropped."""
        s = unicodedata.normalize("NFKD", text or "")
        s = "".join(c for c in s if not unicodedata.combining(c)).lower()
        for ch in ".'’‘`,":
            s = s.replace(ch, " " if ch in ".," else "")
        s = s.replace("-", " ")
        raw = [t for t in s.split() if t]
        tokens: list[str] = []
        run = ""
        for t in raw:
            if len(t) == 1 and t.isalpha():
                run += t
                continue
            if run:
                tokens.append(run)
                run = ""
            tokens.append(t)
        if run:
            tokens.append(run)
        return [t for t in tokens if t not in LahmanDB._SUGGEST_SUFFIXES] or tokens

    @staticmethod
    def _season_pitch_bf(stints: list) -> int:
        """Batters faced minus IBB, the way pitching rates count them
        (BFP, or 3 per inning + hits + walks where BFP wasn't kept)."""
        bfp = sum(s[2][_PIT_IDX["BFP"]] or 0 for s in stints)
        if not bfp:
            bfp = sum((s[2][_PIT_IDX["IPouts"]] or 0) + (s[2][_PIT_IDX["H"]] or 0)
                      + (s[2][_PIT_IDX["BB"]] or 0) for s in stints)
        return bfp - sum(s[2][_PIT_IDX["IBB"]] or 0 for s in stints)

    def _career_table(self) -> dict:
        """pid -> [PA, BF, batting G, pitching G, playable batting years,
        playable pitching years]. 'Playable' = a card can be made: some
        effective plate appearances / batters faced that season."""
        table = getattr(self, "_career_cache", None)
        if table is not None:
            return table
        with self._lock:
            table = getattr(self, "_career_cache", None)
            if table is not None:
                return table
            self._load_batting()
            self._load_pitching()
            bat_g, pit_g = _BAT_IDX["G"], _PIT_IDX["G"]
            table = {}
            for (pid, year), stints in self._batting.items():
                entry = table.setdefault(pid, [0, 0, 0, 0, [], []])
                pa = sum(_pa_eff(s[2]) for s in stints)
                entry[0] += max(pa, 0)
                entry[2] += sum(s[2][bat_g] or 0 for s in stints)
                if pa > 0:
                    entry[4].append(year)
            for (pid, year), stints in self._pitching.items():
                entry = table.setdefault(pid, [0, 0, 0, 0, [], []])
                bf = self._season_pitch_bf(stints)
                entry[1] += max(bf, 0)
                entry[3] += sum(s[2][pit_g] or 0 for s in stints)
                if bf > 0:
                    entry[5].append(year)
            for entry in table.values():
                entry[4].sort()
                entry[5].sort()
            self._career_cache = table
            return table

    def playable_years(self, player_id: str, kind: str) -> list[int]:
        """Seasons that make a card of this kind ('batter'/'pitcher'):
        only seasons with effective PA (or batters faced) above zero."""
        entry = self._career_table().get(player_id)
        if not entry:
            return []
        return list(entry[4] if kind == "batter" else entry[5])

    @staticmethod
    def _role(pa: int, bf: int, bat_g: int, pitch_g: int) -> str | None:
        """'pitcher' when pitching games outnumber the other games played
        (batting G counts every game, pitching ones included), else
        'batter'; volume decides when games weren't recorded."""
        if bf <= 0:
            return "batter" if pa > 0 else None
        if pa <= 0:
            return "pitcher"
        if bat_g or pitch_g:
            return "pitcher" if 2 * pitch_g > bat_g else "batter"
        return "pitcher" if bf > pa else "batter"

    def primary_role(self, player_id: str, year: int | None = None) -> str | None:
        """'batter' or 'pitcher': what the player mostly was that season
        (or over his career when year is None). None without usable stats.
        Ohtani and Ruth from 1918 are batters; a pitcher who batted is a
        pitcher; a position player's mop-up inning doesn't count."""
        if year is None:
            entry = self._career_table().get(player_id)
            if not entry:
                return None
            return self._role(entry[0], entry[1], entry[2], entry[3])
        self._load_batting()
        self._load_pitching()
        bat = self._batting.get((player_id, year)) or []
        pit = self._pitching.get((player_id, year)) or []
        pa = sum(_pa_eff(s[2]) for s in bat)
        bf = self._season_pitch_bf(pit) if pit else 0
        return self._role(pa, bf,
                          sum(s[2][_BAT_IDX["G"]] or 0 for s in bat),
                          sum(s[2][_PIT_IDX["G"]] or 0 for s in pit))

    def career_summary(self, player_id: str) -> dict | None:
        """Career span and volume from the stats themselves (People's
        debut/finalGame are blank for active and most Negro-league
        players): first_year, last_year, pa, bf, role, position."""
        entry = self._career_table().get(player_id)
        if not entry:
            return None
        years = sorted(set(entry[4]) | set(entry[5]))
        return {
            "player_id": player_id,
            "name": self.player_name(player_id),
            "first_year": years[0] if years else None,
            "last_year": years[-1] if years else None,
            "pa": entry[0],
            "bf": entry[1],
            "role": self._role(entry[0], entry[1], entry[2], entry[3]),
            "position": self.career_position(player_id),
            "batting_years": list(entry[4]),
            "pitching_years": list(entry[5]),
        }

    def career_position(self, player_id: str) -> str | None:
        """Position with the most career games ('OF' for any outfield
        spot), or None when no fielding is recorded."""
        self._load_fielding()
        entry = self._career_table().get(player_id)
        if not entry:
            return None
        g_index = _FIELDING_STATS.index("G")
        games: dict[str, int] = defaultdict(int)
        for year in set(entry[4]) | set(entry[5]):
            for pos, (values, _lg) in self._fielding.get((player_id, year), {}).items():
                if pos in ("LF", "CF", "RF", "PH", "PR"):
                    continue  # 'OF' already holds the outfield total
                games[pos] += values[g_index] or 0
        if not games:
            return None
        return max(games.items(), key=lambda kv: kv[1])[0]

    def _suggest_index(self) -> tuple[list[str], dict[str, list[str]], dict]:
        """(sorted unique name tokens, token -> pids, pid -> token tuple),
        built once over every player who has a playable season."""
        index = getattr(self, "_suggest_cache", None)
        if index is not None:
            return index
        with self._lock:
            index = getattr(self, "_suggest_cache", None)
            if index is not None:
                return index
            self._load_people()
            career = self._career_table()
            by_token: dict[str, list[str]] = defaultdict(list)
            names: dict[str, tuple] = {}
            for pid, entry in career.items():
                if not (entry[4] or entry[5]):
                    continue
                tokens = tuple(self._suggest_tokens(self.player_name(pid)))
                names[pid] = tokens
                for t in set(tokens):
                    by_token[t].append(pid)
            index = (sorted(by_token), dict(by_token), names)
            self._suggest_cache = index
            return index

    def suggest_players(self, query: str, limit: int = 8) -> list[dict]:
        """Autocomplete: players whose name tokens start with every typed
        token, in any order ('babe ru', 'mays w', 'aj pierz', 'griffey
        jr'), most prominent first (career PA + batters faced), exact
        name-token matches ahead of prefixes. Fast (bisect over a token
        index built once)."""
        import bisect
        import heapq

        q = self._suggest_tokens(query)
        if not q:
            return []
        tokens, by_token, names = self._suggest_index()
        matched: set | None = None
        for t in sorted(set(q), key=len, reverse=True):
            found: set = set()
            i = bisect.bisect_left(tokens, t)
            while i < len(tokens) and tokens[i].startswith(t):
                found.update(by_token[tokens[i]])
                i += 1
            matched = found if matched is None else matched & found
            if not matched:
                return []
        career = self._career_table()
        # A whole typed word counts as a match only from two letters up,
        # and a whole-name match only for two words or more (so 'smith'
        # ranks Ozzie and Lee ahead of the mononym 'Smith' of 1884).
        qset = {t for t in q if len(t) > 1}
        multi = len(q) > 1

        def score(pid):
            entry = career[pid]
            exact = len(qset & set(names[pid]))
            full = multi and names[pid] == tuple(q)
            return (full, exact, entry[0] + entry[1], pid)

        best = heapq.nlargest(limit, matched, key=score)
        return [self.career_summary(pid) for pid in best]

    # Teams

    def _team_table(self) -> dict:
        """(year, teamID) -> team row (name, league, W, L, G, rank,
        franchise), from one cached read of the small Teams table."""
        table = getattr(self, "_team_cache", None)
        if table is not None:
            return table
        with self._lock:
            table = getattr(self, "_team_cache", None)
            if table is not None:
                return table
            table = {}
            for row in self._rows("Teams"):
                year = int(row["yearID"])
                table[(year, row["teamID"])] = {
                    "year": year,
                    "team_id": row["teamID"],
                    "name": row.get("name") or row["teamID"],
                    "league": row.get("lgID") or "?",
                    "division": row.get("divID") or "",
                    "franchise": row.get("franchID") or "",
                    "rank": _int_or_none(row.get("Rank", "")),
                    "G": _int_or_none(row.get("G", "")) or 0,
                    "W": _int_or_none(row.get("W", "")) or 0,
                    "L": _int_or_none(row.get("L", "")) or 0,
                }
            self._team_cache = table
            return table

    def team_years(self) -> tuple[int, int]:
        """(first, last) season with team data."""
        years = [y for y, _t in self._team_table()]
        return min(years), max(years)

    def teams(self, year: int) -> list[dict]:
        """That season's teams, by league, then standing (rank, W%)."""
        rows = [dict(t) for (y, _tid), t in self._team_table().items() if y == year]
        for t in rows:
            decided = t["W"] + t["L"]
            t["pct"] = t["W"] / decided if decided else 0.0
        rows.sort(key=lambda t: (t["league"], t["division"],
                                 t["rank"] if t["rank"] is not None else 99,
                                 -t["pct"], t["name"]))
        return rows

    def team(self, year: int, team_id: str) -> dict | None:
        row = self._team_table().get((year, team_id))
        return dict(row) if row else None

    def team_name(self, year: int, team_id: str) -> str:
        row = self._team_table().get((year, team_id))
        return row["name"] if row else team_id

    def _roster_index(self) -> dict:
        """(year, teamID) -> pids with a batting or pitching stint there."""
        index = getattr(self, "_roster_cache", None)
        if index is not None:
            return index
        with self._lock:
            index = getattr(self, "_roster_cache", None)
            if index is not None:
                return index
            self._load_batting()
            self._load_pitching()
            index = defaultdict(set)
            for table in (self._batting, self._pitching):
                for (pid, year), stints in table.items():
                    for team_id, _lg, _values in stints:
                        index[(year, team_id)].add(pid)
            self._roster_cache = dict(index)
            return self._roster_cache

    def team_roster(self, year: int, team_id: str) -> list[dict]:
        """Everyone who played for the team that season, with his batting
        and pitching *for this team* (for playing-time thresholds) and
        the other teams he played for that year. A player's card still
        uses his full-season line (batting_season/pitching_season sum all
        stints, as Strat-O-Matic does)."""
        pids = self._roster_index().get((year, team_id), set())
        self._load_fielding()
        g_bat, g_pit = _BAT_IDX["G"], _PIT_IDX["G"]
        out = []
        for pid in pids:
            bat = self._batting.get((pid, year)) or []
            pit = self._pitching.get((pid, year)) or []
            bat_here = [s for s in bat if s[0] == team_id]
            pit_here = [s for s in pit if s[0] == team_id]
            others = sorted({s[0] for s in bat + pit if s[0] != team_id})
            batting = None
            if bat_here:
                v = [s[2] for s in bat_here]
                batting = {
                    "G": sum(x[g_bat] or 0 for x in v),
                    "PA": sum(_pa_eff(x) for x in v),
                    "AB": sum(x[_BAT_IDX["AB"]] or 0 for x in v),
                }
            pitching = None
            if pit_here:
                v = [s[2] for s in pit_here]
                pitching = {
                    "G": sum(x[g_pit] or 0 for x in v),
                    "GS": sum(x[_PIT_IDX["GS"]] or 0 for x in v),
                    "IPouts": sum(x[_PIT_IDX["IPouts"]] or 0 for x in v),
                    "BF": self._season_pitch_bf(pit_here),
                }
            positions = self.positions(pid, year)
            person = self._people.get(pid, {})
            out.append({
                "player_id": pid,
                "name": self.player_name(pid),
                "bats": person.get("bats", "?"),
                "throws": person.get("throws", "?"),
                "batting": batting,
                "pitching": pitching,
                "season_pa": sum(_pa_eff(s[2]) for s in bat),
                "season_bf": self._season_pitch_bf(pit) if pit else 0,
                "season_bat_g": sum(s[2][g_bat] or 0 for s in bat),
                "season_pitch_g": sum(s[2][g_pit] or 0 for s in pit),
                "role": self.primary_role(pid, year),
                "position": positions[0][0] if positions else None,
                "positions": positions,
                "other_teams": [{"team_id": t, "name": self.team_name(year, t)}
                                for t in others],
            })
        out.sort(key=lambda p: p["name"])
        return out


@lru_cache(maxsize=1)
def default_db() -> LahmanDB:
    return LahmanDB()
