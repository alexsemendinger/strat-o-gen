"""Strat-O-Matic Card Maker — local web app.

Run:  python app.py   then open http://localhost:5001

Everything is offline: player statistics and league averages come from the
bundled Lahman database (1871-2025). The only dependency is Flask.
"""

from __future__ import annotations

from flask import Flask, jsonify, request

from stratogen.generate import (
    average_batter_chances, average_pitcher_chances,
    generate_batter_card, generate_pitcher_card,
)
from stratogen.lahman import default_db
from stratogen.render import CARD_CSS, accuracy_rows, card_to_html
from stratogen.simulate import effective_pa

app = Flask(__name__)
MIN_PA = 50          # below this, refuse (a card would be meaningless)
WARN_PA = 150        # below this, generate but warn

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strat-O-Matic Card Maker</title>
<style>
:root {
  --navy:#1e2d4f; --navy-dark:#16223d; --brick:#9e3a2f; --ink:#2c2a25;
  --paper:#faf6ea; --paper-dark:#f1ead7; --field:#fffdf6;
  --rule:#d6cab0; --rule-dark:#b9ab8c; --muted:#7d7259;
}
body { font-family:Georgia,'Iowan Old Style','Times New Roman',serif;
  margin:0; color:var(--ink); min-height:100vh;
  background-color:#ece4d2;
  background-image:repeating-linear-gradient(90deg,
    rgba(30,45,79,0.04) 0, rgba(30,45,79,0.04) 1px, transparent 1px, transparent 28px); }
.container { max-width:760px; margin:0 auto; padding:34px 16px; }
.panel { background:var(--paper); border:1px solid var(--rule-dark);
  border-radius:4px; padding:26px 28px; margin-bottom:22px;
  box-shadow:0 1px 0 #fff inset, 0 3px 10px rgba(44,42,37,0.18);
  outline:1px solid var(--rule); outline-offset:-5px; }
.masthead { text-align:center; margin-bottom:18px; }
h1 { margin:0; color:var(--navy); font-size:30px; font-weight:normal;
  text-transform:uppercase; letter-spacing:.08em; }
h1 .star { color:var(--brick); font-size:.55em; vertical-align:.35em;
  padding:0 .5em; }
.subtitle { color:var(--muted); font-style:italic; margin:6px 0 0;
  font-size:15px; }
.masthead::after { content:""; display:block; width:200px; margin:14px auto 0;
  border-top:1px solid var(--brick); border-bottom:1px solid var(--brick);
  height:3px; }
label { display:block; color:var(--navy); margin:12px 0 5px; font-size:13px;
  text-transform:uppercase; letter-spacing:.08em; }
input[type=text], input[type=number] { width:100%; box-sizing:border-box;
  padding:10px 12px; font-size:17px; font-family:inherit; color:var(--ink);
  background:var(--field); border:1px solid var(--rule-dark); border-radius:3px;
  box-shadow:0 1px 2px rgba(44,42,37,0.08) inset; }
input:focus { outline:none; border-color:var(--navy);
  box-shadow:0 0 0 1px var(--navy); }
.row { display:flex; gap:14px; }
.row > div { flex:1; }
button { background:var(--navy); color:#f5efdf; font-family:inherit;
  font-size:14px; text-transform:uppercase; letter-spacing:.1em;
  border:1px solid var(--navy-dark); border-radius:3px; padding:11px 24px;
  cursor:pointer; margin-top:16px;
  box-shadow:0 1px 0 rgba(255,255,255,0.15) inset, 0 2px 4px rgba(44,42,37,0.25); }
button:hover { background:var(--navy-dark); }
button:disabled { background:#a9a290; border-color:#948d7b; cursor:default; }
button.secondary { background:var(--paper-dark); color:var(--navy);
  border:1px solid var(--rule-dark); box-shadow:none; }
button.secondary:hover { background:#e7dec6; }
.error { background:#f4e2dd; color:#7e2c22; border:1px solid #c79289;
  border-left:4px solid var(--brick); border-radius:3px; padding:10px 14px;
  margin-top:14px; display:none; }
.warnings { background:#f6ecd2; color:#6d5520; border:1px solid #d6c08c;
  border-left:4px solid #b08c3a; border-radius:3px; padding:10px 14px;
  margin:12px 0; font-size:14px; }
.warnings ul { margin:4px 0 0 18px; padding:0; }
.candidates { margin-top:14px; }
.candidate { border:1px solid var(--rule-dark); background:var(--field);
  border-radius:3px; padding:10px 14px; margin-bottom:8px; cursor:pointer; }
.candidate:hover, .candidate.active { border-color:var(--navy);
  background:var(--paper-dark); box-shadow:2px 0 0 var(--brick) inset; }
.candidate b { color:var(--navy); }
.candidate .meta { color:var(--muted); font-size:13px; font-style:italic; }
.kind-toggle { margin-top:12px; }
.kind-toggle label { display:inline; margin-right:18px; font-size:14px;
  text-transform:none; letter-spacing:normal; color:var(--ink); }
.kind-toggle input { accent-color:var(--brick); }
.accuracy { width:100%; border-collapse:collapse; font-size:14px;
  margin-top:8px; background:var(--field); }
.accuracy th, .accuracy td { border:1px solid var(--rule-dark);
  padding:6px 12px; text-align:center; }
.accuracy th { background:var(--navy); color:#f5efdf; font-weight:normal;
  text-transform:uppercase; letter-spacing:.06em; font-size:12px; }
.accuracy tr:nth-child(even) td { background:var(--paper-dark); }
h3 { color:var(--navy); margin:22px 0 4px; font-weight:normal; font-size:16px;
  text-transform:uppercase; letter-spacing:.07em;
  border-bottom:1px solid var(--rule-dark); padding-bottom:4px; }
.note { color:var(--muted); font-size:13px; font-style:italic; }
#spinner { display:none; color:var(--muted); font-style:italic; margin-top:12px; }
.footer { text-align:center; color:var(--muted); font-size:12px;
  font-style:italic; margin:6px 0 24px; }
__CARD_CSS__
</style>
</head>
<body>
<div class="container">
  <div class="panel">
    <div class="masthead">
      <h1>Strat-O-Matic<span class="star">&#9733;</span>Card Maker</h1>
      <p class="subtitle">A game-usable card for any player, 1871&ndash;2025</p>
    </div>
    <div class="row">
      <div>
        <label for="name">Player name</label>
        <input type="text" id="name" placeholder="e.g. Babe Ruth, Nolan Ryan" autofocus>
      </div>
      <div style="max-width:140px">
        <label for="year">Year</label>
        <input type="number" id="year" min="1871" max="2025" placeholder="1927">
      </div>
    </div>
    <div class="kind-toggle" id="kindToggle" style="display:none">
      <label><input type="radio" name="kind" value="batter" checked> Batter card</label>
      <label><input type="radio" name="kind" value="pitcher"> Pitcher card</label>
    </div>
    <button id="searchBtn">Find player</button>
    <div id="spinner">Working&hellip;</div>
    <div class="error" id="error"></div>
    <div class="candidates" id="candidates"></div>
  </div>
  <div id="result"></div>
  <div class="footer">An independent fan project &mdash; not affiliated with
    the Strat-O-Matic Game Company</div>
</div>
<script>
const $ = id => document.getElementById(id);
let chosen = null;

function showError(msg) { const e = $('error'); e.textContent = msg;
  e.style.display = msg ? 'block' : 'none'; }

async function search() {
  showError(''); $('result').innerHTML = ''; $('candidates').innerHTML = '';
  $('kindToggle').style.display = 'none'; chosen = null;
  const name = $('name').value.trim();
  if (!name) { showError('Enter a player name.'); return; }
  $('spinner').style.display = 'block';
  try {
    const r = await fetch('/api/search?name=' + encodeURIComponent(name));
    const data = await r.json();
    if (!r.ok) { showError(data.error); return; }
    if (data.players.length === 0) {
      showError('No player found by that name. Check the spelling (last name alone works too).');
      return;
    }
    if (data.players.length === 1) { pick(data.players[0], null); return; }
    for (const p of data.players) {
      const div = document.createElement('div');
      div.className = 'candidate';
      div.innerHTML = '<b>' + p.name + '</b> <span class="meta">' + p.meta + '</span>';
      div.onclick = () => pick(p, div);
      $('candidates').appendChild(div);
    }
  } finally { $('spinner').style.display = 'none'; }
}

function pick(p, div) {
  chosen = p;
  if (div) {
    for (const el of document.querySelectorAll('.candidate')) el.classList.remove('active');
    div.classList.add('active');
  }
  const kinds = [];
  if (p.can_bat) kinds.push('batter');
  if (p.can_pitch) kinds.push('pitcher');
  if (kinds.length === 2) {
    $('kindToggle').style.display = 'block';
  } else {
    $('kindToggle').style.display = 'none';
    document.querySelector('input[name=kind][value=' + (kinds[0] || 'batter') + ']').checked = true;
  }
  generate();
}

async function generate() {
  if (!chosen) return;
  showError(''); $('result').innerHTML = '';
  const year = parseInt($('year').value, 10);
  if (!year) { showError('Enter a year.'); return; }
  const kind = document.querySelector('input[name=kind]:checked').value;
  $('spinner').style.display = 'block';
  try {
    const r = await fetch('/api/generate', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ player_id: chosen.player_id, year: year, kind: kind })});
    const data = await r.json();
    if (!r.ok) { showError(data.error); return; }
    let htmlOut = '';
    if (data.warnings.length) {
      htmlOut += '<div class="panel"><div class="warnings"><b>Heads up:</b><ul>'
        + data.warnings.map(w => '<li>' + w + '</li>').join('') + '</ul></div></div>';
    }
    htmlOut += '<div class="panel">' + data.card_html
      + '<button onclick="window.print()" class="secondary">Print card</button>'
      + '<h3>How well does this card match the real season?</h3>'
      + '<p class="note">What the card produces over the same plate appearances, versus what actually happened:</p>'
      + '<table class="accuracy"><tr><th></th><th>Actual ' + data.year + '</th><th>This card</th></tr>'
      + data.accuracy.map(r2 => '<tr><td style="text-align:left">' + r2[0] + '</td><td>'
          + r2[1] + '</td><td>' + r2[2] + '</td></tr>').join('')
      + '</table></div>';
    $('result').innerHTML = htmlOut;
  } finally { $('spinner').style.display = 'none'; }
}

$('searchBtn').onclick = search;
$('name').addEventListener('keydown', e => { if (e.key === 'Enter') search(); });
$('year').addEventListener('keydown', e => { if (e.key === 'Enter') search(); });
for (const el of document.querySelectorAll('input[name=kind]'))
  el.addEventListener('change', generate);
</script>
</body>
</html>
""".replace("__CARD_CSS__", CARD_CSS)


@app.route("/")
def index():
    return PAGE


@app.route("/api/search")
def api_search():
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify(error="missing name"), 400
    db = default_db()
    players = []
    for hit in db.search_players(name):
        span = ""
        if hit.first_year:
            span = f"{hit.first_year}–{hit.last_year}"
        kinds = []
        if hit.batting_years:
            kinds.append("batted")
        if len(hit.pitching_years) > 2 or len(hit.pitching_years) > len(hit.batting_years) // 2:
            kinds.append("pitched")
        players.append({
            "player_id": hit.player_id,
            "name": hit.name,
            "meta": f"{span} · bats {hit.bats}/throws {hit.throws}"
                    + (f" · {', '.join(kinds)}" if kinds else ""),
            "can_bat": bool(hit.batting_years),
            "can_pitch": bool(hit.pitching_years),
        })
    return jsonify(players=players)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    payload = request.get_json(silent=True) or {}
    player_id = payload.get("player_id")
    year = payload.get("year")
    kind = payload.get("kind", "batter")
    if not player_id or not isinstance(year, int):
        return jsonify(error="player and year are required"), 400

    db = default_db()
    name = db.player_name(player_id)
    try:
        if kind == "pitcher":
            stats = db.pitching_season(player_id, year)
            if stats is None:
                return jsonify(error=f"{name} has no pitching record in {year}."), 404
            league = db.league_batting(year, stats["league"])
            card, warnings = generate_pitcher_card(stats, league)
            opposing = average_batter_chances(league)
        else:
            stats = db.batting_season(player_id, year)
            if stats is None:
                return jsonify(error=f"{name} has no batting record in {year}."), 404
            pa = effective_pa(stats)
            if pa < MIN_PA:
                return jsonify(error=(
                    f"{name} only had {pa:.0f} plate appearances in {year} — "
                    f"not enough to make a meaningful card (minimum {MIN_PA}). "
                    f"Try another season.")), 400
            league = db.league_batting(year, stats["league"])
            card, warnings = generate_batter_card(
                stats, league, positions=db.positions(player_id, year))
            if pa < WARN_PA:
                warnings.append(
                    f"only {pa:.0f} plate appearances — small samples make "
                    f"streaky cards")
            opposing = average_pitcher_chances(league)
    except (ValueError, KeyError) as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(
        card_html=card_to_html(card),
        warnings=warnings,
        accuracy=accuracy_rows(card, stats, opposing),
        year=year,
        name=name,
    )


if __name__ == "__main__":
    import webbrowser
    import threading

    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5001")).start()
    app.run(host="127.0.0.1", port=5001, debug=False)
