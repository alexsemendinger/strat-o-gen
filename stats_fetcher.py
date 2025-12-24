"""
Clean stats fetching system - Step 1: Basic player stats retrieval

This module starts simple: fetch batting stats for a known player ID and year
by scraping Baseball Reference directly.
"""

import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict
import re
import time


class StatsFetcher:
    """Fetches baseball statistics from Baseball Reference via web scraping."""

    def __init__(self):
        """Initialize the stats fetcher."""
        self.base_url = "https://www.baseball-reference.com"
        self.session = requests.Session()
        # Be nice to Baseball Reference - add a user agent
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Baseball Card Generator)'
        })

    def get_stats(self, bbref_id: str, year: int, stat_type: str = 'batting') -> Optional[Dict]:
        """
        Fetch statistics for a specific player and year.

        Args:
            bbref_id: Baseball Reference player ID (e.g., 'ruthba01')
            year: Season year (e.g., 1927)
            stat_type: 'batting' or 'pitching'

        Returns:
            Dictionary of stats, or None if not found
        """
        if stat_type == 'batting':
            return self.get_batting_stats(bbref_id, year)
        elif stat_type == 'pitching':
            return self.get_pitching_stats(bbref_id, year)
        else:
            raise ValueError(f"stat_type must be 'batting' or 'pitching', got '{stat_type}'")

    def get_batting_stats(self, bbref_id: str, year: int) -> Optional[Dict]:
        """
        Fetch batting statistics for a specific player and year.

        Args:
            bbref_id: Baseball Reference player ID (e.g., 'ruthba01')
            year: Season year (e.g., 1927)

        Returns:
            Dictionary of batting stats, or None if not found
        """
        try:
            # Construct the player page URL
            # Format: /players/{first_letter}/{player_id}.shtml
            first_letter = bbref_id[0].lower()
            url = f"{self.base_url}/players/{first_letter}/{bbref_id}.shtml"

            print(f"Fetching {url}")

            # Fetch the page
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Find the batting standard table
            # Note: Baseball Reference uses 'players_standard_batting' for player pages
            batting_table = soup.find('table', {'id': 'players_standard_batting'})
            if not batting_table:
                print(f"No batting table found for {bbref_id}")
                return None

            # Find the row for the specific year
            stats_row = None
            for row in batting_table.find('tbody').find_all('tr'):
                # Skip header rows
                if row.get('class') and 'thead' in row.get('class'):
                    continue

                # Check if this is the year we want
                # Note: Baseball Reference uses 'year_id' (lowercase) as the data-stat
                year_cell = row.find('th', {'data-stat': 'year_id'})
                if year_cell and year_cell.text.strip() == str(year):
                    stats_row = row
                    break

            if not stats_row:
                print(f"No stats found for {bbref_id} in {year}")
                return None

            # Extract stats from the row
            stats = self._extract_stats_from_row(stats_row, year)

            return stats

        except requests.RequestException as e:
            print(f"Network error fetching stats for {bbref_id}: {e}")
            return None
        except Exception as e:
            print(f"Error fetching stats for {bbref_id} in {year}: {e}")
            return None

    def _extract_stats_from_row(self, row, year: int) -> Dict:
        """
        Extract batting statistics from a BeautifulSoup table row.

        Args:
            row: BeautifulSoup tr element containing a player's season stats
            year: The season year

        Returns:
            Dictionary of standardized batting stats
        """
        # Helper to safely get a stat value from the row
        def get_stat(stat_name, default=0, as_float=False):
            """Get a stat value from the row by data-stat attribute."""
            cell = row.find('td', {'data-stat': stat_name})
            if not cell:
                return default

            text = cell.text.strip()
            if not text or text == '':
                return default

            try:
                if as_float:
                    return float(text)
                else:
                    return int(text)
            except ValueError:
                return default

        # Extract core counting stats
        # Baseball Reference uses 'b_' prefix for batting stats
        stats = {
            'year': year,
            'G': get_stat('b_games'),
            'AB': get_stat('b_ab'),
            'PA': get_stat('b_pa'),
            'H': get_stat('b_h'),
            '2B': get_stat('b_doubles'),
            '3B': get_stat('b_triples'),
            'HR': get_stat('b_hr'),
            'R': get_stat('b_r'),
            'RBI': get_stat('b_rbi'),
            'BB': get_stat('b_bb'),
            'SO': get_stat('b_so'),
            'SB': get_stat('b_sb'),
            'CS': get_stat('b_cs'),
            'HBP': get_stat('b_hbp'),
            'SH': get_stat('b_sh'),
            'SF': get_stat('b_sf'),
            'IBB': get_stat('b_ibb'),
            'GDP': get_stat('b_gidp'),

            # Rate stats
            'BA': get_stat('b_batting_avg', 0.0, as_float=True),
            'OBP': get_stat('b_onbase_perc', 0.0, as_float=True),
            'SLG': get_stat('b_slugging_perc', 0.0, as_float=True),

            # Metadata (initialize with defaults)
            'team': 'Unknown',
            'league': 'Unknown',
        }

        # Get team and league as strings
        team_cell = row.find('td', {'data-stat': 'team_name_abbr'})
        if team_cell:
            stats['team'] = team_cell.text.strip()

        league_cell = row.find('td', {'data-stat': 'comp_name_abbr'})
        if league_cell:
            stats['league'] = league_cell.text.strip()

        return stats

    def get_pitching_stats(self, bbref_id: str, year: int) -> Optional[Dict]:
        """
        Fetch pitching statistics for a specific player and year.

        Args:
            bbref_id: Baseball Reference player ID (e.g., 'kershcl01')
            year: Season year (e.g., 2014)

        Returns:
            Dictionary of pitching stats, or None if not found
        """
        try:
            # Construct the player page URL
            first_letter = bbref_id[0].lower()
            url = f"{self.base_url}/players/{first_letter}/{bbref_id}.shtml"

            print(f"Fetching {url}")

            # Fetch the page
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Find the pitching standard table
            pitching_table = soup.find('table', {'id': 'players_standard_pitching'})
            if not pitching_table:
                print(f"No pitching table found for {bbref_id}")
                return None

            # Find the row for the specific year
            stats_row = None
            for row in pitching_table.find('tbody').find_all('tr'):
                # Skip header rows
                if row.get('class') and 'thead' in row.get('class'):
                    continue

                # Check if this is the year we want
                year_cell = row.find('th', {'data-stat': 'year_id'})
                if year_cell and year_cell.text.strip() == str(year):
                    stats_row = row
                    break

            if not stats_row:
                print(f"No pitching stats found for {bbref_id} in {year}")
                return None

            # Extract stats from the row
            stats = self._extract_pitching_stats_from_row(stats_row, year)

            return stats

        except requests.RequestException as e:
            print(f"Network error fetching pitching stats for {bbref_id}: {e}")
            return None
        except Exception as e:
            print(f"Error fetching pitching stats for {bbref_id} in {year}: {e}")
            return None

    def _extract_pitching_stats_from_row(self, row, year: int) -> Dict:
        """
        Extract pitching statistics from a BeautifulSoup table row.

        Args:
            row: BeautifulSoup tr element containing a pitcher's season stats
            year: The season year

        Returns:
            Dictionary of standardized pitching stats for Bundy formulas
        """
        # Helper to safely get a stat value from the row
        def get_stat(stat_name, default=0, as_float=False):
            """Get a stat value from the row by data-stat attribute."""
            cell = row.find('td', {'data-stat': stat_name})
            if not cell:
                return default

            text = cell.text.strip()
            if not text or text == '':
                return default

            try:
                if as_float:
                    return float(text)
                else:
                    return int(text)
            except ValueError:
                return default

        # Extract stats needed for Bundy pitcher formulas
        # Baseball Reference uses 'p_' prefix for pitching stats
        # Formula #15 needs: IP, H, BB, IBB
        # Formula #16 needs: BB, IBB, TBF
        # Formula #17 needs: H, TBF, oppBA
        # Formula #18-20 needs: 2B, 3B, HR, TBF, IBB
        # Formula #21 needs: K, TBF, IBB
        # Note: 2B and 3B allowed are NOT in standard table, will need alternate approach

        stats = {
            'year': year,

            # Core pitching stats
            'W': get_stat('p_w'),
            'L': get_stat('p_l'),
            'G': get_stat('p_g'),
            'GS': get_stat('p_gs'),
            'CG': get_stat('p_cg'),
            'SHO': get_stat('p_sho'),
            'SV': get_stat('p_sv'),

            # Innings and batters faced
            'IP': get_stat('p_ip', 0.0, as_float=True),
            'TBF': get_stat('p_bfp'),  # BFP = Batters Faced by Pitcher

            # Hits and runs allowed
            'H': get_stat('p_h'),
            'R': get_stat('p_r'),
            'ER': get_stat('p_er'),
            'HR': get_stat('p_hr'),

            # Doubles and triples allowed - NOT in standard table
            # Will be 0 for now - need to get from splits or calculate
            '2B': 0,  # TODO: Get from advanced stats if needed
            '3B': 0,  # TODO: Get from advanced stats if needed

            # Walks and strikeouts
            'BB': get_stat('p_bb'),
            'IBB': get_stat('p_ibb'),
            'SO': get_stat('p_so'),
            'HBP': get_stat('p_hbp'),

            # Rate stats
            'ERA': get_stat('p_earned_run_avg', 0.0, as_float=True),
            'WHIP': get_stat('p_whip', 0.0, as_float=True),
            'H9': get_stat('p_hits_per_nine', 0.0, as_float=True),
            'HR9': get_stat('p_hr_per_nine', 0.0, as_float=True),
            'BB9': get_stat('p_bb_per_nine', 0.0, as_float=True),
            'SO9': get_stat('p_so_per_nine', 0.0, as_float=True),

            # Opponent batting average - calculate from H and TBF
            'OppBA': 0.0,  # Will calculate below

            # Other useful stats
            'WP': get_stat('p_wp'),
            'BK': get_stat('p_bk'),

            # Metadata
            'team': 'Unknown',
            'league': 'Unknown',
        }

        # Calculate opponent batting average if we have the data
        # OppBA = H / (TBF - BB - HBP - SH - SF)
        # Since we don't have SH and SF for pitcher, approximate as: H / (TBF - BB - HBP)
        if stats['TBF'] > 0 and stats['BB'] >= 0:
            at_bats_against = stats['TBF'] - stats['BB'] - stats['HBP']
            if at_bats_against > 0:
                stats['OppBA'] = stats['H'] / at_bats_against

        # Get team and league as strings
        team_cell = row.find('td', {'data-stat': 'team_name_abbr'})
        if team_cell:
            stats['team'] = team_cell.text.strip()

        league_cell = row.find('td', {'data-stat': 'comp_name_abbr'})
        if league_cell:
            stats['league'] = league_cell.text.strip()

        return stats


# Simple test function
if __name__ == "__main__":
    fetcher = StatsFetcher()

    print("=" * 60)
    print("BATTING STATS TEST")
    print("=" * 60)

    # Test with Babe Ruth's legendary 1927 season
    print("\nBabe Ruth 1927...")
    stats = fetcher.get_stats('ruthba01', 1927, 'batting')

    if stats:
        print(f"  ✓ G: {stats['G']}, AB: {stats['AB']}, H: {stats['H']}, HR: {stats['HR']}")
        print(f"  ✓ BA: {stats['BA']:.3f}, Team: {stats['team']}")
    else:
        print("  ✗ Failed")

    print("\n" + "=" * 60)
    print("PITCHING STATS TEST")
    print("=" * 60)

    # Test Sandy Koufax's legendary 1965 season
    print("\nSandy Koufax 1965...")
    stats = fetcher.get_stats('koufasa01', 1965, 'pitching')

    if stats:
        print(f"  ✓ Record: {stats['W']}-{stats['L']}, ERA: {stats['ERA']:.2f}")
        print(f"  ✓ IP: {stats['IP']}, SO: {stats['SO']}, H: {stats['H']}")
        print(f"  ✓ TBF: {stats['TBF']}, OppBA: {stats['OppBA']:.3f}")
    else:
        print("  ✗ Failed")
