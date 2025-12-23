"""Flask web application for Strat-O-Matic Card Generator."""

import os
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, send_file
import tempfile

import config
from scraper import PlayerScraper
from card_engine import CardEngine
from card_renderer import CardRenderer

app = Flask(__name__)
app.secret_key = 'strat-o-matic-card-generator-secret-key'

# Initialize components
scraper = PlayerScraper()
engine = CardEngine()
renderer = CardRenderer()

# Create data directories
Path('data').mkdir(exist_ok=True)
Path(config.CACHE_DIR).mkdir(parents=True, exist_ok=True)


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
    </style>
</head>
<body>
    <div class="container">
        <h1>⚾ Strat-O-Matic Card Maker</h1>
        <p class="subtitle">Generate game-usable baseball cards from historical player statistics</p>

        <form id="cardForm">
            <div class="form-group">
                <label for="playerName">Player Name</label>
                <input type="text" id="playerName" name="playerName" required
                       placeholder="e.g., Babe Ruth, Lou Gehrig, Mike Trout">
            </div>

            <div class="form-group">
                <label for="year">Year</label>
                <input type="number" id="year" name="year" required
                       min="1901" max="2025" placeholder="e.g., 1927">
                <div class="year-info">Supports years 1901-2025</div>
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

        <div class="info">
            Supports players from 1901-2025 • Generated cards are approximations based on community formulas
        </div>
    </div>

    <script>
        const form = document.getElementById('cardForm');
        const loading = document.getElementById('loading');
        const error = document.getElementById('error');
        const disambiguation = document.getElementById('disambiguation');
        const generateBtn = document.getElementById('generateBtn');

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const playerName = document.getElementById('playerName').value;
            const year = document.getElementById('year').value;

            // Hide previous messages
            error.classList.remove('active');
            disambiguation.classList.remove('active');
            loading.classList.add('active');
            generateBtn.disabled = true;

            try {
                const response = await fetch('/api/generate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ player_name: playerName, year: parseInt(year) })
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || 'Failed to generate card');
                }

                if (data.disambiguation) {
                    // Show disambiguation UI
                    showDisambiguation(data.players, year);
                } else if (data.card_url) {
                    // Redirect to card page
                    window.location.href = data.card_url;
                }
            } catch (err) {
                error.textContent = err.message;
                error.classList.add('active');
            } finally {
                loading.classList.remove('active');
                generateBtn.disabled = false;
            }
        });

        function showDisambiguation(players, year) {
            const optionsDiv = document.getElementById('playerOptions');
            optionsDiv.innerHTML = '';

            players.forEach(player => {
                const option = document.createElement('div');
                option.className = 'player-option';
                option.innerHTML = `
                    <strong>${player.name}</strong><br>
                    <small>Career: ${player.years}</small>
                `;
                option.onclick = () => generateForPlayer(player.player_id, year);
                optionsDiv.appendChild(option);
            });

            disambiguation.classList.add('active');
        }

        async function generateForPlayer(playerId, year) {
            loading.classList.add('active');
            generateBtn.disabled = true;
            disambiguation.classList.remove('active');

            try {
                const response = await fetch('/api/generate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ player_id: playerId, year: parseInt(year) })
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || 'Failed to generate card');
                }

                if (data.card_url) {
                    window.location.href = data.card_url;
                }
            } catch (err) {
                error.textContent = err.message;
                error.classList.add('active');
            } finally {
                loading.classList.remove('active');
                generateBtn.disabled = false;
            }
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

    if not year:
        return jsonify({'error': 'Year is required'}), 400

    if year < config.MIN_YEAR or year > config.MAX_YEAR:
        return jsonify({'error': f'Year must be between {config.MIN_YEAR} and {config.MAX_YEAR}'}), 400

    # If we have a player_id, use it directly
    if player_id:
        return generate_card_for_player(player_id, year)

    # Otherwise, search for the player
    if not player_name:
        return jsonify({'error': 'Player name or ID is required'}), 400

    # Search for players
    players = scraper.search_players(player_name)

    if not players:
        return jsonify({'error': f'No players found matching "{player_name}"'}), 404

    # If multiple players found, return disambiguation
    if len(players) > 1:
        return jsonify({
            'disambiguation': True,
            'players': players
        })

    # Single player found, generate card
    return generate_card_for_player(players[0]['player_id'], year)


def generate_card_for_player(player_id: str, year: int):
    """Generate card for a specific player and year."""
    # Fetch player stats
    stats = scraper.get_player_stats(player_id, year)

    if not stats:
        return jsonify({'error': f'No statistics found for player in {year}'}), 404

    # Check minimum PA
    if stats.get('PA', 0) < config.MIN_PLATE_APPEARANCES:
        return jsonify({
            'error': f'Player has insufficient plate appearances ({stats.get("PA", 0)} PA, minimum {config.MIN_PLATE_APPEARANCES})'
        }), 400

    # Get league averages
    league = stats.get('league', 'AL')
    league_avg = scraper.get_league_averages(year, league)

    if not league_avg:
        return jsonify({'error': 'Failed to fetch league averages'}), 500

    # Generate card
    card_data = engine.generate_card(stats, league_avg)

    # Store card data in session/temp storage (simplified - using temp file)
    card_html = renderer.render_html(card_data)

    # Create temporary file for the card
    temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html', dir='data/cache')
    temp_file.write(card_html)
    temp_file.close()

    # Get the filename
    filename = os.path.basename(temp_file.name)

    return jsonify({
        'card_url': f'/card/{filename}',
        'player_name': card_data['player_name'],
        'year': year
    })


@app.route('/card/<filename>')
def view_card(filename):
    """View a generated card."""
    card_path = os.path.join('data/cache', filename)

    if not os.path.exists(card_path):
        return "Card not found", 404

    with open(card_path, 'r') as f:
        return f.read()


@app.route('/api/download/<filename>')
def download_pdf(filename):
    """Download card as PDF."""
    card_path = os.path.join('data/cache', filename)

    if not os.path.exists(card_path):
        return jsonify({'error': 'Card not found'}), 404

    # Read HTML
    with open(card_path, 'r') as f:
        html_content = f.read()

    # Generate PDF
    pdf_path = card_path.replace('.html', '.pdf')

    try:
        from weasyprint import HTML
        HTML(string=html_content).write_pdf(pdf_path)
        return send_file(pdf_path, as_attachment=True, download_name='strat-card.pdf')
    except Exception as e:
        return jsonify({'error': f'Failed to generate PDF: {str(e)}'}), 500


if __name__ == '__main__':
    print(f"Starting Strat-O-Matic Card Maker on http://{config.HOST}:{config.PORT}")
    print(f"Supports years {config.MIN_YEAR}-{config.MAX_YEAR}")
    app.run(host=config.HOST, port=config.PORT, debug=True)
