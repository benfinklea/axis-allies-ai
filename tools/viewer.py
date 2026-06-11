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
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config            # noqa: E402
import state as S        # noqa: E402

HTML_PATH = Path(__file__).resolve().parent / "viewer.html"
MAX_HISTORY = 60         # most recent messages per power sent to the browser


def _pretty(content):
    """Turn a raw JSON decision into table-readable text."""
    try:
        d = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content
    if not isinstance(d, dict):
        return content
    parts = []
    if d.get("assessment"):
        parts.append(d["assessment"])
    if d.get("reasoning"):
        parts.append(d["reasoning"])
    for p in d.get("purchases", []):
        parts.append(f"🛒 buy {p.get('quantity')} {p.get('unit')}")
    if d.get("research_dice"):
        parts.append(f"🧪 {d['research_dice']} research dice")
    for m in d.get("moves", []):
        us = ", ".join(f"{u.get('count')} {u.get('type')}"
                       for u in m.get("units", []))
        parts.append(f"➡️ {us}: {m.get('from')} → {m.get('to')}")
    for p in d.get("placements", []):
        parts.append(f"📦 place {p.get('unit')} in {p.get('territory')}")
    if d.get("remove"):
        parts.append("💀 casualties: " + ", ".join(
            f"{c.get('count')} {c.get('type')}" for c in d["remove"]))
    if d.get("action"):
        retreat = f" to {d['retreat_to']}" if d.get("retreat_to") else ""
        parts.append(f"⚔️ {d['action']}{retreat}")
    if d.get("note_to_allies"):
        parts.append(f"✉️ to allies: {d['note_to_allies']}")
    return "\n".join(parts) or content


def _mind(power):
    path = ROOT / Path(config.STATE_FILE).parent / "minds" / f"{power}.json"
    if not path.exists():
        return []
    try:
        history = json.loads(path.read_text()).get("history", [])
    except (json.JSONDecodeError, OSError):
        return []
    return [{"role": m.get("role"),
             "content": (_pretty(m.get("content", ""))
                         if m.get("role") == "assistant"
                         else m.get("content", ""))}
            for m in history]


def _photo_report():
    """Latest photo-check verdict FROM THIS GAME (run dirs and game_ids
    share the timestamp format, so a string compare scopes them)."""
    photo_root = ROOT / Path(config.STATE_FILE).parent / "photos"
    if not photo_root.exists():
        return None
    game_id = ""
    state_path = ROOT / config.STATE_FILE
    if state_path.exists():
        try:
            game_id = json.loads(state_path.read_text()).get("game_id", "")
        except json.JSONDecodeError:
            pass
    runs = sorted((d for d in photo_root.iterdir()
                   if d.is_dir() and d.name >= game_id), reverse=True)
    for run in runs:
        v = run / "verdict.md"
        if v.exists():
            text = v.read_text().split("## Raw inventory")[0].strip()
            return {"when": run.name, "text": text}
    return None


def _transcript_tail(n=80):
    path = ROOT / config.TRANSCRIPT
    if not path.exists():
        return []
    lines = [l.strip() for l in path.read_text().splitlines() if l.strip()]
    return lines[-n:]


def payload():
    """Always serves whatever exists — transcript and AI minds update live
    even before the game writes its first state checkpoint."""
    state_path = ROOT / config.STATE_FILE
    st = None
    if state_path.exists():
        try:
            st = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            st = None  # mid-write race; next poll gets it

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
            "ipcs": st["ipcs"].get(p, 0) if st else 0,
            "income": S.income(st, p) if st else 0,
            "tech": st.get("tech", {}).get(p, []) if st else [],
            "capital": S.CAPITALS[p],
            "capital_owner": (st["owners"].get(S.CAPITALS[p]) if st else p),
            "eliminated": p in st.get("eliminated", []) if st else False,
            "last_thought": last_thought,
            "history": hist[-MAX_HISTORY:],
        })

    territories = []
    if st:
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
        "round": st["round"] if st else 0,
        "turn": st["turn"] if st else "starting",
        "phase": st["phase"] if st else "waiting for first checkpoint",
        "powers": powers,
        "council": st.get("council_notes", {}) if st else {},
        "territories": territories,
        "axis_income": S.side_income(st, "axis") if st else 0,
        "allies_income": S.side_income(st, "allies") if st else 0,
        "econ_threshold": (config.ECON_VICTORY_AXIS_INCOME
                           if config.ECONOMIC_VICTORY else None),
        "transcript": _transcript_tail(),
        "photo_report": _photo_report(),
        "paused": (ROOT / Path(config.STATE_FILE).parent / "PAUSE").exists(),
        "muted": (ROOT / Path(config.STATE_FILE).parent / "MUTE").exists(),
        "running": _game_running(),
        "actions": _actions() if _game_running() else [],
        "dice": _dice_request() if _game_running() else None,
    }


def _dice_request():
    path = ROOT / Path(config.STATE_FILE).parent / "dice_request.json"
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _game_running():
    return subprocess.run(["pgrep", "-f", "game.py"],
                          capture_output=True).returncode == 0


def _game_control(action):
    """Start a fresh game / end the running one, via the axis tmux session."""
    if action == "stop":
        subprocess.run(["tmux", "kill-session", "-t", "axis"],
                       capture_output=True)
        subprocess.run(["pkill", "-f", "game.py"], capture_output=True)
    elif action == "start" and not _game_running():
        subprocess.run(["tmux", "new-session", "-d", "-s", "axis",
                        "-c", str(ROOT), "./play --new"],
                       capture_output=True)


def _actions():
    path = ROOT / Path(config.STATE_FILE).parent / "actions.json"
    try:
        return json.loads(path.read_text()).get("items", [])
    except (OSError, json.JSONDecodeError):
        return []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/game":  # end the running game / start a fresh one
            length = int(self.headers.get("Content-Length", 0))
            try:
                action = json.loads(self.rfile.read(length)).get("action", "")
            except json.JSONDecodeError:
                action = ""
            _game_control(action)
            body = json.dumps({"running": _game_running()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/roll":  # die faces typed into the web form
            length = int(self.headers.get("Content-Length", 0))
            try:
                raw = json.loads(self.rfile.read(length)).get("raw", "")
            except json.JSONDecodeError:
                raw = ""
            path = ROOT / Path(config.STATE_FILE).parent / "dice_response.json"
            path.write_text(json.dumps({"raw": str(raw)}))
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/done":  # the table finished the DO THIS list
            path = ROOT / Path(config.STATE_FILE).parent / "actions.json"
            path.write_text(json.dumps({"items": []}))
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/mute":  # toggle the voice without touching the game
            flag = ROOT / Path(config.STATE_FILE).parent / "MUTE"
            if flag.exists():
                flag.unlink()
            else:
                flag.parent.mkdir(parents=True, exist_ok=True)
                flag.write_text("muted via viewer\n")
            body = json.dumps({"muted": flag.exists()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/pause":  # toggle the pause flag the game honors
            flag = ROOT / Path(config.STATE_FILE).parent / "PAUSE"
            if flag.exists():
                flag.unlink()
            else:
                flag.parent.mkdir(parents=True, exist_ok=True)
                flag.write_text("paused via viewer\n")
            body = json.dumps({"paused": flag.exists()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/data":
            try:
                body = json.dumps(payload()).encode()
            except Exception as e:  # never leave the page frozen on a 500
                body = json.dumps({"error": str(e)}).encode()
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
