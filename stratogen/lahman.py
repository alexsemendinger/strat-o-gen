"""Offline baseball statistics from the Lahman database (1871-2025).

Reads the gzipped CSVs in data/lahman/ (Batting, Pitching, People, Teams,
Fielding). Everything works offline; no scraping. League averages are
computed per (year, league) by aggregating every player row, so any
year/league combination present in the data is supported — all eras.

To update for a new season: download the latest CSV release from
https://sabr.org/lahman-database/ and replace the .csv.gz files.
"""

from __future__ import annotations

import csv
import gzip
import io
import random
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
        self._people: dict[str, dict] | None = None
        self._name_index: dict[str, list[str]] | None = None
        self._batting: dict[tuple[str, int], list[dict]] | None = None
        self._pitching: dict[tuple[str, int], list[dict]] | None = None
        self._fielding: dict[tuple[str, int], dict[str, dict]] | None = None
        self._fielding_peers: dict[tuple[int, str], list[dict]] = {}
        self._team_names: dict[tuple[int, str], str] | None = None
        self._random_pool: list[tuple[str, int, str]] | None = None
        self._league_totals: dict[tuple[int, str], dict] = {}

    def _rows(self, table: str):
        path = self.data_dir / f"{table}.csv.gz"
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as fh:
            yield from csv.DictReader(fh)

    # --- people / search -------------------------------------------------

    def _load_people(self):
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
        if self._batting is not None:
            return
        table: dict[tuple[str, int], list[dict]] = defaultdict(list)
        for row in self._rows("Batting"):
            table[(row["playerID"], int(row["yearID"]))].append(row)
        self._batting = dict(table)

    def _load_pitching(self):
        if self._pitching is not None:
            return
        table: dict[tuple[str, int], list[dict]] = defaultdict(list)
        for row in self._rows("Pitching"):
            table[(row["playerID"], int(row["yearID"]))].append(row)
        self._pitching = dict(table)

    def _load_fielding(self):
        """Per-position fielding stats per player-season.

        OF is stored both combined ('OF', from Fielding.csv) and as corners
        ('LF'/'CF'/'RF', from FieldingOFsplit.csv, 1891+). Each entry maps
        stat name -> summed value, plus 'lg'.
        """
        if self._fielding is not None:
            return
        table: dict[tuple[str, int], dict[str, dict]] = {}

        def add(pid: str, year: int, pos: str, row: dict):
            entry = table.setdefault((pid, year), {}).setdefault(
                pos, {s: 0 for s in _FIELDING_STATS})
            for s in _FIELDING_STATS:
                entry[s] += _int_or_none(row.get(s, "")) or 0
            entry["lg"] = row.get("lgID") or entry.get("lg") or "?"

        for row in self._rows("Fielding"):
            add(row["playerID"], int(row["yearID"]), row["POS"], row)
        for row in self._rows("FieldingOFsplit"):
            add(row["playerID"], int(row["yearID"]), row["POS"], row)
        self._fielding = table

    def fielding_by_position(self, player_id: str, year: int) -> dict[str, dict]:
        """{position: fielding stats} for the season ('OF' combined plus
        'LF'/'CF'/'RF' corners where the era has them)."""
        self._load_fielding()
        return self._fielding.get((player_id, year), {})

    def fielding_peers(self, year: int, pos: str) -> list[dict]:
        """All player fielding lines at a position in one season (for
        rating a player against contemporaries)."""
        self._load_fielding()
        key = (year, pos)
        if key not in self._fielding_peers:
            peers = []
            for (pid, y), positions in self._fielding.items():
                if y == year and pos in positions:
                    peers.append(positions[pos])
            self._fielding_peers[key] = peers
        return self._fielding_peers[key]

    def _load_teams(self):
        if self._team_names is not None:
            return
        names = {}
        for row in self._rows("Teams"):
            names[(int(row["yearID"]), row["teamID"])] = row["name"]
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
            batting_years = sorted({y for (p, y) in self._batting if p == pid}) \
                if len(ids) <= limit else []
            pitching_years = sorted({y for (p, y) in self._pitching if p == pid}) \
                if len(ids) <= limit else []
            hits.append(PlayerHit(
                player_id=pid, name=person["name"],
                first_year=person["first_year"], last_year=person["last_year"],
                bats=person["bats"], throws=person["throws"],
                batting_years=batting_years, pitching_years=pitching_years,
            ))
        hits.sort(key=lambda h: (h.first_year or 9999))
        return hits[:limit]

    def player_name(self, player_id: str) -> str:
        self._load_people()
        return self._people.get(player_id, {}).get("name", player_id)

    def player_info(self, player_id: str) -> dict:
        self._load_people()
        return dict(self._people.get(player_id, {}))

    # --- season stats -----------------------------------------------------

    @staticmethod
    def _aggregate(rows: list[dict], fields: list[str]) -> tuple[dict, set]:
        """Sum stat fields across stints. Returns (stats, missing_fields)."""
        stats: dict = {}
        missing: set = set()
        for field in fields:
            values = [_int_or_none(r.get(field, "")) for r in rows]
            if all(v is None for v in values):
                stats[field] = 0
                missing.add(field)
            else:
                stats[field] = sum(v or 0 for v in values)
        return stats, missing

    def batting_season(self, player_id: str, year: int) -> dict | None:
        """Aggregated batting line for a season (stints summed), or None."""
        self._load_batting()
        rows = self._batting.get((player_id, year))
        if not rows:
            return None
        stats, missing = self._aggregate(rows, _BATTING_FIELDS)
        return self._finish_season(stats, missing, rows, player_id, year)

    def pitching_season(self, player_id: str, year: int) -> dict | None:
        self._load_pitching()
        rows = self._pitching.get((player_id, year))
        if not rows:
            return None
        stats, missing = self._aggregate(rows, _PITCHING_FIELDS)
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
        return self._finish_season(stats, missing, rows, player_id, year)

    def _finish_season(self, stats, missing, rows, player_id, year):
        self._load_teams()
        # league/team: take from the stint with the most games
        biggest = max(rows, key=lambda r: _int_or_none(r.get("G", "")) or 0)
        stats["year"] = year
        stats["league"] = biggest.get("lgID") or "?"
        stats["team_ids"] = [r["teamID"] for r in rows]
        stats["team"] = self._team_names.get(
            (year, biggest["teamID"]), biggest["teamID"])
        stats["player_id"] = player_id
        stats["name"] = self.player_name(player_id)
        stats["multi_team"] = len(rows) > 1
        stats["missing"] = sorted(missing)
        if stats.get("AB"):
            stats["BA"] = round(stats.get("H", 0) / stats["AB"], 3)
        return stats

    def positions(self, player_id: str, year: int) -> list[tuple[str, int]]:
        """[(position, games)] for the season, most games first.

        Outfield is broken into LF/CF/RF when the era's data allows
        (1891+); otherwise the combined 'OF' is reported.
        """
        by_pos = self.fielding_by_position(player_id, year)
        corners = {p: s for p, s in by_pos.items() if p in ("LF", "CF", "RF")}
        out = []
        for pos, stats in by_pos.items():
            if pos == "OF" and corners:
                continue  # corners supersede the combined row
            out.append((pos, stats.get("G", 0)))
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
            pool: list[tuple[str, int, str]] = []
            for (pid, year), rows in self._batting.items():
                pa = sum((_int_or_none(r.get("AB", "")) or 0)
                         + (_int_or_none(r.get("BB", "")) or 0) for r in rows)
                if pa >= 150:
                    pool.append((pid, year, "batter"))
            for (pid, year), rows in self._pitching.items():
                bfp = sum(_int_or_none(r.get("BFP", "")) or 0 for r in rows)
                ipouts = sum(_int_or_none(r.get("IPouts", "")) or 0 for r in rows)
                if bfp >= 200 or (bfp == 0 and ipouts >= 150):
                    pool.append((pid, year, "pitcher"))
            self._random_pool = pool
        return (rng or random).choice(self._random_pool)

    # --- league averages ---------------------------------------------------

    def leagues_for_year(self, year: int) -> list[str]:
        self._load_batting()
        return sorted({rows[0]["lgID"] for (p, y), rows in self._batting.items()
                       if y == year and rows[0]["lgID"]})

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
        totals = {f: 0 for f in _BATTING_FIELDS}
        tracked = {f: False for f in _BATTING_FIELDS}
        found = False
        for (pid, y), rows in self._batting.items():
            if y != year:
                continue
            for row in rows:
                if row["lgID"] != league:
                    continue
                found = True
                for f in _BATTING_FIELDS:
                    v = _int_or_none(row.get(f, ""))
                    if v is not None:
                        totals[f] += v
                        tracked[f] = True
        if not found:
            raise KeyError(f"no batting data for {league} {year}")

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
