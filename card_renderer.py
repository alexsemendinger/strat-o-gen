"""Card rendering module for HTML and PDF output - SOM-style format."""

from typing import Dict
from pathlib import Path


class CardRenderer:
    """Renders Strat-O-Matic cards as HTML and PDF matching official card layout."""

    def render_html(self, card_data: Dict) -> str:
        """
        Render card as HTML string matching official SOM card layout.

        Args:
            card_data: Complete card data from CardEngine

        Returns:
            HTML string
        """
        player_name = card_data['player_name'].upper()
        bats = card_data['bats']
        year = card_data['year']
        team = card_data['team']
        positions = '/'.join(card_data['positions'])

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{player_name} - {year} Strat-O-Matic Card</title>
    <style>
        @page {{
            size: 3.5in 2.5in;
            margin: 0;
        }}

        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f0f0f0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }}

        .card {{
            width: 800px;
            background: white;
            border: 3px solid black;
            padding: 0;
            box-shadow: 0 4px 8px rgba(0,0,0,0.3);
        }}

        .card-header {{
            background: #f0f0f0;
            padding: 8px 12px;
            border-bottom: 2px solid black;
            text-align: center;
        }}

        .player-name {{
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 4px;
        }}

        .player-info {{
            font-size: 12px;
        }}

        .card-body {{
            display: flex;
        }}

        .platoon-section {{
            flex: 1;
        }}

        .platoon-section.vs-lhp {{
            background-color: #c8e1f5;
            border-right: 2px solid black;
        }}

        .platoon-section.vs-rhp {{
            background-color: #ffd4d4;
        }}

        .platoon-header {{
            text-align: center;
            padding: 6px;
            font-weight: bold;
            font-size: 11px;
            border-bottom: 2px solid black;
        }}

        .platoon-stats {{
            font-size: 10px;
            text-align: center;
            padding: 4px;
            border-bottom: 1px solid #666;
        }}

        .card-grid {{
            display: table;
            width: 100%;
            border-collapse: collapse;
        }}

        .grid-row {{
            display: table-row;
        }}

        .dice-cell {{
            display: table-cell;
            width: 30px;
            text-align: center;
            font-weight: bold;
            border: 1px solid #666;
            padding: 4px 2px;
            font-size: 13px;
            background-color: #e0e0e0;
        }}

        .result-cell {{
            display: table-cell;
            border: 1px solid #666;
            padding: 4px 4px;
            font-size: 10px;
            line-height: 1.3;
            text-align: center;
            min-height: 28px;
            vertical-align: middle;
        }}

        .col-header {{
            display: table-cell;
            text-align: center;
            font-weight: bold;
            border: 1px solid #666;
            padding: 4px;
            font-size: 12px;
            background-color: #000;
            color: white;
        }}

        .ratings {{
            border-top: 2px solid black;
            padding: 8px;
            font-size: 11px;
            text-align: center;
            background-color: #f8f8f8;
        }}

        .rating-item {{
            display: inline-block;
            margin: 0 8px;
            font-weight: bold;
        }}

        .warnings {{
            padding: 8px;
            background-color: #fff3cd;
            border-top: 1px solid #ffc107;
            font-size: 10px;
        }}

        @media print {{
            body {{
                background-color: white;
                padding: 0;
            }}
            .card {{
                box-shadow: none;
                border: 2px solid black;
            }}
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="card-header">
            <div class="player-name">{bats} | {player_name}</div>
            <div class="player-info">If-{positions} {team}/{year}</div>
        </div>

        <div class="card-body">
            <!-- VS LEFT-HAND PITCHERS -->
            <div class="platoon-section vs-lhp">
                <div class="platoon-header">AGAINST LEFT-HAND PITCHERS</div>
                <div class="platoon-stats">Power-{card_data['ratings']['power']}</div>

                <div class="card-grid">
                    <!-- Column headers -->
                    <div class="grid-row">
                        <div class="dice-cell"></div>
                        <div class="col-header">1</div>
                        <div class="col-header">2</div>
                        <div class="col-header">3</div>
                    </div>
"""

        # Add rows for dice 2-12 (VS LHP)
        for dice in range(2, 13):
            html += f"""
                    <div class="grid-row">
                        <div class="dice-cell">{dice}</div>
"""
            for col in [1, 2, 3]:
                result = card_data['grid']['vs_lhp'][col].get(dice, 'OUT')
                # Format result for display
                result_display = result.replace('\n', '<br>')
                html += f"""                        <div class="result-cell">{result_display}</div>\n"""

            html += """                    </div>\n"""

        html += """
                </div>
            </div>

            <!-- VS RIGHT-HAND PITCHERS -->
            <div class="platoon-section vs-rhp">
                <div class="platoon-header">AGAINST RIGHT-HAND PITCHERS</div>
                <div class="platoon-stats">Power-{power_rating}</div>

                <div class="card-grid">
                    <!-- Column headers -->
                    <div class="grid-row">
                        <div class="dice-cell"></div>
                        <div class="col-header">1</div>
                        <div class="col-header">2</div>
                        <div class="col-header">3</div>
                    </div>
""".replace('{power_rating}', card_data['ratings']['power'])

        # Add rows for dice 2-12 (VS RHP)
        for dice in range(2, 13):
            html += f"""
                    <div class="grid-row">
                        <div class="dice-cell">{dice}</div>
"""
            for col in [1, 2, 3]:
                result = card_data['grid']['vs_rhp'][col].get(dice, 'OUT')
                # Format result for display
                result_display = result.replace('\n', '<br>')
                html += f"""                        <div class="result-cell">{result_display}</div>\n"""

            html += """                    </div>\n"""

        html += """
                </div>
            </div>
        </div>

        <div class="ratings">
"""

        # Add ratings
        ratings = card_data['ratings']
        stats = card_data['stats']
        sb = stats.get('SB', 0) if 'SB' in card_data.get('stats', {}) else card_data.get('SB', 0)
        cs = stats.get('CS', 0) if 'CS' in card_data.get('stats', {}) else card_data.get('CS', 0)

        html += f"""
            <span class="rating-item">stealing-({ratings.get('steal', 'E')})</span>
            <span class="rating-item">{sb}/{cs} ({sb + cs}-{sb})</span>
            <span class="rating-item">bunting-{ratings.get('bunt', 'D')}</span>
            <span class="rating-item">hit & run-{ratings.get('hit_and_run', 'B')}</span>
"""

        # Add running rating
        html += f"""
            <br>
            <span class="rating-item">running {ratings.get('speed', '1-10')}</span>
"""

        html += """
        </div>
"""

        # Add warnings if any
        all_warnings = card_data.get('warnings', []) + card_data['confidence'].get('warnings', [])
        if all_warnings:
            html += """
        <div class="warnings">
            <strong>⚠ Notes:</strong>
"""
            for warning in all_warnings:
                html += f"            {warning}<br>\n"

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
