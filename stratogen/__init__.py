"""Strat-O-Matic card generator.

Modules:
    model       Card data model and chance accounting
    card_text   Parser/serializer for the plain-text card format
    lahman      Offline player stats and league averages (Lahman database)
    simulate    Statistical tester: card-implied rates vs actual stats
    generate    Card generation (chances -> layout)
    ratings     Stealing / running / injury ratings
    render      HTML rendering
"""

__version__ = "2.0"
