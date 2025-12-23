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


# Simple test function
if __name__ == "__main__":
    fetcher = StatsFetcher()

    # Test with Babe Ruth's legendary 1927 season
    print("Testing with Babe Ruth 1927...")
    stats = fetcher.get_batting_stats('ruthba01', 1927)

    if stats:
        print(f"\nFound stats for {stats['year']}:")
        print(f"  Games: {stats['G']}")
        print(f"  AB: {stats['AB']}, H: {stats['H']}, HR: {stats['HR']}")
        print(f"  BA: {stats['BA']:.3f}")
        print(f"  Team: {stats['team']}, League: {stats['league']}")
    else:
        print("Failed to fetch stats")
