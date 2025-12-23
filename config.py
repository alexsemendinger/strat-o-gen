"""Configuration parameters for Strat-O-Matic Card Generator."""

# Minimum PA to generate a card (set lower for historical flexibility)
MIN_PLATE_APPEARANCES = 50

# Year range supported - extended to cover all modern baseball
MIN_YEAR = 1901
MAX_YEAR = 2025

# Rate limiting for scraping
SCRAPE_DELAY_SECONDS = 1

# Server config
HOST = 'localhost'
PORT = 5000

# Cache settings
CACHE_DIR = 'data/cache'
LEAGUE_AVG_FILE = 'data/league_averages.json'

# Card generation constants
TOTAL_BATTER_CHANCES = 108  # 3 columns × 36 weighted chances each
TOTAL_CYCLE_CHANCES = 216   # Batter + Pitcher cards

# Dice probability weights (sum of 2d6)
DICE_WEIGHTS = {
    2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6,
    8: 5, 9: 4, 10: 3, 11: 2, 12: 1
}

# Result types
RESULT_TYPES = [
    'HOMERUN', 'TRIPLE', 'DOUBLE', 'SINGLE',
    'WALK', 'HBP', 'STRIKEOUT', 'OUT'
]

# Power rating thresholds
POWER_THRESHOLD_HR = 10  # HR needed for 'N' (normal) power rating
