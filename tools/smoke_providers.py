#!/usr/bin/env python3
"""One tiny live call per configured provider. Run before game night:

    python3 tools/smoke_providers.py            # all five powers
    python3 tools/smoke_providers.py ussr usa   # just the local boxes

Each provider is asked for a trivial JSON decision; cost is a few cents
total for the paid APIs and zero for local. Prints OK/FAIL per power.
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from players.base import _obj

PING_SCHEMA = _obj({"ready": {"type": "boolean"}, "motto": {"type": "string"}})

PROMPT = ("Connectivity check before a game of Axis & Allies. Reply with "
          "ready=true and a short battle motto for your nation (one sentence).")


def main():
    powers = sys.argv[1:] or list(config.PLAYERS)
    results = {}
    for power in powers:
        cfg = config.PLAYERS[power]
        label = f"{power:8s} {cfg['provider']:14s} {cfg['model']}"
        if "FILL-ME-IN" in str(cfg.get("base_url", "")):
            results[power] = False
            print(f"FAIL  {label}  — base_url still FILL-ME-IN in config.py")
            continue
        try:
            if cfg["provider"] == "anthropic":
                from players.anthropic_player import AnthropicPlayer
                player = AnthropicPlayer(power, cfg, "You are a connectivity check.")
            else:
                from players.openai_compat_player import OpenAICompatPlayer
                player = OpenAICompatPlayer(power, cfg, "You are a connectivity check.")
            reply = player.decide(PROMPT, PING_SCHEMA)
            ok = bool(reply.get("ready"))
            results[power] = ok
            print(f"{'OK  ' if ok else 'WARN'}  {label}  — {reply.get('motto', '')!r}")
        except Exception as e:
            results[power] = False
            print(f"FAIL  {label}  — {type(e).__name__}: {e}")
            if "-v" in sys.argv:
                traceback.print_exc()
    print()
    if all(results.values()):
        print(f"All {len(results)} providers ready. Roll for initiative.")
    else:
        bad = [p for p, ok in results.items() if not ok]
        print(f"Not ready: {', '.join(bad)}. See CLAUDE.md troubleshooting map.")
        sys.exit(1)


if __name__ == "__main__":
    main()
