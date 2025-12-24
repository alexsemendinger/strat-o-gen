# Stats Fetcher - Coverage and Constraints

## What We Can Fetch

### Batting Stats (Complete)
All stats needed for Bundy batter formulas:
- ✓ Core: G, AB, PA, H, 2B, 3B, HR, R, RBI
- ✓ Walks/Ks: BB, IBB, SO
- ✓ Other: HBP, SH, SF, SB, CS, GDP
- ✓ Rates: BA, OBP, SLG
- ✓ Metadata: Team, League

### Pitching Stats (Mostly Complete)
Most stats needed for Bundy pitcher formulas:
- ✓ Core: W, L, G, GS, CG, SHO, SV
- ✓ Innings: IP, TBF (batters faced)
- ✓ Outcomes: H, R, ER, HR, BB, IBB, SO, HBP
- ✓ Rates: ERA, WHIP, H9, HR9, BB9, SO9
- ✓ Calculated: OppBA (opponent batting average)
- ✓ Other: WP, BK
- ✗ **MISSING**: 2B allowed, 3B allowed

**Why 2B/3B are missing:**
Baseball Reference's standard pitching table doesn't include doubles and triples allowed. These would need to be fetched from:
- Play-by-play data (not in standard tables)
- Advanced splits pages (different URL/parsing)
- Estimated from league averages

**Impact on formulas:**
- Formula #18 (doubles) and #19 (triples) need these stats
- However, the formulas subtract large constants (90 for 2B, 15 for 3B)
- For many pitchers, these might result in 0 or negative chances anyway
- Can potentially estimate or use league averages as fallback

## Year Constraints

### Batting
- **IBB**: Not tracked before 1955 (will be 0)
- **SF**: Not tracked before 1954 (will be 0)
- **CS**: Spotty before 1951 (may be 0)
- **Full coverage**: 1955+ recommended

### Pitching
- **IBB**: Not tracked before 1955 (will be 0)
- **TBF**: Generally available, but sometimes missing in very old years
- **Full coverage**: 1955+ recommended (same as batting)

## Usage

```python
from stats_fetcher import StatsFetcher

fetcher = StatsFetcher()

# Get batting stats
batter = fetcher.get_stats('ruthba01', 1927, 'batting')

# Get pitching stats
pitcher = fetcher.get_stats('koufasa01', 1965, 'pitching')

# Or use specific methods
batter = fetcher.get_batting_stats('ruthba01', 1927)
pitcher = fetcher.get_pitching_stats('koufasa01', 1965)
```

## Input Requirements

- **bbref_id**: Baseball Reference player ID (e.g., 'ruthba01', 'koufasa01')
  - Format: usually last name + first initial + sequential number
  - Must be looked up manually from Baseball Reference for now
- **year**: Season year (e.g., 1927, 1965)
- **stat_type**: 'batting' or 'pitching'

## Future Enhancements

1. **Player search**: Convert "Babe Ruth" → 'ruthba01'
2. **Multi-team seasons**: Handle trades (currently takes first row only)
3. **2B/3B for pitchers**: Fetch from advanced stats or estimate
4. **Caching**: Store fetched data locally to avoid repeated requests
5. **Rate limiting**: Add delays between requests to be nice to BBRef
6. **League averages**: Fetch era-specific league stats for formulas
