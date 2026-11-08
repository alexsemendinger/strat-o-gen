"""Strat-O-Matic Card Maker - local web app.

Run:  uv run app.py      (uv provisions Flask automatically)
 or:  python3 app.py     (needs: python3 -m pip install flask)
It opens your browser by itself (http://localhost:5001 unless that port is
busy). Options: --port N (or STRATOGEN_PORT=N), --no-browser.

Everything is offline: player statistics and league averages come from the
bundled Lahman database (1871-2025). The only dependency is Flask.
"""
# /// script
# requires-python = ">=3.9"
# dependencies = ["flask>=2.0"]
# ///

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

try:
    from flask import Flask, Response, jsonify, render_template, request
    from werkzeug.exceptions import HTTPException
except ModuleNotFoundError:
    sys.exit(
        "Flask isn't installed for this Python interpreter.\n"
        "Install it with THIS python so pip and python match:\n\n"
        f'    "{sys.executable}" -m pip install flask\n\n'
        "(A bare 'pip install flask' may target a different Python "
        "installation on your machine.)")

from stratogen import service
from stratogen.lahman import default_db
from stratogen.render import CARD_CSS, SHEET_CSS

BASE_DIR = Path(__file__).resolve().parent
APP_ID = "strat-o-gen"
DEFAULT_PORT = 5001
FIRST_YEAR = 1871

app = Flask(__name__, root_path=str(BASE_DIR),
            template_folder=str(BASE_DIR / "templates"),
            static_folder=str(BASE_DIR / "static"))
log = logging.getLogger("strat-o-gen")

_warmed = threading.Event()


def warm_in_background():
    """Parse the data files while the user is still typing, so the first
    search and first card are instant."""
    def _warm():
        db = default_db()
        db.warm()
        db.warm_rosters()
        _warmed.set()
    threading.Thread(target=_warm, daemon=True).start()


def _max_year() -> int:
    # The year bound comes from the data when it's loaded (so a new
    # season's files are picked up automatically); 2025 until then.
    return default_db().max_year() if _warmed.is_set() else 2025


# --- errors -------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra


@app.errorhandler(ApiError)
def _api_error(exc: ApiError):
    return jsonify(error=exc.message, **exc.extra), exc.status


@app.errorhandler(service.CardError)
def _card_error(exc: service.CardError):
    return jsonify(exc.to_json()), exc.status


@app.errorhandler(HTTPException)
def _http_error(exc: HTTPException):
    messages = {404: "There's no such page or API endpoint.",
                405: "That address doesn't accept this kind of request."}
    return jsonify(error=messages.get(exc.code, exc.description)), exc.code


@app.errorhandler(Exception)
def _server_error(exc: Exception):
    log.exception("unexpected error")
    return jsonify(error=f"Something went wrong on our side "
                         f"({type(exc).__name__}). Please try again."), 500


# --- input validation ----------------------------------------------------------------

def _year(value, *, required: bool = True) -> int | None:
    """An int or a numeric string within the data's seasons (bools,
    floats and words are rejected)."""
    if value is None or value == "":
        if required:
            raise ApiError("Enter a year, like 1927.")
        return None
    if isinstance(value, bool):
        raise ApiError("year must be a whole number, like 1927")
    if isinstance(value, int):
        year = value
    elif isinstance(value, str) and value.strip().isdigit():
        year = int(value.strip())
    else:
        raise ApiError("year must be a whole number, like 1927")
    if not FIRST_YEAR <= year <= _max_year():
        raise ApiError(f"Pick a year from {FIRST_YEAR} to {_max_year()}.")
    return year


def _text(value, name: str, *, max_len: int = 80, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(f"{name} must be text")
    value = value.strip()
    if required and not value:
        raise ApiError(f"Enter a {name}.")
    if len(value) > max_len:
        raise ApiError(f"{name} is too long")
    return value


_ID = re.compile(r"^[A-Za-z0-9.'_-]{1,16}$")


def _player_id(value) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise ApiError("Unknown player.", 404)
    if not default_db().player_info(value):
        raise ApiError("Unknown player.", 404)
    return value


def _kind(value) -> str:
    if value in (None, "", "auto"):
        return "auto"
    if value not in service.KINDS:
        raise ApiError("kind must be 'batter', 'pitcher' or 'auto'")
    return value


def _sides(value) -> str:
    value = value or "both"
    if value not in service.SIDES:
        raise ApiError("sides must be 'basic', 'advanced' or 'both'")
    return value


# --- pages ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", max_year=_max_year(), first_year=FIRST_YEAR)


@app.route("/card.css")
def card_css():
    return Response(CARD_CSS + SHEET_CSS, mimetype="text/css")


@app.route("/api/health")
def api_health():
    return jsonify(app=APP_ID, ok=True, ready=_warmed.is_set())


# --- players -------------------------------------------------------------------------

@app.route("/api/suggest")
def api_suggest():
    q = _text(request.args.get("q"), "name", max_len=60, required=False)
    if not q:
        return jsonify(players=[])
    db = default_db()
    players = [service.player_summary(db, hit["player_id"])
               for hit in db.suggest_players(q, limit=8)]
    return jsonify(players=[p for p in players if p])


@app.route("/api/search")
def api_search():
    name = _text(request.args.get("name"), "player name", max_len=80)
    year = _year(request.args.get("year"), required=False)
    db = default_db()
    players, seen = [], set()
    for hit in db.search_players(name):
        if hit.player_id in seen:
            continue
        seen.add(hit.player_id)
        summary = service.player_summary(db, hit.player_id)
        if summary:
            players.append(summary)
    if year is not None:
        # Players with a card that season first (stable otherwise).
        for p in players:
            p["has_year"] = year in p["batting_years"] or year in p["pitching_years"]
        players.sort(key=lambda p: not p["has_year"])
    return jsonify(players=players)


@app.route("/api/random")
def api_random():
    """A random substantial player-season, ready to generate."""
    db = default_db()
    for _ in range(20):
        player_id, year, kind = db.random_season()
        if year in db.playable_years(player_id, kind):
            break
    summary = service.player_summary(db, player_id) or {}
    return jsonify(dict(summary, player_id=player_id, year=year, kind=kind,
                        name=db.player_name(player_id)))


@app.route("/api/generate", methods=["POST"])
def api_generate():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("Send JSON like {\"player_id\": \"ruthba01\", \"year\": 1927}.")
    player_id = _player_id(payload.get("player_id"))
    year = _year(payload.get("year"))
    kind = _kind(payload.get("kind"))
    db = default_db()
    cs = service.make_cards(db, player_id, year, kind)
    data = cs.to_api()
    query = f"player_id={cs.player_id}&year={cs.year}&kind={cs.kind}"
    data["downloads"] = {"html": f"/download/card?{query}&format=html",
                         "json": f"/download/card?{query}&format=json"}
    data["batting_years"] = db.playable_years(player_id, "batter")
    data["pitching_years"] = db.playable_years(player_id, "pitcher")
    data["years"] = sorted(set(data["batting_years"]) | set(data["pitching_years"]))
    return jsonify(data)


def _filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-") or "card"


@app.route("/download/card")
def download_card():
    args = request.args
    player_id = _player_id(args.get("player_id"))
    year = _year(args.get("year"))
    kind = _kind(args.get("kind"))
    fmt = args.get("format", "html")
    if fmt not in ("html", "json"):
        raise ApiError("format must be 'html' or 'json'")
    cs = service.make_cards(default_db(), player_id, year, kind)
    name = _filename(f"{cs.name} {cs.year} {cs.kind}")
    if fmt == "json":
        body = json.dumps(cs.card_data(), indent=1, ensure_ascii=False)
        resp = Response(body, mimetype="application/json")
        resp.headers["Content-Disposition"] = f'attachment; filename="{name}.json"'
        return resp
    resp = Response(service.card_document(cs, _sides(args.get("sides"))),
                    mimetype="text/html")
    resp.headers["Content-Disposition"] = f'attachment; filename="{name}.html"'
    return resp


# --- teams ---------------------------------------------------------------------------

@app.route("/api/teams")
def api_teams():
    year = _year(request.args.get("year"))
    db = default_db()
    leagues: dict[str, list] = {}
    for t in db.teams(year):
        leagues.setdefault(t["league"], []).append(
            {k: t[k] for k in ("team_id", "name", "league", "division", "W", "L", "G", "rank")})
    first, last = db.team_years()
    return jsonify(year=year, first_year=first, last_year=last,
                   leagues=[{"league": lg, "teams": teams}
                            for lg, teams in leagues.items()])


def _team_args():
    year = _year(request.args.get("year"))
    team_id = _text(request.args.get("team"), "team", max_len=8)
    if not re.match(r"^[A-Za-z0-9]{1,8}$", team_id):
        raise ApiError("Unknown team.", 404)
    return year, team_id


@app.route("/api/team")
def api_team():
    year, team_id = _team_args()
    ts = service.team_set(default_db(), year, team_id)
    data = ts.to_api()
    data["downloads"] = {s: f"/download/team?year={year}&team={team_id}&sides={s}"
                         for s in service.SIDES}
    return jsonify(data)


@app.route("/download/team")
def download_team():
    year, team_id = _team_args()
    sides = _sides(request.args.get("sides"))
    ts = service.team_set(default_db(), year, team_id)
    resp = Response(service.team_document(ts, sides), mimetype="text/html")
    name = _filename(f"{ts.title} {sides}")
    resp.headers["Content-Disposition"] = f'attachment; filename="{name}.html"'
    return resp


# --- launcher -----------------------------------------------------------------------

def _ours(port: int, timeout: float = 1.5) -> bool:
    """Does this app already answer on the port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",
                                    timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("app") == APP_ID
    except Exception:
        return False


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name == "nt":
            # Windows: refuse to share a port someone else is listening on.
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _candidate_ports(port: int) -> list[int]:
    """The ports a launch may use, in order: the requested one and the next
    19 (a busy port moves the app up, never onto someone else's port)."""
    return [port] + list(range(port + 1, port + 20))


def _running_port(port: int) -> int | None:
    """The port an already-running copy of this app answers on, if any —
    including one that had to move up because the default port was busy."""
    for candidate in _candidate_ports(port):
        if _ours(candidate, timeout=0.5):
            return candidate
    return None


def _make_server(port: int):
    """Bind the first free port from `port` on (port 0 = any) and return
    (server, port). Never shares a port with another program."""
    from werkzeug import serving
    serving.BaseWSGIServer.allow_reuse_address = os.name != "nt"
    candidates = _candidate_ports(port) + [0]
    for candidate in candidates:
        if candidate and not _port_free(candidate):
            continue
        try:
            server = serving.make_server("127.0.0.1", candidate, app, threaded=True)
        except (OSError, SystemExit):
            continue
        return server, server.server_port
    raise SystemExit("Couldn't find a free network port to run on.")


def _open_when_ready(port: int, url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _ours(port, timeout=1.0):
            webbrowser.open(url)
            return
        time.sleep(0.15)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strat-O-Matic Card Maker web app")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("STRATOGEN_PORT") or DEFAULT_PORT),
                        help=f"port to use (default {DEFAULT_PORT}, or STRATOGEN_PORT)")
    parser.add_argument("--no-browser", action="store_true",
                        help="don't open a browser window")
    args = parser.parse_args(argv)

    running = _running_port(args.port)
    if running is not None:
        url = f"http://localhost:{running}/"
        if args.no_browser:
            print(f"The Card Maker is already running at {url}")
        else:
            print(f"The Card Maker is already running at {url} - opening it in your browser.")
            webbrowser.open(url)
        return 0

    # Quiet console: no development-server banner, no line per request.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logging.basicConfig(level=logging.ERROR, format="%(message)s")
    server, port = _make_server(args.port)
    url = f"http://localhost:{port}/"
    warm_in_background()
    print("=" * 60)
    print(f"  Strat-O-Matic Card Maker is running at  {url}")
    print("  Keep this window open while you use it; close it to quit.")
    print("=" * 60, flush=True)
    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(port, url), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
