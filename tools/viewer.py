#!/usr/bin/env python3
"""Read-only live table viewer: each country, the AI playing it, what it's
thinking, all AI comms (war council + full per-power conversations), and the
board. Run from the repo root (or anywhere):

    python3 tools/viewer.py            # http://localhost:8484
    python3 tools/viewer.py 9000       # custom port

Reads logs/state.json, logs/minds/*.json and logs/transcript.md; refreshes
in the browser every 2 seconds. Touches nothing — safe to leave open during
a game.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config            # noqa: E402
import state as S        # noqa: E402

HTML_PATH = Path(__file__).resolve().parent / "viewer.html"
MAX_HISTORY = 60         # most recent messages per power sent to the browser


def _mind(power):
    path = ROOT / Path(config.STATE_FILE).parent / "minds" / f"{power}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text()).get("history", [])
    except (json.JSONDecodeError, OSError):
        return []


def _transcript_tail(n=80):
    path = ROOT / config.TRANSCRIPT
    if not path.exists():
        return []
    lines = [l.strip() for l in path.read_text().splitlines() if l.strip()]
    return lines[-n:]


def payload():
    state_path = ROOT / config.STATE_FILE
    if not state_path.exists():
        return {"no_game": True}
    st = json.loads(state_path.read_text())

    powers = []
    for p in S.TURN_ORDER:
        cfg = config.PLAYERS.get(p, {})
        hist = _mind(p)
        last_thought = next((m.get("content", "") for m in reversed(hist)
                             if m.get("role") == "assistant"), "")
        powers.append({
            "power": p,
            "side": S.SIDES[p],
            "provider": cfg.get("provider", "?"),
            "model": cfg.get("model", "?"),
            "voice": cfg.get("voice", ""),
            "ipcs": st["ipcs"].get(p, 0),
            "income": S.income(st, p),
            "tech": st.get("tech", {}).get(p, []),
            "capital": S.CAPITALS[p],
            "capital_owner": st["owners"].get(S.CAPITALS[p]),
            "eliminated": p in st.get("eliminated", []),
            "last_thought": last_thought,
            "history": hist[-MAX_HISTORY:],
        })

    territories = []
    for t in sorted(S.TERR):
        units = st["units"].get(t, {})
        owner = st["owners"].get(t)
        if not units and owner is None:
            continue
        sides_present = {S.SIDES[p] for p in units}
        territories.append({
            "name": t,
            "owner": owner,
            "water": S.TERR[t]["water"],
            "ipc": S.TERR[t]["ipc_value"],
            "units": units,
            "contested": len(sides_present) > 1,
        })

    return {
        "round": st["round"],
        "turn": st["turn"],
        "phase": st["phase"],
        "powers": powers,
        "council": st.get("council_notes", {}),
        "territories": territories,
        "axis_income": S.side_income(st, "axis"),
        "allies_income": S.side_income(st, "allies"),
        "econ_threshold": (config.ECON_VICTORY_AXIS_INCOME
                           if config.ECONOMIC_VICTORY else None),
        "transcript": _transcript_tail(),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/data":
            body = json.dumps(payload()).encode()
            ctype = "application/json"
        else:
            body = HTML_PATH.read_bytes()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep the terminal quiet during games


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8484
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"table viewer: http://localhost:{port}  (Ctrl-C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    main()
