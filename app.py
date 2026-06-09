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
body { font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif; margin:0;
  background:linear-gradient(135deg,#667eea 0%,#764ba2 100%); min-height:100vh; }
.container { max-width:760px; margin:0 auto; padding:30px 16px; }
.panel { background:white; border-radius:10px; padding:24px;
  box-shadow:0 8px 24px rgba(0,0,0,0.25); margin-bottom:20px; }
h1 { margin:0 0 4px; color:#333; }
.subtitle { color:#666; margin:0 0 20px; }
label { display:block; font-weight:bold; color:#333; margin:12px 0 4px; }
input[type=text], input[type=number] { width:100%; box-sizing:border-box;
  padding:10px; font-size:16px; border:2px solid #ddd; border-radius:6px; }
input:focus { outline:none; border-color:#667eea; }
.row { display:flex; gap:12px; }
.row > div { flex:1; }
button { background:linear-gradient(135deg,#667eea 0%,#764ba2 100%); color:white;
  font-size:16px; font-weight:bold; border:none; border-radius:6px;
  padding:12px 22px; cursor:pointer; margin-top:14px; }
button:disabled { background:#ccc; cursor:default; }
button.secondary { background:#e8e8f4; color:#333; }
.error { background:#fee; color:#c33; border-radius:6px; padding:10px 14px;
  margin-top:12px; display:none; }
.warnings { background:#fff8e1; color:#7a5d00; border-radius:6px;
  padding:10px 14px; margin:12px 0; font-size:14px; }
.warnings ul { margin:4px 0 0 18px; padding:0; }
.candidates { margin-top:10px; }
.candidate { border:2px solid #ddd; border-radius:6px; padding:10px 12px;
  margin-bottom:8px; cursor:pointer; }
.candidate:hover, .candidate.active { border-color:#667eea; background:#f0f4ff; }
.candidate .meta { color:#666; font-size:13px; }
.kind-toggle { margin-top:10px; }
.kind-toggle label { display:inline; font-weight:normal; margin-right:16px; }
.accuracy { width:100%; border-collapse:collapse; font-size:14px; margin-top:8px; }
.accuracy th, .accuracy td { border:1px solid #ccc; padding:5px 10px;
  text-align:center; }
.accuracy th { background:#f0f0f8; }
h3 { color:#333; margin:18px 0 4px; }
.note { color:#666; font-size:13px; }
#spinner { display:none; color:#666; margin-top:10px; }
__CARD_CSS__
</style>
</head>
<body>
<div class="container">
  <div class="panel">
    <h1>Strat-O-Matic Card Maker</h1>
    <p class="subtitle">Make a game-usable card for any player, 1871&ndash;2025</p>
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
