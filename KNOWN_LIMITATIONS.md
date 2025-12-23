# Known Limitations

## Card Format - Simplified Version

**IMPORTANT:** The current card generator produces **simplified Basic game cards** that differ from official Strat-O-Matic cards in several ways:

### What's Missing (Compared to Real SOM Cards)

Looking at an actual SOM card (like the Ted Williams card), official cards have:

1. **Platoon Splits** ❌
   - Real cards: Separate columns for vs LHP (blue) and vs RHP (red)
   - Our cards: Single unified result (Basic game style)

2. **Detailed Out Types** ❌
   - Real cards: `fly (lf) B?`, `gb (2b) C`, `gb (ss) A` (specific fielder positions and ratings)
   - Our cards: Generic `gb(A)`, `fb(X)` outs

3. **Split Dice Results** ❌
   - Real cards: `SI** 1-13` / `gb (1b) B 14-20` (additional dice roll subdivisions)
   - Our cards: Single result per dice roll

4. **Runner Advancement Symbols** ⚠️ Partial
   - Real cards: `*`, `**` for extra base advancement
   - Our cards: Mentioned but not fully implemented

5. **Injury Results** ❌
   - Real cards: `plus injury` annotations on certain results
   - Our cards: No injury tracking

6. **Specific Numbers** ❌
   - Real cards: Secondary numbers like `1-11`, `12-20`, `1-12`, `13-20`
   - Our cards: Simple result per dice sum

### What Works

✅ Basic statistical accuracy (outcome frequencies match player stats)
✅ Proper dice probability distribution (2d6 weighting)
✅ Ratings (Power, Steal, Speed)
✅ Confidence indicators
✅ Era-appropriate adjustments
✅ Basic/Intermediate game level results

### Why These Limitations Exist

The official Strat-O-Matic formulas are proprietary and extremely complex. This generator uses:
- Community-reverse-engineered "Bundy formulas" (approximations)
- Simplified result mapping
- Basic game assumptions

### Future Improvements Needed

To match official SOM cards, we would need to add:

1. **Platoon split calculations** - Different chances vs LHP/RHP
2. **Fielder-specific out distribution** - Based on spray charts and batted ball data
3. **Split result logic** - Additional 20-sided die rolls for certain outcomes
4. **Injury probability tables** - Based on historical player injury data
5. **Advanced baserunning** - More detailed advancement rules
6. **Fielding ratings** - Requires defensive statistics

### For Now: Basic Game Cards

The current generator produces **usable Basic game cards** that:
- Reflect player's statistical performance
- Can be used in actual Strat-O-Matic gameplay
- Are statistically validated through simulation
- Just lack the detail and platoon splits of official Advanced game cards

### Adding More Manual Data

To bypass API issues, you can add players to `manual_data.py`:

```python
MANUAL_PLAYERS = {
    'playerid_year': {
        'player_id': 'playerid',
        'player_name': 'Player Name',
        'year': 2003,
        'team': 'NYY',
        'league': 'AL',
        'G': 162,
        'AB': 500,
        'PA': 600,
        'H': 150,
        # ... etc
    }
}
```

Then the card will generate instantly without hitting any APIs.

## Current Status

- ✅ Derek Jeter 2003 works (via manual data)
- ✅ Card generation engine functional
- ✅ Basic game level accuracy
- ⚠️ Advanced game features not implemented
- ⚠️ API data sources often rate-limited (use manual data fallback)

## Recommendation

For now, use this generator to create **Basic game cards** for players. The cards will be statistically accurate but won't have all the detail of official Advanced game cards with platoon splits and fielder-specific outs.

To get closer to official cards, we'd need to:
1. Implement platoon split calculations (vs LHP/RHP)
2. Add batted ball data (ground ball %, fly ball %, line drive %)
3. Implement fielder-position-specific out distribution
4. Add split dice roll logic
5. Include injury probabilities

This is a significant undertaking that goes beyond the current scope.
