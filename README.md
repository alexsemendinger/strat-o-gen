# Strat-O-Matic Baseball Card Generator

Generate statistically accurate, game-usable Strat-O-Matic baseball cards from historical player statistics (1901-2025).

## Features

- **Historical Coverage**: Supports players from 1901 to 2025
- **Automatic Data Fetching**: Retrieves player statistics from Baseball Reference
- **Smart Handling**: Gracefully handles missing historical data (IBB, SF, CS)
- **Web Interface**: Simple, user-friendly web interface
- **Player Disambiguation**: Handles multiple players with the same name
- **Card Rendering**: Beautiful HTML cards with PDF export capability
- **Confidence Indicators**: Shows reliability of generated cards
- **Era-Appropriate**: Adjusts formulas based on league context for each year

## Quick Start

### Windows

**First-time setup:** See [WINDOWS_SETUP.md](WINDOWS_SETUP.md) for detailed instructions.

**Daily use:**
1. Double-click `Start Strat-O-Gen.vbs`
2. The application will open in your browser automatically

### Mac / Linux

```bash
pip install -r requirements.txt
python3 app.py
```

Then visit: http://localhost:5001

## Requirements

- Python 3.10 or later
- Internet connection (for first-time data fetching)

Install dependencies with: `pip install -r requirements.txt`

## Manual Installation

```bash
pip install -r requirements.txt
python3 app.py
```

## Usage

1. Enter a player's name (e.g., "Babe Ruth", "Mike Trout")
2. Enter the year (1901-2025)
3. Click "Generate Card"
4. If multiple players match, select the correct one
5. View your generated card!

## How It Works

The generator:
1. Fetches player statistics from Baseball Reference via pybaseball
2. Retrieves era-appropriate league averages for context
3. Applies modified Bundy formulas to convert stats to card outcomes
4. Accounts for the 50/50 batter/pitcher card split in Strat-O-Matic
5. Handles missing historical data gracefully (pre-1955 IBB, pre-1954 SF, etc.)
6. Places results on a 3-column card grid respecting 2d6 dice probabilities
7. Calculates auxiliary ratings (stealing, power, speed)
8. Generates a printable HTML card

## Historical Data Notes

### Fully Supported (1955-2025)
All statistics available, highest accuracy.

### Good Support (1920-1954)
- Missing: IBB (treated as 0)
- Missing: SF before 1954
- Otherwise complete data

### Limited Support (1901-1919)
- Missing: IBB, SF, and some CS data
- Cards generated with warnings
- Lower confidence ratings

The generator always works, but older years come with appropriate warnings about data limitations.

## Card Confidence Levels

- **HIGH**: Complete data, adequate sample size (300+ PA)
- **MEDIUM**: Minor missing data or smaller sample (150-300 PA)
- **LOW**: Significant missing data or very small sample (<150 PA)

## Technical Details

### Architecture
- **Backend**: Python 3 + Flask
- **Data Source**: pybaseball (Baseball Reference)
- **Card Engine**: Modified Bundy formulas with era adjustments
- **PDF Generation**: WeasyPrint
- **Caching**: Local JSON cache for performance

### File Structure
```
strat-o-gen/
├── app.py                  # Flask web application
├── generate_card.py        # Command-line interface
├── stats_fetcher.py        # Data fetching (pybaseball wrapper)
├── card_formulas.py        # Bundy formulas for card generation
├── card_layout.py          # Card grid generation
├── league_averages.py      # League average handling
├── requirements.txt        # Python dependencies
├── Start Strat-O-Gen.vbs   # Windows launcher (double-click this)
├── start_windows.bat       # Windows batch script
├── WINDOWS_SETUP.md        # Windows setup guide
└── data/
    ├── cache/              # Cached player data
    └── league_averages/    # Cached league averages
```

## Formula Basis

This generator uses community-researched formulas (primarily the "Bundy formulas") to approximate official Strat-O-Matic cards. These formulas:

- Are based on reverse-engineering, not official SOM sources
- Account for the batter-pitcher card interaction
- Adjust for era-specific league contexts
- Are validated through simulation testing

**Note**: Generated cards are approximations and may differ slightly from official SOM cards.

## Limitations

- **Pitcher cards**: Not yet implemented (batters only)
- **Advanced game features**: Basic game cards only (no platoon splits)
- **Fielding ratings**: Simplified (requires defensive metrics)
- **Minor leagues**: MLB only

## Troubleshooting

### "No players found"
- Check spelling of player name
- Try last name only
- Verify the player played in that year

### "Insufficient plate appearances"
- Player didn't play enough in that year
- Try a different season
- Threshold is 50 PA (adjustable in config.py)

### Server won't start
- Ensure Python 3.10+ is installed
- Try manual installation: `pip install -r requirements.txt`
- Check port 5001 isn't already in use

## Credits

- **Strat-O-Matic**: Card game by Strat-O-Matic Game Company
- **Bundy Formulas**: Community research by Bruce Bundy and others
- **Baseball Reference**: Historical statistics
- **pybaseball**: Python baseball statistics library

## License

This is an independent fan project. Strat-O-Matic is a registered trademark of the Strat-O-Matic Game Company. This project is not affiliated with or endorsed by Strat-O-Matic.

Generated cards are for personal use only.

## Version

Version 1.0 - Initial Release

## Support

For issues or questions, see the specification document: `STRAT_CARD_MAKER_SPEC_v2.md`
