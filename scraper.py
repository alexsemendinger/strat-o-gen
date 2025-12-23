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
                    'name_first': row.get('name_first', ''),
                    'name_last': row.get('name_last', ''),
                    'years': f"{row.get('mlb_played_first', 'Unknown')}-{row.get('mlb_played_last', 'Unknown')}",
                    'debut': row.get('mlb_played_first', 0),
                    'final': row.get('mlb_played_last', 0)
                }
                players.append(player_info)

                # Cache the player name for later use
                self._cache_player_name(player_info['player_id'], player_info['name'])

            return players
        except Exception as e:
            print(f"Error searching for player: {e}")
            return []

    def _cache_player_name(self, player_id: str, name: str) -> None:
        """Cache player name for ID lookup."""
        cache_file = self.cache_dir / f"{player_id}_name.json"
        try:
            with open(cache_file, 'w') as f:
                json.dump({'player_id': player_id, 'name': name}, f)
        except:
            pass

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
        """Fetch batting statistics from various sources."""
        # Try manual data first (for when APIs are down)
        from manual_data import get_manual_player_data
        manual_stats = get_manual_player_data(player_id, year)
        if manual_stats:
            print(f"Using manually entered data for {player_id} {year}")
            return manual_stats

        # Try Lahman database (offline, usually reliable)
        stats = self._fetch_from_lahman(player_id, year)
        if stats:
            return stats

        # Try Baseball Reference scraping as fallback
        try:
            stats = self._fetch_from_baseball_reference(player_id, year)
            if stats:
                return stats
        except Exception as e:
            print(f"Baseball Reference fetch failed: {e}")

        # Last resort: try other pybaseball methods
        return self._fetch_via_pybaseball_alt(player_id, year)

    def _fetch_via_pybaseball_alt(self, player_id: str, year: int) -> Optional[Dict]:
        """Alternative method using pybaseball batting_stats_bref."""
        try:
            # Try batting_stats_bref which goes directly to Baseball Reference
            batting = pyb.batting_stats_bref(year)

            if batting is None or len(batting) == 0:
                return None

            # Get player name from cache
            player_name_parts = self._get_player_name_from_id(player_id)

            if not player_name_parts:
                return None

            first, last = player_name_parts

            # Search for player in the data
            for idx, row in batting.iterrows():
                name = str(row.get('Name', ''))
                if last.lower() in name.lower() and first.lower() in name.lower():
                    stats = self._extract_stats_from_row(row, year)
                    stats['player_id'] = player_id
                    stats['year'] = year
                    return stats

            return None

        except Exception as e:
            print(f"pybaseball batting_stats_bref failed: {e}")
            return None

    def _fetch_from_lahman(self, player_id: str, year: int) -> Optional[Dict]:
        """Fetch stats from Lahman database (offline, reliable)."""
        try:
            # Download Lahman database if not already downloaded
            try:
                pyb.download_lahman()
            except:
                pass  # May already be downloaded

            # Get Lahman batting data (function is called 'batting')
            lahman = pyb.batting()

            if lahman is None or len(lahman) == 0:
                return None

            # Filter for this player and year
            player_data = lahman[
                (lahman['playerID'] == player_id) &
                (lahman['yearID'] == year)
            ]

            if len(player_data) == 0:
                return None

            # If multiple rows (played for multiple teams), aggregate
            if len(player_data) > 1:
                row = self._aggregate_lahman_stats(player_data)
            else:
                row = player_data.iloc[0]

            # Convert Lahman format to our format
            stats = self._convert_lahman_stats(row, year)
            stats['player_id'] = player_id
            stats['year'] = year

            return stats

        except Exception as e:
            print(f"Lahman database lookup failed: {e}")
            return None

    def _aggregate_lahman_stats(self, df: pd.DataFrame) -> pd.Series:
        """Aggregate Lahman stats across teams."""
        # Lahman has counting stats, so just sum them
        numeric_cols = ['G', 'AB', 'R', 'H', '2B', '3B', 'HR', 'RBI', 'SB', 'CS', 'BB', 'SO', 'IBB', 'HBP', 'SH', 'SF', 'GIDP']

        result = {}
        for col in numeric_cols:
            if col in df.columns:
                result[col] = df[col].sum()

        # Get non-numeric from first row
        result['playerID'] = df.iloc[0]['playerID']
        result['yearID'] = df.iloc[0]['yearID']
        result['lgID'] = df.iloc[0].get('lgID', 'AL')

        return pd.Series(result)

    def _convert_lahman_stats(self, row: pd.Series, year: int) -> Dict:
        """Convert Lahman database format to our format."""

        def safe_int(key, default=0):
            val = row.get(key, default)
            return int(val) if pd.notna(val) else default

        ab = safe_int('AB')
        h = safe_int('H')
        doubles = safe_int('2B')
        triples = safe_int('3B')
        hr = safe_int('HR')
        bb = safe_int('BB')
        hbp = safe_int('HBP')
        sf = safe_int('SF')
        sh = safe_int('SH')

        # Calculate PA
        pa = ab + bb + hbp + sf + sh

        # Calculate BA/OBP/SLG
        ba = h / ab if ab > 0 else 0.0

        obp_denom = ab + bb + hbp + sf
        obp = (h + bb + hbp) / obp_denom if obp_denom > 0 else 0.0

        singles = h - doubles - triples - hr
        tb = singles + (2 * doubles) + (3 * triples) + (4 * hr)
        slg = tb / ab if ab > 0 else 0.0

        stats = {
            'player_name': 'Unknown',  # Lahman doesn't include names in batting table
            'team': str(row.get('teamID', 'Unknown')),
            'league': str(row.get('lgID', 'AL')),
            'G': safe_int('G'),
            'AB': ab,
            'PA': pa,
            'H': h,
            '2B': doubles,
            '3B': triples,
            'HR': hr,
            'R': safe_int('R'),
            'RBI': safe_int('RBI'),
            'BB': bb,
            'SO': safe_int('SO'),
            'SB': safe_int('SB'),
            'CS': safe_int('CS'),
            'BA': ba,
            'OBP': obp,
            'SLG': slg,
            'HBP': hbp,
            'SF': sf if year >= 1954 else None,
            'SH': sh,
            'IBB': safe_int('IBB') if year >= 1955 else None,
            'GDP': safe_int('GIDP'),
            'positions': ['Unknown'],
            'bats': 'R',
            'throws': 'R',
        }

        # Get player name from cache if available
        name_parts = self._get_player_name_from_id(row.get('playerID', ''))
        if name_parts:
            stats['player_name'] = f"{name_parts[0]} {name_parts[1]}"

        # Generate warnings
        stats['warnings'] = self._generate_warnings(stats, year)

        return stats

    def _get_player_name_from_id(self, player_id: str) -> Optional[Tuple[str, str]]:
        """Extract player name from ID or cache."""
        # Check name cache first
        name_cache = self.cache_dir / f"{player_id}_name.json"
        if name_cache.exists():
            try:
                with open(name_cache, 'r') as f:
                    cached = json.load(f)
                    name = cached.get('name', '')
                    parts = name.split()
                    if len(parts) >= 2:
                        return parts[0], parts[-1]
            except:
                pass

        # Check stats cache
        cache_files = list(self.cache_dir.glob(f"{player_id}_*.json"))
        for cache_file in cache_files:
            if '_name.json' in str(cache_file):
                continue
            try:
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                    name = cached.get('player_name', '')
                    parts = name.split()
                    if len(parts) >= 2:
                        return parts[0], parts[-1]
            except:
                pass

        return None

    def _fetch_from_baseball_reference(self, player_id: str, year: int) -> Optional[Dict]:
        """Fetch stats directly from Baseball Reference HTML."""
        try:
            import requests
            from bs4 import BeautifulSoup

            # Baseball Reference URL format
            url = f"https://www.baseball-reference.com/players/{player_id[0]}/{player_id}.shtml"

            # Add headers to avoid being blocked
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            time.sleep(config.SCRAPE_DELAY_SECONDS)
            response = requests.get(url, headers=headers, timeout=15)

            if response.status_code != 200:
                print(f"Baseball Reference returned status {response.status_code}")
                return None

            soup = BeautifulSoup(response.content, 'html.parser')

            # Find the batting stats table - Baseball Reference often puts tables in HTML comments
            batting_table = soup.find('table', {'id': 'batting_standard'})

            if not batting_table:
                # Try to find the table in HTML comments
                import re
                comments = soup.find_all(string=lambda text: isinstance(text, str) and 'batting_standard' in text)

                for comment in comments:
                    # Parse the comment as HTML
                    comment_soup = BeautifulSoup(str(comment), 'html.parser')
                    batting_table = comment_soup.find('table', {'id': 'batting_standard'})
                    if batting_table:
                        break

            if not batting_table:
                print("Could not find batting table (even in comments)")
                return None

            # Find the row for the specific year
            tbody = batting_table.find('tbody')
            if not tbody:
                # Sometimes there's no tbody tag
                rows = batting_table.find_all('tr')
            else:
                rows = tbody.find_all('tr')

            for row in rows:
                # Skip header rows
                if 'class' in row.attrs and 'thead' in row.attrs.get('class', []):
                    continue

                year_cell = row.find('th', {'data-stat': 'year_ID'})
                if not year_cell:
                    continue

                year_text = year_cell.text.strip()

                if str(year) == year_text:
                    # Extract stats from this row
                    stats_dict = {}

                    # Get player name from page
                    name_tag = soup.find('h1')
                    if name_tag:
                        stats_dict['player_name'] = name_tag.text.strip()

                    # Get all stat cells
                    for cell in row.find_all(['td', 'th']):
                        stat_name = cell.get('data-stat', '')
                        stat_value = cell.text.strip()
                        if stat_name:
                            stats_dict[stat_name] = stat_value

                    # Convert to our format
                    stats = self._convert_bbref_stats(stats_dict, year)
                    stats['player_id'] = player_id
                    stats['year'] = year

                    return stats

            print(f"Could not find stats row for year {year}")
            return None

        except Exception as e:
            print(f"Exception in Baseball Reference scraping: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _convert_bbref_stats(self, bbref_stats: Dict, year: int) -> Dict:
        """Convert Baseball Reference stat format to our format."""

        def safe_int(val, default=0):
            try:
                return int(val) if val and val != '' else default
            except:
                return default

        def safe_float(val, default=0.0):
            try:
                return float(val) if val and val != '' else default
            except:
                return default

        stats = {
            'player_name': bbref_stats.get('player_name', 'Unknown'),
            'team': bbref_stats.get('team_ID', 'Unknown'),
            'league': bbref_stats.get('lg_ID', 'AL'),
            'G': safe_int(bbref_stats.get('G')),
            'AB': safe_int(bbref_stats.get('AB')),
            'PA': safe_int(bbref_stats.get('PA')),
            'H': safe_int(bbref_stats.get('H')),
            '2B': safe_int(bbref_stats.get('2B')),
            '3B': safe_int(bbref_stats.get('3B')),
            'HR': safe_int(bbref_stats.get('HR')),
            'R': safe_int(bbref_stats.get('R')),
            'RBI': safe_int(bbref_stats.get('RBI')),
            'BB': safe_int(bbref_stats.get('BB')),
            'SO': safe_int(bbref_stats.get('SO')),
            'SB': safe_int(bbref_stats.get('SB')),
            'CS': safe_int(bbref_stats.get('CS')),
            'BA': safe_float(bbref_stats.get('batting_avg')),
            'OBP': safe_float(bbref_stats.get('onbase_perc')),
            'SLG': safe_float(bbref_stats.get('slugging_perc')),
            'HBP': safe_int(bbref_stats.get('HBP')),
            'SF': safe_int(bbref_stats.get('SF')) if year >= 1954 else None,
            'SH': safe_int(bbref_stats.get('SH')),
            'IBB': safe_int(bbref_stats.get('IBB')) if year >= 1955 else None,
            'GDP': safe_int(bbref_stats.get('GIDP')),
            'positions': ['Unknown'],
            'bats': 'R',
            'throws': 'R',
        }

        # Calculate PA if not provided
        if stats['PA'] == 0:
            stats['PA'] = self._calculate_pa(stats)

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

        # Track warnings
        stats['warnings'] = self._generate_warnings(stats, year)

        return stats

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
        # Try manual data first (for when APIs are down)
        from manual_data import get_manual_league_averages
        manual_avg = get_manual_league_averages(year, league)
        if manual_avg:
            return manual_avg

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
