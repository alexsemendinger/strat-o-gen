"""Flask web application for Strat-O-Matic Card Generator.

Uses the same stats fetching and card generation as the CLI.
"""

import os
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify

from stats_fetcher import StatsFetcher
from card_formulas import BatterCardFormulas, PitcherCardFormulas
from league_averages import LeagueAveragesFetcher
from card_layout import CardLayoutGenerator

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'strat-o-matic-dev-key')

# Initialize components
fetcher = StatsFetcher()
league_fetcher = LeagueAveragesFetcher()

# Create data directories
Path('data').mkdir(exist_ok=True)
Path('data/cache').mkdir(parents=True, exist_ok=True)

# Configuration
MIN_YEAR = 1901
MAX_YEAR = 2025
MIN_PLATE_APPEARANCES = 50


INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Strat-O-Matic Card Maker</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }

        .container {
            background-color: white;
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
            padding: 40px;
            max-width: 600px;
            width: 100%;
        }

        h1 {
            text-align: center;
            color: #333;
            margin-bottom: 10px;
            font-size: 32px;
        }

        .subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 30px;
            font-size: 14px;
        }

        .form-group {
            margin-bottom: 25px;
        }

        label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 600;
        }

        input[type="text"],
        input[type="number"],
        select {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
        }

        input[type="text"]:focus,
        input[type="number"]:focus,
        select:focus {
            outline: none;
            border-color: #667eea;
        }

        .radio-group {
            display: flex;
            gap: 20px;
            margin-top: 8px;
        }

        .radio-group label {
            display: flex;
            align-items: center;
            gap: 8px;
            font-weight: normal;
            cursor: pointer;
        }

        .radio-group input[type="radio"] {
            width: auto;
        }

        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }

        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }

        button:active {
            transform: translateY(0);
        }

        button:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }

        .loading {
            display: none;
            text-align: center;
            margin-top: 20px;
        }

        .loading.active {
            display: block;
        }

        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .error {
            background-color: #fee;
            border: 1px solid #fcc;
            color: #c33;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
            display: none;
        }

        .error.active {
            display: block;
        }

        .disambiguation {
            margin-top: 20px;
            padding: 20px;
            background-color: #f8f9fa;
            border-radius: 8px;
            display: none;
        }

        .disambiguation.active {
            display: block;
        }

        .player-option {
            padding: 12px;
            margin: 8px 0;
            background-color: white;
            border: 2px solid #ddd;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .player-option:hover {
            border-color: #667eea;
            background-color: #f0f4ff;
        }

        .info {
            text-align: center;
            margin-top: 30px;
            color: #666;
            font-size: 12px;
        }

        .year-info {
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }

        /* Card display styles */
        .card-result {
            display: none;
            margin-top: 30px;
        }

        .card-result.active {
            display: block;
        }

        .card-header {
            text-align: center;
            padding: 15px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 8px 8px 0 0;
            margin-bottom: 0;
        }

        .card-content {
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
            border-radius: 0 0 8px 8px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.4;
            white-space: pre;
            overflow-x: auto;
        }

        .new-card-btn {
            margin-top: 20px;
            background: #28a745;
        }

        .new-card-btn:hover {
            box-shadow: 0 5px 15px rgba(40, 167, 69, 0.4);
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Strat-O-Matic Card Maker</h1>
        <p class="subtitle">Generate game-usable baseball cards from historical player statistics</p>

        <form id="cardForm">
            <div class="form-group">
                <label for="playerName">Player Name</label>
                <input type="text" id="playerName" name="playerName" required
                       placeholder="e.g., Babe Ruth, Mike Trout, Nolan Ryan">
            </div>

            <div class="form-group">
                <label for="year">Year</label>
                <input type="number" id="year" name="year" required
                       min="1901" max="2025" placeholder="e.g., 1927">
                <div class="year-info">Supports years 1901-2025</div>
            </div>

            <div class="form-group">
                <label>Card Type</label>
                <div class="radio-group">
                    <label>
                        <input type="radio" name="cardType" value="batter" checked>
                        Batter
                    </label>
                    <label>
                        <input type="radio" name="cardType" value="pitcher">
                        Pitcher
                    </label>
                </div>
            </div>

            <button type="submit" id="generateBtn">Generate Card</button>
        </form>

        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p style="margin-top: 15px; color: #666;">Generating card...</p>
        </div>

        <div class="error" id="error"></div>

        <div class="disambiguation" id="disambiguation">
            <h3 style="margin-bottom: 15px; color: #333;">Multiple players found. Please select:</h3>
            <div id="playerOptions"></div>
        </div>

        <div class="card-result" id="cardResult">
            <div class="card-header">
                <h2 id="cardTitle"></h2>
            </div>
            <div class="card-content" id="cardContent"></div>
            <button type="button" class="new-card-btn" onclick="resetForm()">Generate Another Card</button>
        </div>

        <div class="info">
            Supports players from 1901-2025 | Generated cards use community Bundy formulas
        </div>
    </div>

    <script>
        const form = document.getElementById('cardForm');
        const loading = document.getElementById('loading');
        const error = document.getElementById('error');
        const disambiguation = document.getElementById('disambiguation');
        const generateBtn = document.getElementById('generateBtn');
        const cardResult = document.getElementById('cardResult');

        let currentYear = null;
        let currentCardType = null;

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const playerName = document.getElementById('playerName').value;
            const year = document.getElementById('year').value;
            const cardType = document.querySelector('input[name="cardType"]:checked').value;

            currentYear = parseInt(year);
            currentCardType = cardType;

            await generateCard(playerName, currentYear, cardType);
        });

        async function generateCard(playerNameOrId, year, cardType, isId = false) {
            // Hide previous messages
            error.classList.remove('active');
            disambiguation.classList.remove('active');
            cardResult.classList.remove('active');
            loading.classList.add('active');
            generateBtn.disabled = true;

            try {
                const body = isId
                    ? { player_id: playerNameOrId, year: year, card_type: cardType }
                    : { player_name: playerNameOrId, year: year, card_type: cardType };

                const response = await fetch('/api/generate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(body)
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || 'Failed to generate card');
                }

                if (data.disambiguation) {
                    showDisambiguation(data.players);
                } else if (data.card) {
                    showCard(data);
                }
            } catch (err) {
                error.textContent = err.message;
                error.classList.add('active');
            } finally {
                loading.classList.remove('active');
                generateBtn.disabled = false;
            }
        }

        function showDisambiguation(players) {
            const optionsDiv = document.getElementById('playerOptions');
            optionsDiv.innerHTML = '';

            players.forEach(player => {
                const option = document.createElement('div');
                option.className = 'player-option';
                const yearsStr = player.years ? ` (${player.years})` : '';
                option.innerHTML = `
                    <strong>${player.name}</strong>${yearsStr}<br>
                    <small>ID: ${player.id}</small>
                `;
                option.onclick = () => generateCard(player.id, currentYear, currentCardType, true);
                optionsDiv.appendChild(option);
            });

            disambiguation.classList.add('active');
        }

        function showCard(data) {
            document.getElementById('cardTitle').textContent =
                `${data.player_name} - ${data.year} ${data.card_type.toUpperCase()}`;
            document.getElementById('cardContent').textContent = data.card;
            cardResult.classList.add('active');
            form.style.display = 'none';
        }

        function resetForm() {
            cardResult.classList.remove('active');
            form.style.display = 'block';
            document.getElementById('playerName').value = '';
            document.getElementById('year').value = '';
        }
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    """Render the main page."""
    return render_template_string(INDEX_HTML)


@app.route('/api/generate', methods=['POST'])
def generate_card():
    """Generate a card from player name/ID and year."""
    data = request.get_json()

    player_name = data.get('player_name')
    player_id = data.get('player_id')
    year = data.get('year')
    card_type = data.get('card_type', 'batter')

    if not year:
        return jsonify({'error': 'Year is required'}), 400

    if year < MIN_YEAR or year > MAX_YEAR:
        return jsonify({'error': f'Year must be between {MIN_YEAR} and {MAX_YEAR}'}), 400

    # If we have a player_id, use it directly
    if player_id:
        return generate_card_for_player(player_id, year, card_type)

    # Otherwise, search for the player
    if not player_name:
        return jsonify({'error': 'Player name or ID is required'}), 400

    # Search for players
    players = fetcher.search_player(player_name)

    if not players:
        return jsonify({'error': f'No players found matching "{player_name}"'}), 404

    # If multiple players found, return disambiguation
    if len(players) > 1:
        return jsonify({
            'disambiguation': True,
            'players': players
        })

    # Single player found, generate card
    return generate_card_for_player(players[0]['id'], year, card_type)


def generate_card_for_player(player_id: str, year: int, card_type: str = 'batter'):
    """Generate card for a specific player and year."""
    if card_type == 'pitcher':
        return generate_pitcher_card(player_id, year)
    else:
        return generate_batter_card(player_id, year)


def generate_batter_card(player_id: str, year: int):
    """Generate a batter card."""
    # Fetch player stats
    stats = fetcher.get_batting_stats(player_id, year)

    if not stats:
        return jsonify({'error': f'No batting statistics found for player in {year}'}), 404

    # Check minimum PA
    if stats.get('PA', 0) < MIN_PLATE_APPEARANCES:
        return jsonify({
            'error': f'Player has insufficient plate appearances ({stats.get("PA", 0)} PA, minimum {MIN_PLATE_APPEARANCES})'
        }), 400

    # Get league averages
    league = stats.get('league', 'AL')
    league_avg = league_fetcher.get_league_averages(year, league)

    if not league_avg:
        return jsonify({'error': 'Failed to fetch league averages'}), 500

    # Calculate card chances
    chances = BatterCardFormulas.calculate_batter_card_chances(stats, league_avg)

    # Generate layout
    player_name = stats.get('name', player_id)
    layout = CardLayoutGenerator.generate_layout(
        chances, player_name, year,
        player_stats=stats, card_type='batter'
    )

    # Format card as text
    card_text = str(layout)

    return jsonify({
        'card': card_text,
        'player_name': player_name,
        'year': year,
        'card_type': 'batter'
    })


def generate_pitcher_card(player_id: str, year: int):
    """Generate a pitcher card."""
    # Fetch player stats
    stats = fetcher.get_pitching_stats(player_id, year)

    if not stats:
        return jsonify({'error': f'No pitching statistics found for player in {year}'}), 404

    # Get league averages
    league = stats.get('league', 'AL')
    league_avg = league_fetcher.get_league_averages(year, league)

    if not league_avg:
        return jsonify({'error': 'Failed to fetch league averages'}), 500

    # Calculate card chances
    chances = PitcherCardFormulas.calculate_pitcher_card_chances(stats, league_avg)

    # Generate layout
    player_name = stats.get('name', player_id)
    layout = CardLayoutGenerator.generate_layout(
        chances, player_name, year,
        card_type='pitcher'
    )

    # Format card as text
    card_text = str(layout)

    return jsonify({
        'card': card_text,
        'player_name': player_name,
        'year': year,
        'card_type': 'pitcher'
    })


@app.route('/api/search', methods=['GET'])
def search_players():
    """Search for players by name."""
    name = request.args.get('name', '')
    if not name:
        return jsonify({'error': 'Name parameter is required'}), 400

    players = fetcher.search_player(name)
    return jsonify({'players': players})


if __name__ == '__main__':
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('DEBUG', 'true').lower() == 'true'

    print(f"Starting Strat-O-Matic Card Maker on http://{host}:{port}")
    print(f"Supports years {MIN_YEAR}-{MAX_YEAR}")
    app.run(host=host, port=port, debug=debug)
