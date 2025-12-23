# Strat-O-Matic Card Generator - Troubleshooting Guide

## Common Issues and Solutions

### Issue: "Cannot import name 'player_stats_bref'" or Similar

**Problem:** The scraper was using a non-existent pybaseball function.

**Solution:** This has been fixed in the latest version. Update your code by pulling the latest changes.

### Issue: "Received response with content-encoding: br" (Brotli Error)

**Problem:** pybaseball has issues with brotli-compressed responses.

**Solution:**
1. Install brotli support:
   ```bash
   pip install brotlipy
   ```

2. Or clear pybaseball cache and retry:
   ```bash
   python3 -c "import pybaseball; pybaseball.cache.purge()"
   ```

### Issue: "File is not a zip file" (Lahman Database)

**Problem:** The Lahman database download is corrupted.

**Solution:** Clear the pybaseball cache and re-download:
```bash
python3 << 'EOF'
import pybaseball as pyb
import shutil
from pathlib import Path

# Clear cache
cache_dir = Path.home() / '.pybaseball'
if cache_dir.exists():
    print(f"Removing cache directory: {cache_dir}")
    shutil.rmtree(cache_dir)

# Re-download Lahman database
print("Downloading fresh Lahman database...")
pyb.download_lahman()
print("✓ Done!")
EOF
```

### Issue: Baseball Reference Returns 503 or Blocks Requests

**Problem:** Baseball Reference is rate-limiting or blocking automated requests.

**Solution:**
1. Wait 5-10 minutes before trying again
2. The app now uses the offline Lahman database first, which should work for most historical players
3. For very recent players (current season), you may need to wait for rate limits to clear

### Issue: "Year must be 2008 or later" with batting_stats_bref

**Problem:** Some pybaseball functions only work for recent years.

**Solution:** The app now tries multiple data sources:
1. Lahman database (works for all historical years)
2. Baseball Reference scraping (works when not rate-limited)
3. batting_stats_bref (2008+ only)

For historical players (before 2008), make sure the Lahman database is working (see above).

### Issue: Player Not Found

**Possible causes:**
1. Player name spelled incorrectly
2. Player didn't play in that year
3. Player is too recent for Lahman database (< 1 year old)

**Solution:**
- Try last name only
- Check Baseball Reference for the correct spelling
- Verify the year
- For current-season players, wait for Lahman database update

### Complete Reset

If all else fails, completely reset pybaseball:

```bash
python3 << 'EOF'
import shutil
from pathlib import Path

# Remove pybaseball cache
cache_dir = Path.home() / '.pybaseball'
if cache_dir.exists():
    shutil.rmtree(cache_dir)
    print("✓ Removed pybaseball cache")

# Remove local data cache
data_cache = Path('data/cache')
if data_cache.exists():
    shutil.rmtree(data_cache)
    data_cache.mkdir(parents=True)
    print("✓ Cleared local cache")

print("\nNow restart the app and try again.")
EOF
```

## Data Sources (in order of preference)

1. **Lahman Database** (offline, most reliable)
   - Covers 1871-2024
   - Downloaded once, used offline
   - Best for historical players

2. **Baseball Reference Scraping** (online, can be rate-limited)
   - Covers all years
   - May be blocked temporarily
   - Backup method

3. **batting_stats_bref** (online, 2008+ only)
   - Most recent years only
   - Last resort for modern players

## Verifying Your Setup

Test that data sources are working:

```bash
python3 << 'EOF'
import pybaseball as pyb

print("Testing pybaseball...")

# Test Lahman
try:
    batting = pyb.batting()
    print(f"✓ Lahman database: {len(batting)} records")
except Exception as e:
    print(f"✗ Lahman database failed: {e}")

# Test player lookup
try:
    players = pyb.playerid_lookup('trout', 'mike')
    print(f"✓ Player lookup: found {len(players)} matches")
except Exception as e:
    print(f"✗ Player lookup failed: {e}")

print("\nIf both tests pass, the app should work!")
EOF
```

## Still Having Issues?

1. Check that you're using Python 3.10+
2. Reinstall dependencies: `pip install -r requirements.txt --upgrade`
3. Try with a well-known player from a historical year (e.g., "Babe Ruth", 1927)
4. Check the console output for specific error messages

For more help, open an issue on GitHub with:
- The player name and year you're trying
- The complete error message
- Your Python version (`python3 --version`)
- Your pybaseball version (`pip show pybaseball`)
