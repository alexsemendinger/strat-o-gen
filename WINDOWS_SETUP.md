# Windows Setup Guide for Strat-O-Matic Card Generator

This guide is for the person doing the **initial setup** (you, not your dad).

## One-Time Setup (Do This First)

### Step 1: Install Python

1. Go to https://www.python.org/downloads/
2. Download Python 3.10 or later (click the big yellow "Download Python" button)
3. Run the installer
4. **IMPORTANT:** Check the box that says **"Add Python to PATH"** at the bottom of the first screen
5. Click "Install Now"
6. Wait for installation to complete, then close the installer

### Step 2: Verify Python Installation

1. Open Command Prompt (press Windows key, type `cmd`, press Enter)
2. Type `python --version` and press Enter
3. You should see something like `Python 3.12.0`
4. If you see an error, restart your computer and try again

### Step 3: Install the App Dependencies

1. Open Command Prompt
2. Navigate to the app folder. For example, if the folder is on the Desktop:
   ```
   cd Desktop\strat-o-gen
   ```
3. Run this command:
   ```
   pip install -r requirements.txt
   ```
4. Wait for all packages to download and install (this may take a few minutes)
5. You should see "Successfully installed..." messages

### Step 4: Test It Works

1. Double-click `Start Strat-O-Gen.vbs`
2. A browser window should open to the app
3. Try generating a card for "Babe Ruth" in 1927
4. If it works, setup is complete!

---

## For Daily Use (What Dad Does)

Just double-click **`Start Strat-O-Gen.vbs`**

That's it! The app will:
1. Start the server (minimized window)
2. Open the browser automatically
3. Be ready to generate cards

To stop the app, close the minimized command prompt window.

---

## Updating the App

When you send an update:

1. Download the new ZIP file
2. Extract it to the **same location** as before (overwrite existing files)
3. The `data/` folder with cached player data will be preserved
4. That's it - the app is updated!

**Tip:** The `data/` folder contains cached player statistics. If you want a fresh start, you can delete this folder, but cards will take longer to generate the first time as data is re-fetched.

---

## Troubleshooting

### "Python is not installed or not in PATH"
- Python wasn't installed correctly
- Uninstall Python, reinstall, and make sure to check "Add Python to PATH"
- Restart the computer after reinstalling

### Browser doesn't open
- Manually open a browser and go to: http://localhost:5001
- The server might take a few seconds to start

### "No module named flask" or similar errors
- The dependencies weren't installed
- Open Command Prompt, navigate to the folder, and run:
  ```
  pip install -r requirements.txt
  ```

### Port already in use
- Another program is using port 5001
- Close other programs or restart the computer
- Or edit `start_windows.bat` to change the PORT value

### App crashes or shows errors
- Try deleting the `data/cache` folder and regenerating cards
- Make sure you have an internet connection (needed to fetch player stats)

---

## File Reference

| File | Purpose |
|------|---------|
| `Start Strat-O-Gen.vbs` | **Double-click this to start the app** |
| `start_windows.bat` | The actual launcher (called by the VBS file) |
| `app.py` | The main application |
| `requirements.txt` | List of Python packages needed |
| `data/` | Cached player data (preserved during updates) |

---

## Quick Reference Card

Print this out and leave it next to the computer:

```
┌─────────────────────────────────────────┐
│  STRAT-O-MATIC CARD GENERATOR           │
│                                         │
│  To START:                              │
│    Double-click "Start Strat-O-Gen"     │
│                                         │
│  To STOP:                               │
│    Close the black command window       │
│                                         │
│  If browser doesn't open:               │
│    Go to http://localhost:5001          │
└─────────────────────────────────────────┘
```
