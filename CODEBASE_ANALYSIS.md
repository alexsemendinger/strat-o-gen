# Strat-O-Matic Card Generator - Codebase Analysis

## What This Program Actually Does

This is an end-to-end Strat-O-Matic baseball card generator that:

1. **Takes a player name and year as input** (via web UI or CLI)
2. **Fetches real statistics** from Baseball Reference
3. **Applies "Bundy formulas"** to convert stats to card chances
4. **Generates a 3x11 card grid** with dice roll results
5. **Renders an HTML/PDF card** with ratings and outcome distribution

### End-to-End Flow

```
User Input (name, year) -> Search Player -> Fetch Stats -> Get League Averages
    -> Calculate Chances (Bundy formulas) -> Create Card Grid -> Render HTML/PDF
```

**This flow is complete and functional.** You can enter "Mike Trout" and "2019" and receive a generated card.

---

## Critical Issues Found

### 1. TWO PARALLEL DATA FETCHING SYSTEMS (Confusing/Redundant)

**Files involved:**
- `scraper.py` - Uses `pybaseball` library (used by web app)
- `stats_fetcher.py` - Direct Baseball Reference scraping (used by CLI)

**Problem:** The web app (`app.py`) uses `scraper.py`, but the CLI tool (`generate_card.py`) uses `stats_fetcher.py`. These return slightly different data structures.

**Impact:** CLI and web may produce different results for the same player. This is confusing and violates DRY.

**Location:** `generate_card.py:22-23` imports `StatsFetcher`, while `app.py:9` imports `PlayerScraper`

---

### 2. TWO PARALLEL CARD GENERATION ENGINES (Confusing/Redundant)

**Files involved:**
- `card_engine.py` - Used by web app
- `card_formulas.py` + `card_layout.py` - Used by CLI tool

**Problem:** The web app uses `CardEngine.calculate_chances()` and `CardEngine.create_card_grid()`, while the CLI uses `BatterCardFormulas.calculate_batter_card_chances()` and `CardLayoutGenerator.generate_layout()`.

**These are DIFFERENT IMPLEMENTATIONS of the same formulas!**

Example differences:
- `card_engine.py:110-111` calculates singles using: `league_1b_rate = league_avg.get('BA', 0.250) - league_2b_rate - league_3b_rate - league_hr_rate`
- `card_formulas.py:258-260` uses: `league_hits_per_pa = league_ba * 0.85` then subtracts XBH rates

**Impact:** Same player will get different cards from CLI vs web.

---

### 3. HARDCODED DEFAULT VALUES WHERE REAL DATA SHOULD BE USED

**Location:** `card_formulas.py:280-289` and `scraper.py:413-423`

```python
# Default league averages (hardcoded fallback)
league_avg = {
    'BA': 0.250,
    'HR_per_PA': 0.025,
    'BB_per_PA': 0.085,
    'K_per_PA': 0.200,
    '2B_per_PA': 0.040,
    '3B_per_PA': 0.005,
}
```

**Problem:** If league average fetching fails (network issue, cache miss), the system silently falls back to these hardcoded values without warning. These defaults are roughly "average modern MLB" but:
- 1920s had ~3.5% K/PA, not 20%
- Deadball era (1901-1919) had very different rates
- Steroid era had different HR rates

**Impact:** Cards for historical players may be significantly wrong if league data fetch fails, and user won't know.

---

### 4. RATINGS ARE PLACEHOLDERS (Not Calculated)

**Location:** `card_engine.py:315-319`

```python
# BUNTING (placeholder - would need more sophisticated analysis)
ratings['bunt'] = 'B'  # Default

# HIT AND RUN (placeholder)
ratings['hit_and_run'] = 'B'  # Default
```

**Problem:** Bunt and Hit & Run ratings are always 'B' regardless of player. Real SOM cards calculate these based on:
- Speed
- Contact rate
- Batting eye
- Historical sacrifice bunt data

**Impact:** Every card shows "Bunt: B, Hit & Run: B" which is incorrect.

---

### 5. PITCHER CARDS NOT INTEGRATED (Incomplete Feature)

**Files:** `card_formulas.py` has `PitcherCardFormulas` class, but:
- `card_engine.py` has no pitcher support
- `app.py` only generates batter cards
- `generate_card.py:117-118` always calls `generate_batter_card()`

**Location:** `generate_card.py:117-118`
```python
# Try batter first, then pitcher
generate_batter_card(bbref_id, year)
# generate_pitcher_card is defined but NEVER CALLED
```

**Impact:** You cannot generate pitcher cards through either interface, despite the formulas being implemented.

---

### 6. RANDOM FIELDING LOCATIONS (Non-Deterministic Cards)

**Location:** `fielding_locations.py:82-102`

```python
def assign_out_type() -> str:
    rand = random.random()  # RANDOM!
    ...
```

**Problem:** Every time you generate a card, the fielding locations (gb(ss)A, flyball(cf)B, etc.) are randomly assigned. Running the generator twice for the same player/year produces different cards.

**Impact:** Cards are not reproducible. This is especially problematic for testing.

---

### 7. RANDOM BASERUNNING MODIFIERS (Non-Deterministic)

**Location:** `card_layout.py:240-275`

```python
import random
...
for result in random.sample(single_results, ...):
    result.outcome = 'single**'
```

**Problem:** The `*` and `**` modifiers on singles/doubles are randomly assigned from a pool, not deterministically calculated.

**Impact:** Same player card has different baserunning symbols each generation.

---

### 8. CARD GRID LAYOUT IGNORES D20 SPLITS (Oversimplified)

**Location:** `card_engine.py:241-243`

```python
# For simplicity in basic version, just assign the first available result
# In reality, we'd assign multiple results per position based on weight
grid[col][dice_sum] = self._format_result(results_list[result_idx])
```

**Problem:** The comment says "for simplicity" - real SOM cards use d20 splits like "HR 1-12, 2B 13-20" to handle fractional chances. This implementation just picks one result per dice position.

The `card_layout.py` DOES support d20 splits properly, but `card_engine.py` doesn't use it.

**Impact:** Cards lose granularity. A player with 2.5 HR chances might show 2 or 3, not the correct 2.5.

---

### 9. SECRET KEY HARDCODED (Security Issue)

**Location:** `app.py:14`

```python
app.secret_key = 'strat-o-matic-card-generator-secret-key'
```

**Problem:** Hardcoded, publicly visible secret key.

**Impact:** Low (no sensitive data), but bad practice.

---

### 10. MISSING PA CALCULATION INCONSISTENCY

**Location:** `scraper.py:300-307` vs `card_formulas.py:36-44`

`scraper.py`:
```python
def _calculate_pa(self, stats: Dict) -> int:
    pa = stats['AB'] + stats['BB'] + stats['HBP']
    if stats.get('SF') is not None:
        pa += stats['SF']
    if stats.get('SH') is not None:
        pa += stats['SH']
    return pa
```

`card_formulas.py`:
```python
def calculate_pa_effective(stats: Dict) -> int:
    ab = stats.get('AB', 0)
    bb = stats.get('BB', 0)
    ibb = stats.get('IBB', 0)
    hbp = stats.get('HBP', 0)
    sf = stats.get('SF', 0)
    # PA_eff = AB + (BB - IBB) + HBP + SF
    return ab + (bb - ibb) + hbp + sf
```

**Problem:** Different formulas for PA calculation. One includes SH (sacrifice hits), one doesn't. One subtracts IBB, one doesn't.

---

### 11. VALIDATION SYSTEM NOT INTEGRATED

**File:** `card_validator.py` exists but is not called anywhere in the main flow.

**Location:** The class `CardSimulator` is defined but never instantiated in `app.py` or `generate_card.py`.

**Problem:** There's a card validation/simulation system that could verify card accuracy, but it's never used.

---

### 12. CACHE FILES NEVER EXPIRE

**Location:** `scraper.py:330-339`

```python
def _get_from_cache(self, key: str) -> Optional[Dict]:
    cache_file = self.cache_dir / f"{key}.json"
    if cache_file.exists():
        # No timestamp check!
        return json.load(f)
```

**Problem:** Once stats are cached, they're used forever. If Baseball Reference updates data (corrections, etc.), the cache won't reflect it.

---

### 13. YEAR DISPLAYED DIFFERENTLY IN OUTPUT

**Problem:** `real_som_cards.py:29-44` shows Tim Raines data marked as 2001, but the stats don't match 2001 Tim Raines. He had:
- 2001: 47 games, .308 BA, 0 HR (was 41 years old)
- The stats listed (172 H, 12 HR, .312 BA) look more like 1987 Tim Raines

**Impact:** Test data appears to be mislabeled.

---

## Summary of Issues by Severity

### Critical (Affects Output Correctness)
1. Two parallel data fetching systems producing different results
2. Two parallel card generation engines with different formulas
3. Hardcoded fallback values silently used when data fetch fails
4. Card layout ignores d20 splits for fractional chances

### Major (Missing/Incomplete Features)
5. Pitcher cards are not accessible through any interface
6. Bunt/Hit-and-Run ratings are always hardcoded 'B'
7. Validation system exists but is never used

### Moderate (Quality/Reproducibility Issues)
8. Random fielding locations make cards non-reproducible
9. Random baserunning modifiers make cards non-reproducible
10. PA calculation inconsistency between modules
11. Cache never expires

### Minor (Best Practice Violations)
12. Hardcoded Flask secret key
13. Test data appears mislabeled

---

## What Works Well

1. **Stats fetching is robust** - multiple fallback methods, good error handling
2. **League averages are properly cached** - separate cache per year/league
3. **Web UI is clean and functional** - player disambiguation works well
4. **Bundy formulas are well-documented** - comments explain the math
5. **Era-appropriate warnings** - correctly flags missing IBB/SF for historical data
6. **Confidence indicators** - tells users when card may be unreliable

---

## Recommendations

1. **Consolidate to one data fetching module** - pick `scraper.py` or `stats_fetcher.py`
2. **Consolidate to one card generation engine** - `card_layout.py` is more complete
3. **Add visible warnings** when fallback league averages are used
4. **Calculate bunt/hit-run ratings** or mark them as "N/A"
5. **Integrate pitcher card generation** into the web and CLI interfaces
6. **Seed random number generator** with player+year for reproducibility
7. **Add cache expiration** (e.g., 30 days for current year data)
8. **Integrate the validator** as an optional verification step
