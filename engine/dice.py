"""Dice: physical (typed at the table) or scripted.

Manual mode asks the table through the viewer's dice form (a request file
the viewer renders; it writes the response file back). A terminal, if one
is attached, works too — first answer wins.
"""
import json
import random
import select
import sys
import time
from pathlib import Path


def _read_response(resp):
    try:
        raw = json.loads(resp.read_text()).get("raw", "")
    except (json.JSONDecodeError, OSError):
        raw = ""
    resp.unlink(missing_ok=True)
    return raw


def _table_roll(n, label, log):
    import config
    base = Path(config.STATE_FILE).parent
    req, resp = base / "dice_request.json", base / "dice_response.json"
    base.mkdir(parents=True, exist_ok=True)
    resp.unlink(missing_ok=True)
    error = ""
    while True:
        req.write_text(json.dumps({"n": n, "label": label, "error": error}))
        if sys.stdin.isatty():
            print(f"  ROLL {n} dice — {label} (here or on the web) > ",
                  end="", flush=True)
        raw = None
        while raw is None:
            if resp.exists():
                raw = _read_response(resp)
            elif sys.stdin.isatty():
                ready, _, _ = select.select([sys.stdin], [], [], 0.5)
                if ready:
                    raw = sys.stdin.readline().strip()
            else:
                time.sleep(0.5)
        raw = raw.replace(" ", "")
        if len(raw) == n and all(c in "123456" for c in raw):
            req.unlink(missing_ok=True)
            rolls = [int(c) for c in raw]
            if log:
                log(label, rolls)
            return rolls
        error = f"need exactly {n} digits, each 1-6 (got {raw!r})"
        if sys.stdin.isatty():
            print(f"  {error}")


def battle(groups, context, mode="manual", speak=None, log=None):
    """One combat exchange rolled at once. groups = [{"id", "side"
    (attacker|defender), "power", "unit", "count", "target"}]; context =
    {"territory", "round", "attacker", "defenders", optional "note"}.
    Manual mode renders the viewer's battle board (attackers left,
    defenders right) and validates every field. Returns {id: [faces]}."""
    groups = [g for g in groups if g["count"] > 0]
    if not groups:
        return {}

    def _log(g, rolls):
        if log:
            log(f"{g['power']} {g['count']} {g['unit']} "
                f"({context['territory']} r{context.get('round', 0)})", rolls)

    if mode == "auto":
        out = {}
        for g in groups:
            rolls = [random.randint(1, 6) for _ in range(g["count"])]
            print(f"  [auto-dice] {g['power']} {g['unit']} x{g['count']}: "
                  f"{''.join(map(str, rolls))}")
            _log(g, rolls)
            out[g["id"]] = rolls
        return out

    import config
    base = Path(config.STATE_FILE).parent
    req, resp = base / "dice_request.json", base / "dice_response.json"
    base.mkdir(parents=True, exist_ok=True)
    resp.unlink(missing_ok=True)
    if speak:
        speak(f"Roll for {context['territory']} — the battle board is on "
              f"screen.")
    error = ""
    while True:
        req.write_text(json.dumps(
            {"battle": dict(context, groups=groups, error=error)}))
        while not resp.exists():
            time.sleep(0.5)
        try:
            raw = json.loads(resp.read_text()).get("rolls", {})
        except (OSError, json.JSONDecodeError):
            raw = {}
        resp.unlink(missing_ok=True)
        out, problems = {}, []
        for g in groups:
            s = str(raw.get(g["id"], "")).replace(" ", "")
            if len(s) == g["count"] and all(c in "123456" for c in s):
                out[g["id"]] = [int(c) for c in s]
            else:
                problems.append(f"{g['power']} {g['unit']}: need exactly "
                                f"{g['count']} digits, each 1-6")
        if not problems:
            req.unlink(missing_ok=True)
            for g in groups:
                _log(g, out[g["id"]])
            return out
        error = "; ".join(problems)


def roll(n, label, mode="manual", speak=None, log=None):
    """Returns a list of n d6 results. Manual mode: the table rolls real
    dice and types the faces as a digit string, e.g. '61423'."""
    if n <= 0:
        return []
    if mode == "auto":
        rolls = [random.randint(1, 6) for _ in range(n)]
        print(f"  [auto-dice] {label}: {''.join(map(str, rolls))}")
        if log:
            log(label, rolls)
        return rolls
    if speak:
        speak(f"Roll {n} dice: {label}")
    return _table_roll(n, label, log)
