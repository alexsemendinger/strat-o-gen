# Windows Setup Guide

This guide is for whoever does the **one-time setup**. After that, daily use
is just double-clicking one file.

## One-Time Setup

### Step 0: Get the app folder

If you downloaded a ZIP file: right-click it, choose **Extract All...**, and
open the extracted folder. (Starting the app from inside the ZIP window
doesn't work.)

### Step 1: Install Python (3.9 or newer)

1. Go to https://www.python.org/downloads/ and click the big yellow
   "Download Python" button.
2. Run what you downloaded.
   - If it's the **Python install manager** (the newer download), just
     follow its prompts; it sets up the `py` command the app uses.
   - If it's the classic **installer**, tick **"Add python.exe to PATH"** at
     the bottom of the first screen, then click "Install Now".
3. Wait for it to finish.

### Step 2: Start the app

Double-click **`Start Strat-O-Gen.vbs`** (Windows may show it as
"Start Strat-O-Gen"). If Windows asks whether to run it, choose Run / Open.

The first launch opens a black window that installs Flask (the app's only
dependency - a small, pure-Python package). After that the app opens in
your browser by itself.

No internet connection is needed after Flask is installed: every player
season from 1871 to 2025 is bundled with the app.

### Step 3: Make a test card

Start typing "Babe Ruth", pick him from the list, type the year 1927, and
press Enter. If a card appears, you're done.

---

## Daily Use

Double-click **`Start Strat-O-Gen.vbs`**. The browser opens by itself once
the app is ready. The app runs in a **minimized black window on the
taskbar** - leave it there while you use the app.

To stop: click that window on the taskbar and close it (or right-click its
taskbar button and choose "Close window").

Double-clicking again while the app is running just opens the browser again.

If the browser doesn't open on its own, open one and go to
**http://localhost:5001** (the black window shows the exact address).

To print cards at their real size, keep the print scale at 100% ("Actual
size", not "Fit to page").

---

## Troubleshooting

To see what's going on, double-click **`start_windows.bat`** instead of the
.vbs file: it shows the window with any messages.

### "Python was not found"
Install Python (Step 1). With the classic installer, make sure **"Add
python.exe to PATH"** is ticked. Then restart the computer and try again.

### "This Python is too old"
Install a current Python from https://www.python.org/downloads/.

### "Flask isn't installed for this Python interpreter"
The message shows the exact command to install it for the Python that runs
the app; copy that line into Command Prompt and press Enter. Or open
Command Prompt in the app folder and run:
```
py -3 -m pip install flask
```

### Browser doesn't open
Open a browser yourself and go to http://localhost:5001 - or, if the black
window shows a different address (another program was using 5001), that one.

### Port already in use
The app is probably already running: just open http://localhost:5001. If
another program uses port 5001, the app picks the next free port by itself
and prints the address in its window.

---

## Updating to a new season

Player data lives in `data/lahman/` (the Lahman database). When a new
season's database is released (every January at
https://sabr.org/lahman-database/), download the CSV version and replace
the matching files - `Batting`, `Pitching`, `People`, `Teams` and
`Fielding` - keeping the `.csv.gz` names (compress each `.csv` with gzip;
see the README's *Updating for a new season*). `FieldingOFsplit` isn't in
the CSV release; without an updated copy the new season's outfielders get
generic "outfield" ratings instead of LF/CF/RF. The app's latest year
updates by itself from the data.

---

## Quick Reference Card

```
+-----------------------------------------+
|  STRAT-O-MATIC CARD MAKER               |
|                                         |
|  To START:                              |
|    Double-click "Start Strat-O-Gen"     |
|                                         |
|  To STOP:                               |
|    Close the black window on the        |
|    taskbar                              |
|                                         |
|  If the browser doesn't open:           |
|    Go to http://localhost:5001          |
+-----------------------------------------+
```
