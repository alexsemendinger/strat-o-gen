# Windows Setup Guide

This guide is for whoever does the **one-time setup**. After that, daily use
is just double-clicking one file.

## One-Time Setup

### Step 1: Install Python

1. Go to https://www.python.org/downloads/
2. Click the big yellow "Download Python" button (3.10 or later)
3. Run the installer
4. **IMPORTANT:** check the box **"Add Python to PATH"** at the bottom of the
   first screen
5. Click "Install Now" and wait for it to finish

### Step 2: Start the app

Double-click **`Start Strat-O-Gen.vbs`**.

The first launch installs Flask automatically (the app's only dependency —
it's a small, pure-Python package, so there is nothing else to build or
download). Then the app opens in your browser.

That's the whole setup. No internet connection is needed after Flask is
installed: every player season from 1871 to 2025 is bundled with the app.

### Step 3: Make a test card

Try "Babe Ruth", year 1927. If a card appears, you're done.

---

## Daily Use

Double-click **`Start Strat-O-Gen.vbs`**. The browser opens by itself.

To stop: close the minimized black command window.

If the browser doesn't open on its own, open one and go to:
**http://localhost:5001**

---

## Troubleshooting

### "Python is not installed or not in PATH"
Reinstall Python and make sure to check **"Add Python to PATH"**, then
restart the computer.

### Browser doesn't open
Open a browser yourself and go to http://localhost:5001 — the server may
just need a few seconds.

### "No module named flask"
Open Command Prompt in the app folder and run:
```
pip install flask
```

### Port already in use
Another program is using port 5001. Restart the computer, or edit the last
line of `app.py` to change the port.

---

## Updating to a new season

Player data lives in `data/lahman/*.csv.gz` (the Lahman database). When a
new season's database is released (every January at
https://sabr.org/lahman-database/), download the CSV version and replace
the five `.csv.gz` files. Everything else updates automatically.

---

## Quick Reference Card

```
┌─────────────────────────────────────────┐
│  STRAT-O-MATIC CARD MAKER               │
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
