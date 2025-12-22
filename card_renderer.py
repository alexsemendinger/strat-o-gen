"""Card rendering module for HTML and PDF output."""

from typing import Dict
from pathlib import Path


class CardRenderer:
    """Renders Strat-O-Matic cards as HTML and PDF."""

    def render_html(self, card_data: Dict) -> str:
        """
        Render card as HTML string.

        Args:
            card_data: Complete card data from CardEngine

        Returns:
            HTML string
        """
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{card_data['player_name']} - {card_data['year']} Strat-O-Matic Card</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background-color: #f0f0f0;
            padding: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }}

        .card-container {{
            background-color: white;
            border: 3px solid #333;
            border-radius: 10px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            width: 600px;
            padding: 20px;
        }}

        .card-header {{
            text-align: center;
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }}

        .player-name {{
            font-size: 28px;
            font-weight: bold;
            color: #000;
        }}

        .player-info {{
            font-size: 14px;
            color: #666;
            margin-top: 5px;
        }}

        .player-stats {{
            font-size: 16px;
            margin-top: 5px;
            font-weight: bold;
        }}

        .card-grid {{
            margin: 20px 0;
            border-collapse: collapse;
            width: 100%;
        }}

        .card-grid th, .card-grid td {{
            border: 1px solid #333;
            padding: 8px;
            text-align: center;
        }}

        .card-grid th {{
            background-color: #000;
            color: white;
            font-weight: bold;
        }}

        .dice-col {{
            background-color: #ddd;
            font-weight: bold;
        }}

        .result {{
            font-size: 12px;
            min-height: 30px;
        }}

        .result.HOMERUN {{
            background-color: #ffeb3b;
            font-weight: bold;
        }}

        .result.TRIPLE {{
            background-color: #81c784;
        }}

        .result.DOUBLE {{
            background-color: #a5d6a7;
        }}

        .result.SINGLE {{
            background-color: #c8e6c9;
        }}

        .result.WALK {{
            background-color: #bbdefb;
        }}

        .result.STRIKEOUT {{
            background-color: #ffcdd2;
        }}

        .ratings {{
            margin-top: 15px;
            padding: 10px;
            background-color: #f5f5f5;
            border: 1px solid #ccc;
            border-radius: 5px;
        }}

        .ratings-title {{
            font-weight: bold;
            margin-bottom: 5px;
        }}

        .rating-item {{
            display: inline-block;
            margin-right: 15px;
        }}

        .warnings {{
            margin-top: 15px;
            padding: 10px;
            background-color: #fff3cd;
            border: 1px solid #ffc107;
            border-radius: 5px;
        }}

        .confidence {{
            margin-top: 15px;
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 5px;
        }}

        .confidence.HIGH {{
            background-color: #d4edda;
            border-color: #28a745;
        }}

        .confidence.MEDIUM {{
            background-color: #fff3cd;
            border-color: #ffc107;
        }}

        .confidence.LOW {{
            background-color: #f8d7da;
            border-color: #dc3545;
        }}

        .chances-summary {{
            margin-top: 15px;
            padding: 10px;
            background-color: #e3f2fd;
            border: 1px solid #2196f3;
            border-radius: 5px;
            font-size: 12px;
        }}

        .chances-item {{
            display: inline-block;
            margin-right: 10px;
        }}

        @media print {{
            body {{
                background-color: white;
                padding: 0;
            }}
            .card-container {{
                box-shadow: none;
                border: 2px solid black;
            }}
            .no-print {{
                display: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="card-container">
        <div class="card-header">
            <div class="player-name">{card_data['player_name']}</div>
            <div class="player-info">
                {card_data['year']} {card_data['team']} |
                {', '.join(card_data['positions'])} |
                Bats: {card_data['bats']} Throws: {card_data['throws']}
            </div>
            <div class="player-stats">
                AVG: {card_data['stats']['AVG']:.3f} |
                HR: {card_data['stats']['HR']} |
                RBI: {card_data['stats']['RBI']} |
                R: {card_data['stats']['R']} |
                H: {card_data['stats']['H']} |
                PA: {card_data['stats']['PA']}
            </div>
        </div>

        <table class="card-grid">
            <thead>
                <tr>
                    <th>DICE</th>
                    <th>1</th>
                    <th>2</th>
                    <th>3</th>
                </tr>
            </thead>
            <tbody>
"""

        # Add grid rows
        for dice in range(2, 13):
            html += f"                <tr>\n"
            html += f"                    <td class='dice-col'>{dice}</td>\n"
            for col in [1, 2, 3]:
                result = card_data['grid'][col].get(dice, 'OUT')
                result_class = result.split('(')[0] if '(' in result else result
                html += f"                    <td class='result {result_class}'>{result}</td>\n"
            html += f"                </tr>\n"

        html += """
            </tbody>
        </table>

        <div class="ratings">
            <div class="ratings-title">RATINGS</div>
"""

        # Add ratings
        ratings = card_data['ratings']
        html += f"            <span class='rating-item'><strong>Power:</strong> {ratings.get('power', 'N')}</span>\n"
        html += f"            <span class='rating-item'><strong>Steal:</strong> {ratings.get('steal', 'E')}</span>\n"
        html += f"            <span class='rating-item'><strong>Speed:</strong> {ratings.get('speed', 'C')}</span>\n"
        html += f"            <span class='rating-item'><strong>Bunt:</strong> {ratings.get('bunt', 'B')}</span>\n"
        html += f"            <span class='rating-item'><strong>Hit & Run:</strong> {ratings.get('hit_and_run', 'B')}</span>\n"

        html += """
        </div>
"""

        # Add chances summary
        chances = card_data.get('chances', {})
        html += """
        <div class="chances-summary">
            <strong>Outcome Distribution (out of 108 chances):</strong><br>
"""
        for outcome in ['HOMERUN', 'TRIPLE', 'DOUBLE', 'SINGLE', 'WALK', 'HBP', 'STRIKEOUT', 'OUT']:
            count = chances.get(outcome, 0)
            if count > 0:
                html += f"            <span class='chances-item'>{outcome}: {count:.1f}</span>\n"

        html += """
        </div>
"""

        # Add confidence indicator
        confidence = card_data.get('confidence', {})
        overall = confidence.get('overall', 'MEDIUM')
        html += f"""
        <div class="confidence {overall}">
            <strong>Card Confidence: {overall}</strong>
"""

        if confidence.get('missing_data'):
            html += f"            <br><em>Missing data: {', '.join(confidence['missing_data'])}</em>\n"

        html += """
        </div>
"""

        # Add warnings if any
        all_warnings = card_data.get('warnings', []) + confidence.get('warnings', [])
        if all_warnings:
            html += """
        <div class="warnings">
            <strong>⚠ Warnings:</strong><br>
"""
            for warning in all_warnings:
                html += f"            • {warning}<br>\n"

            html += """
        </div>
"""

        html += """
    </div>
</body>
</html>
"""

        return html

    def save_pdf(self, card_data: Dict, output_path: str) -> bool:
        """
        Save card as PDF.

        Args:
            card_data: Complete card data
            output_path: Path to save PDF

        Returns:
            True if successful
        """
        try:
            from weasyprint import HTML

            html_content = self.render_html(card_data)
            HTML(string=html_content).write_pdf(output_path)
            return True
        except Exception as e:
            print(f"Error generating PDF: {e}")
            return False
