"""Data acquisition module for fetching player statistics."""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pybaseball as pyb

import config

# Enable pybaseball cache
pyb.cache.enable()


class PlayerScraper:
    """Handles fetching and caching player statistics."""

    def __init__(self):
        """Initialize scraper with cache directory."""
        self.cache_dir = Path(config.CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def search_players(self, name: str) -> List[Dict]:
        """
        Search for players by name.

        Args:
            name: Player name to search for

        Returns:
            List of matching players with disambiguating info
        """
        try:
            # Use pybaseball's playerid_lookup
            results = pyb.playerid_lookup(name.split()[-1], name.split()[0] if len(name.split()) > 1 else '')

            if results is None or len(results) == 0:
                return []

            players = []
            for _, row in results.iterrows():
                player_info = {
                    'player_id': row.get('key_bbref', ''),
                    'name': f"{row.get('name_first', '')} {row.get('name_last', '')}",
                    'years': f"{row.get('mlb_played_first', 'Unknown')}-{row.get('mlb_played_last', 'Unknown')}",
                    'debut': row.get('mlb_played_first', 0),
                    'final': row.get('mlb_played_last', 0)
                }
                players.append(player_info)

            return players
        except Exception as e:
            print(f"Error searching for player: {e}")
            return []

    def get_player_stats(self, player_id: str, year: int) -> Optional[Dict]:
        """
        Fetch player statistics for a given year.

        Args:
            player_id: Baseball Reference player ID
            year: Season year

        Returns:
            Dictionary of player stats or None if not found
        """
        # Check cache first
        cache_key = f"{player_id}_{year}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:
            # Fetch batting stats
            stats = self._fetch_batting_stats(player_id, year)

            if stats:
                # Cache the result
                self._save_to_cache(cache_key, stats)

            return stats

        except Exception as e:
            print(f"Error fetching stats for {player_id} in {year}: {e}")
            return None

    def _fetch_batting_stats(self, player_id: str, year: int) -> Optional[Dict]:
        """Fetch batting statistics from Baseball Reference."""
        try:
            # Use pybaseball's player_stats_bref function for specific player
            # This fetches directly from Baseball Reference using their player ID
            from pybaseball import player_stats_bref

            # Get all batting stats for the player
            try:
                df = player_stats_bref(player_id)
                if df is None or len(df) == 0:
                    return None

                # Filter for the specific year
                # The year might be in different columns depending on format
                year_data = None
                if 'Year' in df.columns:
                    year_data = df[df['Year'] == str(year)]
                elif 'season' in df.columns:
                    year_data = df[df['season'] == year]

                if year_data is None or len(year_data) == 0:
                    return None

                # If multiple rows (multi-team season), aggregate
                if len(year_data) > 1:
                    # Look for a 'TOT' row or aggregate manually
                    tot_row = year_data[year_data.get('Tm', '') == 'TOT']
                    if len(tot_row) > 0:
                        row = tot_row.iloc[0]
                    else:
                        # Aggregate stats across teams
                        row = self._aggregate_multi_team(year_data)
                else:
                    row = year_data.iloc[0]

                # Extract stats
                stats = self._extract_stats_from_row(row, year)
                stats['player_id'] = player_id
                stats['year'] = year

                return stats

            except Exception as e:
                print(f"player_stats_bref failed, trying alternative: {e}")
                # Fallback: try batting_stats with broad search
                return self._fetch_batting_stats_fallback(player_id, year)

        except Exception as e:
            print(f"Error in _fetch_batting_stats: {e}")
            return None

    def _aggregate_multi_team(self, df: pd.DataFrame) -> pd.Series:
        """Aggregate stats across multiple teams in same season."""
        numeric_cols = df.select_dtypes(include=['int64', 'float64']).columns

        # Sum counting stats
        aggregated = df[numeric_cols].sum()

        # Get non-numeric from first row
        non_numeric = df.select_dtypes(exclude=['int64', 'float64']).iloc[0]

        # Combine
        result = pd.concat([non_numeric, aggregated])

        # Recalculate rate stats
        if 'AB' in result and result['AB'] > 0:
            result['AVG'] = result.get('H', 0) / result['AB']
        if 'PA' in result and result['PA'] > 0:
            ab = result.get('AB', 0)
            h = result.get('H', 0)
            bb = result.get('BB', 0)
            hbp = result.get('HBP', 0)
            sf = result.get('SF', 0)

            if ab + bb + hbp + sf > 0:
                result['OBP'] = (h + bb + hbp) / (ab + bb + hbp + sf)
            if ab > 0:
                tb = (result.get('H', 0) - result.get('2B', 0) - result.get('3B', 0) - result.get('HR', 0) +
                      2 * result.get('2B', 0) + 3 * result.get('3B', 0) + 4 * result.get('HR', 0))
                result['SLG'] = tb / ab

        return result

    def _fetch_batting_stats_fallback(self, player_id: str, year: int) -> Optional[Dict]:
        """Fallback method to fetch batting stats."""
        try:
            # Try to use batting_stats for the year and search by name
            batting = pyb.batting_stats(year, year, qual=0)

            if batting is None or len(batting) == 0:
                return None

            # Search for player by ID in various ID columns
            player_data = pd.DataFrame()
            for id_col in ['IDfg', 'mlbamid', 'bbrefid', 'Name']:
                if id_col in batting.columns:
                    if id_col == 'Name':
                        # Partial name match as last resort
                        player_data = batting[batting[id_col].str.contains(player_id, case=False, na=False)]
                    else:
                        player_data = batting[batting[id_col] == player_id]

                    if len(player_data) > 0:
                        break

            if len(player_data) == 0:
                return None

            row = player_data.iloc[0]
            stats = self._extract_stats_from_row(row, year)
            stats['player_id'] = player_id
            stats['year'] = year

            return stats

        except Exception as e:
            print(f"Fallback also failed: {e}")
            return None

    def _extract_stats_from_row(self, row: pd.Series, year: int) -> Dict:
        """Extract and normalize stats from a pandas row."""

        def safe_get(keys, default=0):
            """Safely get a value from row, trying multiple key names."""
            if isinstance(keys, str):
                keys = [keys]

            for key in keys:
                try:
                    val = row.get(key, None)
                    if val is not None and not pd.isna(val):
                        return int(float(val))
                except:
                    continue
            return default

        def safe_get_float(keys, default=0.0):
            """Safely get a float value from row."""
            if isinstance(keys, str):
                keys = [keys]

            for key in keys:
                try:
                    val = row.get(key, None)
                    if val is not None and not pd.isna(val):
                        return float(val)
                except:
                    continue
            return default

        # Handle various column name formats from different sources
        stats = {
            'player_name': str(row.get('Name', row.get('name', 'Unknown'))),
            'team': str(row.get('Tm', row.get('Team', 'Unknown'))),
            'league': str(row.get('Lg', row.get('League', 'AL'))),
            'G': safe_get(['G', 'Games']),
            'AB': safe_get(['AB', 'At-bats']),
            'PA': safe_get(['PA', 'plate_appearances']),
            'H': safe_get(['H', 'Hits']),
            '2B': safe_get(['2B', 'Doubles', 'doubles']),
            '3B': safe_get(['3B', 'Triples', 'triples']),
            'HR': safe_get(['HR', 'Home Runs', 'home_runs']),
            'R': safe_get(['R', 'Runs']),
            'RBI': safe_get(['RBI']),
            'BB': safe_get(['BB', 'Walks']),
            'SO': safe_get(['SO', 'K', 'Strikeouts']),
            'SB': safe_get(['SB', 'Stolen Bases']),
            'CS': safe_get(['CS', 'Caught Stealing']),
            'BA': safe_get_float(['BA', 'AVG', 'avg'], 0.0),
            'OBP': safe_get_float(['OBP', 'obp'], 0.0),
            'SLG': safe_get_float(['SLG', 'slg'], 0.0),
        }

        # Optional stats with era-appropriate handling
        stats['HBP'] = safe_get(['HBP', 'Hit By Pitch'])
        stats['SF'] = safe_get(['SF', 'Sacrifice Flies']) if year >= 1954 else None
        stats['SH'] = safe_get(['SH', 'Sacrifice Hits', 'SAC'])
        stats['IBB'] = safe_get(['IBB', 'Intentional Walks']) if year >= 1955 else None
        stats['GDP'] = safe_get(['GDP', 'GIDP', 'Double Plays'])

        # Get position and handedness if available
        pos = row.get('Pos', row.get('Position', 'Unknown'))
        stats['positions'] = [str(pos)] if pos != 'Unknown' else ['Unknown']
        stats['bats'] = str(row.get('Bats', 'R'))
        stats['throws'] = str(row.get('Throws', 'R'))

        # Calculate BA/OBP/SLG if not provided
        if stats['BA'] == 0.0 and stats['AB'] > 0:
            stats['BA'] = stats['H'] / stats['AB']

        if stats['OBP'] == 0.0 and stats['AB'] > 0:
            denom = stats['AB'] + stats['BB'] + stats['HBP'] + (stats['SF'] if stats['SF'] else 0)
            if denom > 0:
                stats['OBP'] = (stats['H'] + stats['BB'] + stats['HBP']) / denom

        if stats['SLG'] == 0.0 and stats['AB'] > 0:
            singles = stats['H'] - stats['2B'] - stats['3B'] - stats['HR']
            tb = singles + (2 * stats['2B']) + (3 * stats['3B']) + (4 * stats['HR'])
            stats['SLG'] = tb / stats['AB']

        # Calculate PA if not provided
        if stats['PA'] == 0:
            stats['PA'] = self._calculate_pa(stats)

        # Track warnings for missing data
        stats['warnings'] = self._generate_warnings(stats, year)

        return stats

    def _calculate_pa(self, stats: Dict) -> int:
        """Calculate plate appearances from components."""
        pa = stats['AB'] + stats['BB'] + stats['HBP']
        if stats.get('SF') is not None:
            pa += stats['SF']
        if stats.get('SH') is not None:
            pa += stats['SH']
        return pa

    def _generate_warnings(self, stats: Dict, year: int) -> List[str]:
        """Generate warnings for missing or estimated data."""
        warnings = []

        if year < 1955 and (stats.get('IBB') is None or stats['IBB'] == 0):
            warnings.append('IBB not tracked before 1955')

        if year < 1954 and (stats.get('SF') is None or stats['SF'] == 0):
            warnings.append('SF not tracked before 1954')

        if year < 1951 and stats.get('CS', 0) == 0:
            warnings.append('CS data may be incomplete before 1951')

        if stats.get('HBP', 0) == 0:
            warnings.append('HBP may be incomplete in historical data')

        if stats['PA'] < config.MIN_PLATE_APPEARANCES:
            warnings.append(f'Limited sample size: {stats["PA"]} PA')

        return warnings

    def _get_from_cache(self, key: str) -> Optional[Dict]:
        """Retrieve cached player data."""
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except:
                return None
        return None

    def _save_to_cache(self, key: str, data: Dict) -> None:
        """Save player data to cache."""
        cache_file = self.cache_dir / f"{key}.json"
        try:
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving to cache: {e}")

    def get_league_averages(self, year: int, league: str) -> Optional[Dict]:
        """
        Get league average statistics for a year.

        Args:
            year: Season year
            league: 'AL' or 'NL'

        Returns:
            Dictionary of league averages
        """
        # Check if we have cached league averages
        league_file = Path(config.LEAGUE_AVG_FILE)
        if league_file.exists():
            try:
                with open(league_file, 'r') as f:
                    all_league_avgs = json.load(f)
                    return all_league_avgs.get(str(year), {}).get(league)
            except:
                pass

        # If not cached, fetch from pybaseball
        return self._fetch_league_averages(year, league)

    def _fetch_league_averages(self, year: int, league: str) -> Dict:
        """Fetch league averages from pybaseball."""
        try:
            # Get league batting stats
            batting = pyb.batting_stats(year, year, qual=0)

            if len(batting) == 0:
                return self._get_default_league_averages()

            # Filter by league if possible
            if 'League' in batting.columns:
                league_data = batting[batting['League'] == league]
                if len(league_data) == 0:
                    league_data = batting
            else:
                league_data = batting

            # Calculate averages
            total_pa = league_data['PA'].sum()

            if total_pa == 0:
                return self._get_default_league_averages()

            averages = {
                'BA': league_data['H'].sum() / league_data['AB'].sum() if league_data['AB'].sum() > 0 else 0.250,
                'HR_per_PA': league_data['HR'].sum() / total_pa,
                'BB_per_PA': league_data['BB'].sum() / total_pa,
                'K_per_PA': league_data['SO'].sum() / total_pa,
                '2B_per_PA': league_data['2B'].sum() / total_pa,
                '3B_per_PA': league_data['3B'].sum() / total_pa,
                'HBP_per_PA': league_data['HBP'].sum() / total_pa if 'HBP' in league_data.columns else 0.005,
            }

            return averages

        except Exception as e:
            print(f"Error fetching league averages: {e}")
            return self._get_default_league_averages()

    def _get_default_league_averages(self) -> Dict:
        """Return reasonable default league averages."""
        return {
            'BA': 0.250,
            'HR_per_PA': 0.025,
            'BB_per_PA': 0.085,
            'K_per_PA': 0.200,
            '2B_per_PA': 0.040,
            '3B_per_PA': 0.005,
            'HBP_per_PA': 0.005,
        }
