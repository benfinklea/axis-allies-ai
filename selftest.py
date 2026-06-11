#!/usr/bin/env python3
"""Offline smoke test: no APIs, no speech, auto dice. Runs two full rounds
with stub players and checks core invariants. `python3 selftest.py`"""
import json
import random
import sys
from pathlib import Path

random.seed(42)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

config.SPEECH = False
config.DICE_MODE = "auto"
# fully isolated directory — selftest must NEVER touch the live game's
# logs/ files (it once overwrote logs/turn_start.json and corrupted a
# real game night's resume)
config.STATE_FILE = "logs/selftest/state.json"
config.TRANSCRIPT = "logs/selftest/transcript.md"
config.SNAPSHOT_DIR = "logs/selftest/snapshots"

import state as S


def main():
    state = S.new_game()
    assert state["ipcs"] == {"japan": 25, "uk": 30, "usa": 36, "ussr": 24, "germany": 32}
    assert S.income(state, "germany") > 0
    assert S.victory(state) is None

    # adjacency + legality
    assert S.check_move(state, "ussr", {"infantry": 1}, "Russia", "Karelia S.S.R.") is None
    assert S.check_move(state, "ussr", {"infantry": 99}, "Russia", "Karelia S.S.R.")
    assert S.check_move(state, "ussr", {"infantry": 1}, "Russia", "Germany")  # too far

    # combat engine: synthetic battle, auto dice, stub casualties
    from engine import combat
    from game import UI, build_players, run_turn
    from gamelog import GameLog
    from speech import Table
    bstate = S.new_game()
    bstate["game_id"] = "selftest-battle"
    bstate["units"]["Ukraine S.S.R."] = {
        "ussr": {"infantry": 2},
        "germany": {"infantry": 3, "armour": 2, "fighter": 1},
    }
    bplayers = build_players(all_stub=True)
    btable = Table()
    Path("logs/selftest/games/selftest-battle.jsonl").unlink(missing_ok=True)
    bglog = GameLog(bstate, "logs/selftest/games")
    result = combat.resolve_battle(bstate, "Ukraine S.S.R.", "germany",
                                   UI(btable, bplayers, bstate, bglog))
    assert result in ("attacker", "defender", "retreat")
    survivors = S.units_in(bstate, "Ukraine S.S.R.")
    assert not (survivors.get("germany") and survivors.get("ussr")), \
        "battle ended with both sides still present"
    if result == "attacker":
        assert bstate["owners"]["Ukraine S.S.R."] == "germany"
    print(f"\nBATTLE TEST OK — result: {result}, survivors: {survivors}")

    # two stub rounds end-to-end
    table = Table()
    players = build_players(all_stub=True)
    state["game_id"] = "selftest"
    Path("logs/selftest/games/selftest.jsonl").unlink(missing_ok=True)
    glog = GameLog(state, "logs/selftest/games")
    table.on_speak = glog.say
    for _ in range(2):
        for power in S.TURN_ORDER:
            if power in state["eliminated"]:
                continue
            state["turn"] = power
            run_turn(state, players, table, power, glog)
            if S.victory(state):
                break
        state["round"] += 1

    # the corpus log captured the game: spoken lines, AI decisions, dice
    # everyone gets a final word when a game ends
    from game import closing_comments
    closing_comments(state, players, table, glog, "selftest draw")

    # the corpus logs captured everything: spoken lines + AI decisions in the
    # game log, dice in the synthetic battle's log (stub rounds may not fight)
    kinds = {json.loads(l)["e"]
             for l in glog.path.read_text().splitlines() if l.strip()}
    assert {"say", "ai"} <= kinds, f"game log missing events: {kinds}"
    bkinds = {json.loads(l)["e"]
              for l in bglog.path.read_text().splitlines() if l.strip()}
    assert "dice" in bkinds, f"battle log missing dice events: {bkinds}"

    total_units = sum(n for t in state["units"].values()
                      for p in t.values() for n in p.values())
    assert total_units > 0
    assert all(v >= 0 for v in state["ipcs"].values())
    S.save(state, config.STATE_FILE)
    print(f"\nSELFTEST OK — {state['round'] - 1} rounds, "
          f"{total_units} units on the board, "
          f"treasuries {state['ipcs']}")


if __name__ == "__main__":
    main()
