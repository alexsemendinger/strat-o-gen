# Strat-O-Matic Card Maker — Specification

## Project Overview

**Goal:** Build a local web application that generates statistically accurate, game-usable Strat-O-Matic baseball cards from historical player statistics.

**User:** A non-technical person who will double-click a desktop shortcut, see a browser interface, enter a player name and year, and receive a printable card.

**Success criteria:**
1. Cards produce statistically accurate results when used in gameplay (validated by simulation)
2. Interface requires zero technical knowledge
3. Output is a clean, printable PDF or HTML page

---

## Table of Contents

1. [User Experience Requirements](#1-user-experience-requirements)
2. [Technical Architecture](#2-technical-architecture)
3. [Data Acquisition](#3-data-acquisition)
4. [How Strat-O-Matic Cards Work](#4-how-strat-o-matic-cards-work)
5. [Card Generation: The Hard Problem](#5-card-generation-the-hard-problem)
6. [Card Rendering and Output](#6-card-rendering-and-output)
7. [Test Suite Requirements](#7-test-suite-requirements)
8. [Packaging and Deployment](#8-packaging-and-deployment)
9. [Reference Links and Resources](#9-reference-links-and-resources)
10. [Open Questions and Decisions](#10-open-questions-and-decisions)

---

## 1. User Experience Requirements

### 1.1 Launch Experience

User double-clicks a desktop shortcut. This should:
1. Start the Python server (invisibly — no terminal window)
2. Wait for server to be ready
3. Open default browser to `http://localhost:5000`

If the server is already running, just open the browser.

### 1.2 Web Interface

**Main page:** Single-page application with:
- Title: "Strat-O-Matic Card Maker"
- Input field: "Player Name" (text, with autocomplete if feasible)
- Input field: "Year" (dropdown or text, validated to supported range—see Section 3.5)
- Button: "Generate Card"
- Loading indicator while processing
- Error messages displayed clearly

**Results display:**
- Card preview (HTML rendering)
- Confidence indicator (see Section 5.7)
- "Download PDF" button
- "Make Another Card" button

### 1.3 Error Handling

Handle these cases with user-friendly messages:
- Player name not found
- Player didn't play in specified year
- Multiple players with same name (present disambiguation UI)
- Network error fetching stats
- Player has insufficient plate appearances (see Section 10.1 for threshold)
- Player played for multiple teams that year (present team selection or aggregate option)

### 1.4 Warnings (Not Errors)

Display warnings but still generate card:
- Missing historical data (e.g., IBB not tracked before 1955)
- Formula produced clamped values (negative intermediate results)
- Very unusual stat line that may produce unreliable results

---

## 2. Technical Architecture

### 2.1 Stack

```
Backend:  Python 3.10+ with Flask
Scraping: pybaseball (preferred) or requests + BeautifulSoup4
PDF:      WeasyPrint or browser print-to-PDF
Frontend: Plain HTML/CSS/JS (no framework needed)
Testing:  pytest
```

**Decision: Use pybaseball if it provides all required stats.** It handles rate limiting and caching. Only build custom scraper if pybaseball is insufficient. Verify pybaseball coverage before starting implementation.

### 2.2 File Structure

```
strat-card-maker/
├── app.py                     # Flask application, routes
├── scraper.py                 # Data fetching (wraps pybaseball or custom)
├── card_engine.py             # Stats → card conversion (CORE LOGIC)
├── card_renderer.py           # Card data → HTML/PDF
├── config.py                  # All configurable parameters (see 2.4)
├── templates/
│   ├── index.html
│   ├── card.html
│   ├── disambiguation.html    # For same-name players
│   └── error.html
├── static/
│   ├── style.css
│   └── card_template.css
├── data/
│   ├── league_averages.json   # Historical league data by year
│   ├── average_pitcher_cards/ # Era-appropriate pitcher cards
│   └── cache/                 # Cached player data
├── tests/
│   ├── test_scraper.py
│   ├── test_card_engine.py
│   ├── test_simulation.py     # Statistical validation
│   └── known_cards/           # Validation fixtures (if available)
├── requirements.txt
├── start_windows.bat
├── start_mac.command
└── README.md
```

### 2.3 Data Flow

```
User Input (name, year)
    ↓
Scraper: Check cache → Fetch if needed → Return stats
    ↓
Validation: Check for missing data, flag warnings
    ↓
Card Engine: Apply formulas with era-appropriate league context
    ↓
Card Data: {columns, ratings, warnings, confidence}
    ↓
Renderer: Generate HTML/PDF
    ↓
User: View and download
```

### 2.4 Configuration File

All tunable parameters should live in `config.py`, not scattered through code:

```python
# config.py

# Minimum PA to generate a card (see Section 10.1)
MIN_PLATE_APPEARANCES = 150  # DECISION NEEDED: what threshold?

# Year range supported
MIN_YEAR = 1955  # IBB tracking starts (see Section 3.5)
MAX_YEAR = 2024

# Rate limiting for scraping
SCRAPE_DELAY_SECONDS = 3

# Formula constants - these are starting points, may need adjustment
# See Section 5 for how these are used
FORMULA_CONSTANTS = {
    # These will be loaded from league_averages.json per-year
    # This is just the structure
}
```

---

## 3. Data Acquisition

### 3.1 Data Source

**Primary:** Baseball Reference via pybaseball library (or direct scraping if needed)

**Decision required before implementation:** Test pybaseball to confirm it provides:
- All stats listed in 3.3
- Player disambiguation (multiple players with same name)
- Multi-team season handling
- Reasonable rate limiting

### 3.2 Player Identification

**Problem:** Multiple players share names (e.g., "Mike Smith").

**Solution:** 
1. Search returns list of matching players with disambiguating info (years active, teams, positions)
2. If multiple matches, present selection UI to user
3. Internally use Baseball Reference player IDs, not names

### 3.3 Required Statistics (Batting)

```python
REQUIRED_BATTING_STATS = {
    # Always available
    'G':    int,   # Games played
    'AB':   int,   # At bats
    'R':    int,   # Runs scored
    'H':    int,   # Hits
    '2B':   int,   # Doubles
    '3B':   int,   # Triples
    'HR':   int,   # Home runs
    'RBI':  int,   # Runs batted in
    'BB':   int,   # Walks
    'SO':   int,   # Strikeouts
    
    # Usually available, may be missing in early years
    'SB':   int,   # Stolen bases
    'CS':   int,   # Caught stealing (spotty before 1951)
    'HBP':  int,   # Hit by pitch (gaps in historical data)
    'SF':   int,   # Sacrifice flies (tracked from 1954)
    'SH':   int,   # Sacrifice hits
    'IBB':  int,   # Intentional walks (from 1955)
    'GDP':  int,   # Grounded into double play
    
    # Derived (calculate if not provided)
    'PA':   int,   # Plate appearances = AB + BB + HBP + SF + SH
    'BA':   float, # Batting average = H / AB
    'OBP':  float, # On-base percentage
    'SLG':  float, # Slugging percentage
}
```

**Note on PA calculation:** PA = AB + BB + HBP + SF + SH. If SF/SH unavailable, PA = AB + BB + HBP (will slightly undercount, ~2-3%). Log warning when using incomplete PA.

### 3.4 Required Statistics (Pitching) — OUT OF SCOPE

Pitcher cards are **not** in scope for initial implementation. This spec covers batter cards only.

### 3.5 Supported Year Range

**Recommended minimum year: 1955** (when IBB tracking begins)

Earlier years can be supported with degraded accuracy:
- 1951-1954: Missing IBB (treat as 0, warn user)
- Before 1951: Missing CS for many players
- Before 1920: Significant data gaps

**Decision required:** What is the acceptable minimum year? See Section 10.2.

### 3.6 Multi-Team Seasons

When a player played for multiple teams in one year:

**Options:**
1. Present team selection to user, generate card for that stint only
2. Aggregate stats across all teams (this is what official SOM does)
3. Default to aggregate with option to select team

**Recommendation:** Option 3 — aggregate by default, match official SOM behavior.

### 3.7 Missing Data Handling

| Stat | If Missing | Action |
|------|------------|--------|
| IBB | Before 1955 | Use 0, add warning to card |
| CS | Before 1951 | Use 0, add warning, steal rating unreliable |
| HBP | Sparse | Use 0, add warning |
| SF | Before 1954 | Use 0, PA calculation note |
| GDP | Often missing | Use league average rate × PA, add warning |

**Never silently use 0.** Always flag when substituting missing data.

### 3.8 Caching

Cache all fetched data locally:
- Store in `data/cache/` as JSON files
- Key by player ID + year
- Include fetch timestamp
- Never re-fetch cached data unless user explicitly requests

This protects against Baseball Reference rate limiting/blocking.

### 3.9 Example Scraper Output

```python
{
    'player_id': 'gehrilo01',
    'player_name': 'Lou Gehrig',
    'year': 1934,
    'team': 'NYY',  # Or ['NYY', 'BOS'] for multi-team
    'league': 'AL',
    'stats': {
        'G': 154,
        'PA': 690,
        'AB': 579,
        'H': 210,
        '2B': 40,
        '3B': 6,
        'HR': 49,
        'BB': 109,
        'SO': 31,
        'SB': 9,
        'CS': 5,
        'HBP': 2,
        'SF': None,  # Not tracked
        'IBB': None, # Not tracked
        'GDP': None, # Not available
    },
    'positions': ['1B'],
    'bats': 'L',
    'throws': 'L',
    'warnings': ['IBB not tracked in 1934', 'SF not tracked in 1934'],
}
```

---

## 4. How Strat-O-Matic Cards Work

This section describes the game mechanics. Understanding this is essential for implementing card generation.

### 4.1 The Dice System

Strat-O-Matic uses **three six-sided dice**:

**White die (control die):** Determines which card to read
- 1-3 → Batter's card (columns 1, 2, or 3)
- 4-6 → Pitcher's card (columns 4, 5, or 6)

**Two colored dice:** Summed (2-12) to determine the row within the column

**Result:** 50% of plate appearances resolve on batter's card, 50% on pitcher's card.

### 4.2 The 2d6 Probability Distribution

| Sum | Ways to Roll | Probability | "Chances" out of 36 |
|-----|--------------|-------------|---------------------|
| 2   | 1            | 2.78%       | 1                   |
| 3   | 2            | 5.56%       | 2                   |
| 4   | 3            | 8.33%       | 3                   |
| 5   | 4            | 11.11%      | 4                   |
| 6   | 5            | 13.89%      | 5                   |
| 7   | 6            | 16.67%      | 6                   |
| 8   | 5            | 13.89%      | 5                   |
| 9   | 4            | 11.11%      | 4                   |
| 10  | 3            | 8.33%       | 3                   |
| 11  | 2            | 5.56%       | 2                   |
| 12  | 1            | 2.78%       | 1                   |

### 4.3 Card "Chances"

Each column has 36 weighted chances (per 2d6 distribution).
Each card has 3 columns = **108 total chances per card**.
Full cycle (batter + pitcher cards) = **216 chances**.

**Key insight:** A "chance" is not a slot—it's a probability unit. Dice roll 7 represents 6 chances; dice roll 2 represents 1 chance. When placing results on a card, you must account for these weights.

### 4.4 Card Structure

A batter's card has three columns (1, 2, 3) and eleven rows (dice sums 2-12).

In **Basic** play: All three columns are identical or used interchangeably.
In **Advanced** play: Columns represent platoon splits (vs. LHP/RHP).

**This spec covers Basic cards only.** All three columns will be identical.

### 4.5 Result Types

**Positive outcomes:**
- `HOMERUN` — Home run
- `TRIPLE` — Triple  
- `DOUBLE` — Double (may have `*` or `**` for runner advancement)
- `SINGLE` — Single (may have `*` or `**`)
- `WALK` — Base on balls
- `HBP` — Hit by pitch (batter card only)

**Negative outcomes:**
- `STRIKEOUT` — Strikeout
- `gb(A)` — Groundball out (A indicates double-play potential)
- `gb(B)` or `gb(C)` — Groundball out (lower DP potential)
- `fb(X)` — Flyball out
- `lo` — Lineout
- `po` — Popout
- `fo` — Foulout

**Symbols:**
- `*` after hit = runners advance one extra base
- `**` after hit = runners advance two extra bases

### 4.6 The Batter-Pitcher Interaction

**Critical concept:** A batter's card is designed assuming they face a league-average pitcher. The pitcher's card handles deviation from average.

Example: If league walk rate is 8.5% and a batter walks 12%:
- ~4.25% of walks come from "average pitcher being average" (on pitcher card)
- ~7.75% come from batter being above-average at drawing walks (on batter card)

The card generation formulas must account for this split. The batter's card only encodes their *deviation from league average*, not their raw stats.

### 4.7 Average Pitcher Card

To simulate a batter's card accurately, you need an "average pitcher card" that represents what a league-average pitcher's card looks like.

**Important:** This varies by era. A 1968 average pitcher card (Year of the Pitcher) looks very different from a 2019 average pitcher card (juiced ball era).

The average pitcher card must be generated from league-average statistics for each year/league. See Section 5.6.

---

## 5. Card Generation: The Hard Problem

**WARNING:** This is the most complex and uncertain part of the spec. The exact formulas Strat-O-Matic uses are proprietary. What follows is based on community reverse-engineering (primarily the "Bundy formulas") which are *approximations*.

### 5.1 The Fundamental Approach

1. **Calculate target frequencies:** Given a player's stats, determine what % of PAs should result in HR, 3B, 2B, 1B, BB, HBP, K, outs
2. **Adjust for league context:** The batter's card only needs to produce results *above/below league average*—the pitcher card handles the baseline
3. **Convert to chances:** Map frequencies to the 108-chance batter card
4. **Place on card:** Assign results to specific dice roll positions

### 5.2 The Bundy Formulas

These formulas are from community reverse-engineering. **They are approximations and may not be perfectly accurate.** The original source is Bruce Bundy's analysis on somworld.com.

```
[CONFIDENCE: MEDIUM]
These formulas are widely used in the SOM community but are not officially validated.
They should be treated as a starting point, not ground truth.
```

**Input variables:**
```python
AB = at_bats
H = hits
_2B = doubles
_3B = triples
HR = home_runs
BB = walks
IBB = intentional_walks  # 0 if unavailable
HBP = hit_by_pitch
SO = strikeouts
SF = sacrifice_flies  # 0 if unavailable

# Effective PA (excludes IBB which bypass the card)
PA_eff = AB + (BB - IBB) + HBP + SF
```

**Formula structure:**

Each formula calculates chances out of 108 for the batter's card. The general form is:

```
result_chances = ((player_rate × 216) / PA_eff) - league_average_contribution
```

Where:
- `216` = full cycle (both cards)
- `league_average_contribution` = what you'd expect from facing average pitchers

The league_average_contribution values are **era-dependent** and must be calculated from league statistics, not hardcoded.

### 5.3 Era-Dependent Parameters

**DO NOT HARDCODE these values.** They must be calculated from actual league statistics for the year in question.

For each year/league, you need:
- League batting average
- League HR per PA
- League BB per PA (non-intentional)
- League K per PA
- League 2B per PA
- League 3B per PA
- League HBP per PA

These determine the "average pitcher card" contribution that gets subtracted in the formulas.

### 5.4 League Averages Data

Store in `data/league_averages.json`:

```json
{
  "1968": {
    "AL": {
      "BA": 0.230,
      "HR_per_PA": 0.020,
      "BB_per_PA": 0.073,
      "K_per_PA": 0.147,
      "2B_per_PA": 0.035,
      "3B_per_PA": 0.006,
      "HBP_per_PA": 0.005
    },
    "NL": { ... }
  },
  "2019": {
    "AL": {
      "BA": 0.252,
      "HR_per_PA": 0.035,
      "BB_per_PA": 0.088,
      "K_per_PA": 0.232,
      "2B_per_PA": 0.044,
      "3B_per_PA": 0.004,
      "HBP_per_PA": 0.010
    },
    "NL": { ... }
  }
}
```

**This data must be populated for all supported years.** It can be scraped from Baseball Reference league pages:
- https://www.baseball-reference.com/leagues/AL/{year}.shtml
- https://www.baseball-reference.com/leagues/NL/{year}.shtml

### 5.5 Formula Implementation Guidance

```
[CONFIDENCE: LOW]
The specific formula implementations below are my best understanding of the Bundy formulas.
They may contain errors. DO NOT TRUST these blindly.
Validate against simulation (Section 7.3) before considering them correct.
```

The formulas follow this pattern (pseudocode):

```python
def calculate_batter_card_chances(player_stats, league_avg):
    """
    Calculate chances (out of 108) for each outcome on the batter's card.
    
    Returns dict with keys: walk, hbp, strikeout, home_run, triple, double, single, outs
    """
    
    PA_eff = calculate_effective_pa(player_stats)
    
    # Walk chances
    # Player's walk contribution above what average pitcher would yield
    player_bb_rate = (player_stats['BB'] - player_stats['IBB']) / PA_eff
    avg_pitcher_bb_contribution = league_avg['BB_per_PA'] * 108 / 216  # Half comes from pitcher
    walk_chances = (player_bb_rate * 216) - (avg_pitcher_bb_contribution * 2)
    walk_chances = max(0, walk_chances)  # Can't be negative
    
    # HBP - only appears on batter card (no pitcher contribution)
    hbp_chances = (player_stats['HBP'] / PA_eff) * 108
    
    # Similar pattern for other outcomes...
    # [IMPLEMENTATION NOTE: Work out exact formulas through simulation validation]
    
    return chances
```

**Critical:** The exact subtraction values (what I called `avg_pitcher_bb_contribution`) are the crux of getting this right. They must be derived from league averages, not hardcoded.

### 5.6 Average Pitcher Card Generation

For simulation and validation, you need an "average pitcher card" for each era.

**Approach:**
1. Take league-average statistics for the year
2. Generate a pitcher card that, when paired with an average batter, produces league-average outcomes
3. This is the inverse of the batter card problem

```
[CONFIDENCE: LOW]
I am not confident in how to correctly generate the average pitcher card.
This may require research into SOM methodology or empirical fitting.
```

### 5.7 Confidence Indicators

Because the formulas are approximations, the generated card should include confidence metadata:

```python
{
    'card': { ... },
    'confidence': {
        'overall': 'HIGH' | 'MEDIUM' | 'LOW',
        'warnings': [
            'Strikeout chances clamped from -3 to 0',
            'IBB data not available for 1934',
        ],
        'clamped_values': ['strikeout'],
        'missing_data': ['IBB', 'SF'],
    }
}
```

Display this to the user so they know when a card may be unreliable.

### 5.8 Card Layout Algorithm

Once you have chances for each outcome, you must place them on the card grid.

**Principles:**
1. Results must respect dice probability weights (dice sum 7 = 6 chances, dice sum 2 = 1 chance)
2. Best results traditionally go on rare rolls (2, 3, 11, 12)
3. Common results (singles, outs) go on common rolls (6, 7, 8)
4. Each of the 3 columns must have exactly 36 weighted chances

**Algorithm sketch:**

```python
def place_results_on_card(chances: dict) -> dict:
    """
    Place results on a 3×11 card grid respecting dice weights.
    
    Returns: {column: {dice_sum: result_string}}
    """
    # Each column needs 36 weighted chances
    # Dice sum N provides DICE_WEIGHTS[N] chances
    
    DICE_WEIGHTS = {2:1, 3:2, 4:3, 5:4, 6:5, 7:6, 8:5, 9:4, 10:3, 11:2, 12:1}
    
    # Convert float chances to allocations respecting weights
    # This is a bin-packing problem
    
    # [IMPLEMENTATION NOTE: This requires careful implementation.
    # The naive approach of sorting and filling doesn't respect weights correctly.
    # May need to iterate: place results, check weighted totals, adjust.]
```

```
[CONFIDENCE: MEDIUM on principles, LOW on specific algorithm]
The principles are correct. The specific algorithm needs to be worked out carefully
and validated against known good cards.
```

### 5.9 Ratings Calculation

Beyond the card grid, SOM cards have auxiliary ratings.

**Stealing:**
```python
def calculate_steal_rating(SB, CS):
    attempts = SB + CS
    if attempts == 0:
        return 'E'  # No steal attempts
    
    success_rate = SB / attempts
    
    # Thresholds are approximate
    if success_rate >= 0.80 and attempts >= 20:
        return 'A'
    elif success_rate >= 0.70 and attempts >= 10:
        return 'B'
    elif success_rate >= 0.60:
        return 'C'
    elif success_rate >= 0.50:
        return 'D'
    else:
        return 'E'
```

```
[CONFIDENCE: LOW]
These thresholds are guesses. Real SOM uses proprietary formulas.
The general principle (higher success rate + more attempts = better rating) is correct.
```

**Power rating:**
- `N` (Normal) = can hit HR off pitcher cards
- `W` (Weak) = HR on pitcher cards become singles

```python
def calculate_power_rating(HR):
    # Threshold is approximate
    return 'N' if HR >= 10 else 'W'
```

**Speed, Bunting, Hit-and-Run:** These require additional data (triples rate, player type heuristics) and are **lower priority**. Implement basic versions or omit initially.

**Fielding:** Requires defensive statistics not covered in this spec. **Out of scope** for initial implementation. Use placeholder average values.

---

## 6. Card Rendering and Output

### 6.1 Visual Design

The card should resemble an actual SOM card layout:
- Player name and year prominently displayed
- Team, position, bats/throws
- Key stats (AVG, HR, RBI)
- 3-column × 11-row grid with results
- Ratings section at bottom

**Card dimensions:** Verify against actual SOM cards before finalizing. Standard trading card is 2.5" × 3.5" but SOM cards may differ.

### 6.2 HTML Template

```html
<div class="card">
    <div class="header">
        <div class="player-name">{{ player_name }}</div>
        <div class="info">{{ year }} {{ team }} | {{ position }} | B:{{ bats }} T:{{ throws }}</div>
        <div class="stats">AVG:{{ avg }} HR:{{ hr }} RBI:{{ rbi }}</div>
    </div>
    
    <div class="card-grid">
        <!-- Column headers -->
        <div class="dice-col"></div>
        <div class="col-header">1</div>
        <div class="col-header">2</div>
        <div class="col-header">3</div>
        
        <!-- Rows 2-12 -->
        {% for dice in range(2, 13) %}
        <div class="dice-val">{{ dice }}</div>
        <div class="result">{{ card[1][dice] }}</div>
        <div class="result">{{ card[2][dice] }}</div>
        <div class="result">{{ card[3][dice] }}</div>
        {% endfor %}
    </div>
    
    <div class="ratings">
        Power: {{ power }} | Steal: {{ steal }} | Speed: {{ speed }}
    </div>
    
    {% if warnings %}
    <div class="warnings">
        ⚠️ {{ warnings | join(', ') }}
    </div>
    {% endif %}
</div>
```

### 6.3 PDF Generation

**Option A: WeasyPrint**
```python
from weasyprint import HTML
HTML(string=html_content).write_pdf(output_path)
```

**Option B: Browser print-to-PDF**
Provide a print-friendly stylesheet and let user print from browser.

**Recommendation:** Implement both. WeasyPrint for one-click download, print stylesheet for user control.

### 6.4 Print Stylesheet

```css
@media print {
    .card {
        page-break-inside: avoid;
        border: 1px solid black;
    }
    .warnings {
        font-size: 8pt;
        color: #666;
    }
    /* Hide UI elements */
    button, .no-print { display: none; }
}
```

---

## 7. Test Suite Requirements

### 7.1 Unit Tests

Test individual formula components:

```python
def test_walk_chances_high_walk_player():
    """High-walk player should have positive walk chances."""
    stats = {'AB': 400, 'BB': 100, 'IBB': 5, 'HBP': 5, ...}
    league = {'BB_per_PA': 0.085, ...}
    chances = calculate_batter_card_chances(stats, league)
    assert chances['walk'] > 10

def test_walk_chances_low_walk_player():
    """Low-walk player may have 0 walk chances (clamped)."""
    stats = {'AB': 500, 'BB': 20, 'IBB': 0, 'HBP': 2, ...}
    league = {'BB_per_PA': 0.085, ...}
    chances = calculate_batter_card_chances(stats, league)
    assert chances['walk'] >= 0  # Never negative

def test_total_chances_equals_108():
    """Batter card chances must sum to 108."""
    # Test with multiple player types
    for stats in [power_hitter, contact_hitter, slap_hitter]:
        chances = calculate_batter_card_chances(stats, league)
        total = sum(chances.values())
        assert abs(total - 108) < 0.5  # Allow small rounding error
```

### 7.2 Integration Tests

Test end-to-end flow:

```python
def test_generate_card_lou_gehrig_1934():
    """Generate card for known elite player."""
    card = generate_card('Lou Gehrig', 1934)
    
    assert card is not None
    assert card['player_name'] == 'Lou Gehrig'
    assert card['year'] == 1934
    assert 'grid' in card
    assert len(card['grid']) == 3  # 3 columns
    assert len(card['grid'][1]) == 11  # 11 rows per column

def test_generate_card_handles_missing_data():
    """Card generation should handle missing IBB gracefully."""
    card = generate_card('Babe Ruth', 1927)
    
    assert card is not None
    assert 'IBB not tracked' in card['warnings']
```

### 7.3 Simulation Validation (Critical)

**This is the most important test.** Simulate many plate appearances and verify statistical accuracy.

```python
def simulate_pa(batter_card, pitcher_card):
    """Simulate one plate appearance."""
    white_die = random.randint(1, 6)
    colored_dice = random.randint(1, 6) + random.randint(1, 6)
    
    if white_die <= 3:
        return batter_card[white_die][colored_dice]
    else:
        return pitcher_card[white_die][colored_dice]

def test_simulation_batting_average():
    """Simulated BA should match player's actual BA within tolerance."""
    player_stats = fetch_stats('Lou Gehrig', 1934)  # .363 BA
    batter_card = generate_card(player_stats)
    pitcher_card = get_average_pitcher_card(1934, 'AL')
    
    hits = 0
    at_bats = 0
    
    for _ in range(50000):  # Large sample for statistical stability
        result = simulate_pa(batter_card, pitcher_card)
        if is_hit(result):
            hits += 1
            at_bats += 1
        elif is_at_bat(result):  # Excludes walks, HBP
            at_bats += 1
    
    simulated_ba = hits / at_bats
    expected_ba = player_stats['BA']
    
    # Should be within 1.5% (allowing for statistical variance)
    assert abs(simulated_ba - expected_ba) < 0.015, \
        f"Simulated BA {simulated_ba:.3f} differs from expected {expected_ba:.3f}"

def test_simulation_home_run_rate():
    """Simulated HR rate should match player's actual HR rate."""
    # Similar structure to above
    pass

def test_simulation_strikeout_rate():
    """Simulated K rate should match player's actual K rate."""
    pass

def test_simulation_walk_rate():
    """Simulated BB rate should match player's actual BB rate."""
    pass
```

**Run simulation tests for multiple player archetypes:**
- Power hitter (high HR, high K)
- Contact hitter (high BA, low K)
- Speedster (high 3B, high SB)
- Three-true-outcomes (high HR, high BB, high K)
- Slap hitter (low power, high BA)

### 7.4 Known Card Validation (If Available)

If you have access to actual SOM cards, compare generated cards:

```python
def test_against_known_card():
    """Compare generated card to known official SOM card."""
    known = load_known_card('gehrig_1934.json')
    generated = generate_card('Lou Gehrig', 1934)
    
    # Compare chance distributions (allow some variance)
    for outcome in ['home_run', 'strikeout', 'walk', 'single']:
        known_chances = count_chances(known, outcome)
        gen_chances = count_chances(generated, outcome)
        assert abs(known_chances - gen_chances) <= 3, \
            f"{outcome}: known={known_chances}, generated={gen_chances}"
```

---

## 8. Packaging and Deployment

### 8.1 Requirements

```
# requirements.txt
flask>=2.0
pybaseball>=2.2
requests>=2.28
beautifulsoup4>=4.11
weasyprint>=57.0
pytest>=7.0
```

### 8.2 Windows Launcher

```batch
@echo off
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed. Please install from https://www.python.org/
    pause
    exit /b 1
)

python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

start /b python app.py
timeout /t 3 /nobreak >nul
start http://localhost:5000

echo Strat-O-Matic Card Maker is running.
echo Close this window to stop the server.
pause
```

### 8.3 Mac Launcher

```bash
#!/bin/bash
cd "$(dirname "$0")"

if ! command -v python3 &> /dev/null; then
    echo "Python 3 is not installed."
    exit 1
fi

python3 -c "import flask" 2>/dev/null || pip3 install -r requirements.txt

python3 app.py &
sleep 3
open http://localhost:5000

echo "Press Ctrl+C to stop."
wait
```

---

## 9. Reference Links and Resources

### 9.1 Strat-O-Matic Official
- Official site: https://www.strat-o-matic.com/
- Online game help (hitter cards): https://365.strat-o-matic.com/help/hittercard
- Online game help (pitcher cards): https://365.strat-o-matic.com/help/pitchercard

### 9.2 Community Formula Resources
- Bruce Bundy Formulas: https://www.somworld.com/2003/bundy1.htm
- Bundy on card chances: https://www.tapatalk.com/groups/stratomaticbaseballvillage/determining-card-chances-on-a-batter-in-strat-o-ma-t1703413.html
- Sabermetric analysis: https://fourpitchrandomwalk.wordpress.com/2015/03/31/sabermetrically-gaming-strat-o-matic-baseball/

### 9.3 Baseball Reference
- Main site: https://www.baseball-reference.com/
- League stats: https://www.baseball-reference.com/leagues/

### 9.4 Rules Reference
- Full rules: https://www.baseballthinkfactory.org/btf/pages/basesim/somrules.htm
- Rulebook PDF: https://tesera.ru/images/items/1513588/SOM-BaseballRulebook.pdf

---

## 10. Open Questions and Decisions

These require decisions before or during implementation.

### 10.1 Minimum Plate Appearances

**Question:** What is the minimum PA to generate a meaningful card?

**Options:**
- 50 PA: Very loose, allows September call-ups
- 100 PA: Allows part-time players
- 150 PA: More statistically stable
- 200 PA: Conservative, roughly 1/3 season

**Trade-off:** Lower threshold = more players available but less reliable cards.

**Recommendation:** 150 PA default, with option to override with warning.

### 10.2 Minimum Supported Year

**Question:** How far back should this support?

**Options:**
- 1871: All of baseball history (significant data gaps)
- 1901: "Modern" era (still missing many stats)
- 1920: Post-dead-ball era
- 1955: Full IBB tracking begins

**Trade-off:** Earlier = more players but worse data quality.

**Recommendation:** 1955 default, with option to go earlier with prominent warnings.

### 10.3 Formula Validation Approach

**Question:** How do we know if the formulas are correct?

**Options:**
1. Validate against known SOM cards (requires access to official cards)
2. Simulation-only validation (check if output stats match input stats)
3. Accept approximation, document limitations

**Recommendation:** Primarily option 2. If you have access to official cards, use option 1 as well.

### 10.4 Handling Formula Edge Cases

**Question:** What if formulas produce impossible results (negative values, >108 total chances)?

**Options:**
1. Clamp values and warn user
2. Error out, refuse to generate card
3. Apply smoothing/normalization

**Recommendation:** Option 1 — clamp and warn. User can decide if card is usable.

### 10.5 Two-Way Players (Ohtani, Ruth)

**Question:** How to handle players with significant stats as both batter and pitcher?

**Recommendation:** This spec covers batter cards only. Generate batter card from batting stats. Pitcher cards are out of scope.

---

## Appendix A: Confidence Summary

| Section | Confidence | Notes |
|---------|------------|-------|
| Dice mechanics (4.1-4.3) | HIGH | Well-documented game rules |
| Card structure (4.4-4.5) | HIGH | Well-documented |
| Batter-pitcher interaction (4.6) | HIGH | Core SOM design principle |
| Bundy formulas (5.2-5.5) | MEDIUM | Community reverse-engineering, not official |
| Era-dependent parameters (5.3-5.4) | HIGH | The approach is correct; specific values need research |
| Average pitcher card (5.6) | LOW | Uncertain how to correctly generate |
| Card layout algorithm (5.8) | MEDIUM | Principles correct, implementation needs work |
| Ratings (5.9) | LOW | Thresholds are guesses |
| Simulation validation (7.3) | HIGH | This is the right way to validate |

---

## Appendix B: Implementation Order Recommendation

1. **Scraper + caching** — Get reliable data first
2. **League averages data** — Populate for all supported years
3. **Basic formula implementation** — Start with walks, strikeouts
4. **Simulation harness** — Build this early to validate formulas
5. **Iterate on formulas** — Adjust until simulation matches reality
6. **Card layout** — Once chances are right, place them on card
7. **Rendering** — HTML output
8. **UI polish** — Disambiguation, warnings, PDF
9. **Launchers** — Desktop shortcuts

**Key insight:** Don't finalize formulas until simulation validates them. The simulation harness is not a "nice to have"—it's the primary tool for getting formulas right.
