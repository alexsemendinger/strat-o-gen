"""
Fetch and cache league-average statistics by year and league.

This is critical for:
1. Accurate card generation (batter formulas need league context)
2. Accurate validation (need era-appropriate average pitcher)
"""

import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict
import json
from pathlib import Path


class LeagueAveragesFetcher:
    """Fetches league-average statistics from Baseball Reference."""

    def __init__(self, cache_dir: str = 'data/league_averages'):
        """Initialize the fetcher with cache directory."""
        self.base_url = "https://www.baseball-reference.com"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Baseball Card Generator)'
        })
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_league_averages(self, year: int, league: str) -> Optional[Dict]:
        """
        Get league-average statistics for a specific year and league.

        Args:
            year: Season year (e.g., 2001, 1972)
            league: 'AL' or 'NL'

        Returns:
            Dictionary with league averages or None if not found
        """
        # Check cache first
        cache_file = self.cache_dir / f"{year}_{league}.json"
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return json.load(f)

        # Fetch from Baseball Reference
        print(f"Fetching {league} league averages for {year}...")
        averages = self._fetch_league_stats(year, league)

        if averages:
            # Cache it
            with open(cache_file, 'w') as f:
                json.dump(averages, f, indent=2)

        return averages

    def _fetch_league_stats(self, year: int, league: str) -> Optional[Dict]:
        """
        Scrape league statistics from Baseball Reference.

        URL format: https://www.baseball-reference.com/leagues/AL/2001.shtml
        """
        try:
            url = f"{self.base_url}/leagues/{league}/{year}.shtml"
            print(f"  Fetching {url}")

            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find the team batting table
            batting_table = soup.find('table', {'id': 'teams_standard_batting'})
            if not batting_table:
                print(f"  No batting table found for {league} {year}")
                return None

            # Find the league average row (usually at the bottom, often labeled "Avg" or has class "stat_total")
            # Look for row with team abbr "Avg" or similar
            avg_row = None
            tbody = batting_table.find('tbody')
            for row in tbody.find_all('tr'):
                team_cell = row.find('th', {'data-stat': 'team_name'})
                if team_cell:
                    team_text = team_cell.text.strip()
                    # League average row is often "League Average" or just at the end
                    if 'Average' in team_text or team_text == 'Avg':
                        avg_row = row
                        break

            # If not found, try looking for tfoot (league totals/averages)
            if not avg_row:
                tfoot = batting_table.find('tfoot')
                if tfoot:
                    avg_row = tfoot.find('tr')

            if not avg_row:
                print(f"  Could not find league average row for {league} {year}")
                return None

            # Extract statistics
            averages = self._extract_league_stats(avg_row, year, league)
            return averages

        except Exception as e:
            print(f"  Error fetching league averages: {e}")
            return None

    def _extract_league_stats(self, row, year: int, league: str) -> Dict:
        """Extract league average statistics from a table row."""

        def get_stat(stat_name, default=0, as_float=False):
            """Safely get a stat value from the row."""
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

        # Extract raw stats
        g = get_stat('G')
        pa = get_stat('PA')
        ab = get_stat('AB')
        h = get_stat('H')
        doubles = get_stat('2B')
        triples = get_stat('3B')
        hr = get_stat('HR')
        bb = get_stat('BB')
        so = get_stat('SO')
        hbp = get_stat('HBP')
        sf = get_stat('SF')
        ibb = get_stat('IBB')

        # Calculate rates (per PA)
        if pa > 0:
            ba = h / ab if ab > 0 else 0.0
            hr_per_pa = hr / pa
            bb_per_pa = (bb - ibb) / pa  # Non-intentional walks
            k_per_pa = so / pa
            doubles_per_pa = doubles / pa
            triples_per_pa = triples / pa
            hbp_per_pa = hbp / pa
        else:
            # Fallback to reasonable defaults
            ba = 0.250
            hr_per_pa = 0.025
            bb_per_pa = 0.085
            k_per_pa = 0.20
            doubles_per_pa = 0.04
            triples_per_pa = 0.005
            hbp_per_pa = 0.01

        return {
            'year': year,
            'league': league,
            'BA': ba,
            'HR_per_PA': hr_per_pa,
            'BB_per_PA': bb_per_pa,
            'K_per_PA': k_per_pa,
            '2B_per_PA': doubles_per_pa,
            '3B_per_PA': triples_per_pa,
            'HBP_per_PA': hbp_per_pa,
            # Store raw stats for reference
            'raw': {
                'G': g,
                'PA': pa,
                'AB': ab,
                'H': h,
                '2B': doubles,
                '3B': triples,
                'HR': hr,
                'BB': bb,
                'SO': so,
                'HBP': hbp,
                'SF': sf,
                'IBB': ibb,
            }
        }


# Test the fetcher
if __name__ == "__main__":
    fetcher = LeagueAveragesFetcher()

    print("=" * 70)
    print("Testing League Averages Fetcher")
    print("=" * 70)

    # Test with a few different eras
    test_cases = [
        (2001, 'AL', 'Modern era (Tim Raines)'),
        (1972, 'AL', 'Dead ball era (Nolan Ryan)'),
        (1983, 'AL', '1980s (Jack Morris)'),
        (1927, 'AL', 'Babe Ruth era'),
    ]

    for year, league, description in test_cases:
        print(f"\n{description}: {league} {year}")
        print("-" * 70)

        averages = fetcher.get_league_averages(year, league)

        if averages:
            print(f"  BA:      {averages['BA']:.3f}")
            print(f"  HR/PA:   {averages['HR_per_PA']:.3f} ({averages['HR_per_PA']*100:.1f}%)")
            print(f"  BB/PA:   {averages['BB_per_PA']:.3f} ({averages['BB_per_PA']*100:.1f}%)")
            print(f"  K/PA:    {averages['K_per_PA']:.3f} ({averages['K_per_PA']*100:.1f}%)")
            print(f"  2B/PA:   {averages['2B_per_PA']:.3f}")
            print(f"  3B/PA:   {averages['3B_per_PA']:.3f}")
        else:
            print("  Failed to fetch")
