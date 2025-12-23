"""Manual data entry for when APIs are down."""

# Derek Jeter 2003 season stats
MANUAL_PLAYERS = {
    'jeterde01_2003': {
        'player_id': 'jeterde01',
        'player_name': 'Derek Jeter',
        'year': 2003,
        'team': 'NYY',
        'league': 'AL',
        'G': 119,
        'AB': 482,
        'PA': 550,
        'H': 156,
        '2B': 25,
        '3B': 3,
        'HR': 10,
        'R': 87,
        'RBI': 52,
        'BB': 43,
        'SO': 88,
        'SB': 11,
        'CS': 5,
        'BA': 0.324,
        'OBP': 0.393,
        'SLG': 0.450,
        'HBP': 5,
        'SF': 4,
        'SH': 1,
        'IBB': 3,
        'GDP': 8,
        'positions': ['SS'],
        'bats': 'R',
        'throws': 'R',
        'warnings': ['Using manually entered data - API sources unavailable']
    },
    # Add more players as needed
}

# League averages by year
MANUAL_LEAGUE_AVERAGES = {
    2003: {
        'AL': {
            'BA': 0.267,
            'HR_per_PA': 0.028,
            'BB_per_PA': 0.087,
            'K_per_PA': 0.171,
            '2B_per_PA': 0.045,
            '3B_per_PA': 0.005,
            'HBP_per_PA': 0.010,
        },
        'NL': {
            'BA': 0.264,
            'HR_per_PA': 0.027,
            'BB_per_PA': 0.083,
            'K_per_PA': 0.169,
            '2B_per_PA': 0.044,
            '3B_per_PA': 0.005,
            'HBP_per_PA': 0.009,
        }
    },
    # Add more years as needed
}

def get_manual_player_data(player_id: str, year: int):
    """Get manually entered player data."""
    key = f"{player_id}_{year}"
    return MANUAL_PLAYERS.get(key)

def get_manual_league_averages(year: int, league: str):
    """Get manually entered league averages."""
    year_data = MANUAL_LEAGUE_AVERAGES.get(year, {})
    return year_data.get(league)
