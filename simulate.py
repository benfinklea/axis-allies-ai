#!/usr/bin/env python3
"""Headless fast simulations: run whole games in seconds, try rule variants.

    python3 simulate.py                          # 5 stub games, base rules
    python3 simulate.py --games 20               # more samples
    python3 simulate.py --variant variants/super-subs-everywhere.json
    python3 simulate.py --model fast             # all five powers on one
                                                 # gateway model (slow, real AI)
    python3 simulate.py --games 10 --seed 42     # reproducible dice
    python3 simulate.py --max-rounds 12          # call it a draw after N rounds

Each run writes logs/sim/<stamp>/: per-game corpus logs, per-turn snapshots
(watch any of them on the board view: http://localhost:8484/board), and
results.jsonl + a printed summary. The live game's logs/ files are never
touched.

A variant file overrides rules without code changes:
    {
      "name": "cheap bombers",
      "config":     {"ECON_VICTORY_AXIS_INCOME": 96},
      "unit_stats": {"bomber": {"cost": 9}},
      "setup":      {"ipcs": {"ussr": 30}}
    }
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config

config.SPEECH = False
config.DICE_MODE = "auto"


def apply_variant(path):
    v = json.loads(Path(path).read_text())
    for key, val in v.get("config", {}).items():
        if not hasattr(config, key):
            raise SystemExit(f"variant config key unknown: {key}")
        setattr(config, key, val)
    import state as S
    for unit, fields in v.get("unit_stats", {}).items():
        if unit not in S.STATS:
            raise SystemExit(f"variant unit unknown: {unit}")
        S.STATS[unit].update(fields)
    return v


def apply_setup_overrides(state, variant):
    for section, payload in (variant or {}).get("setup", {}).items():
        if section not in state:
            raise SystemExit(f"variant setup section unknown: {section}")
        if isinstance(state[section], dict):
            state[section].update(payload)
        else:
            state[section] = payload


def build_sim_players(model):
    """Stub players by default; --model X puts every power on one gateway
    intent (real AI, much slower, costs whatever the route costs)."""
    if model:
        for cfg in config.PLAYERS.values():
            cfg["provider"] = "openai_compat"
            cfg["model"] = model
            cfg["base_url"] = config.FLEET_BASE_URL
            cfg["api_key_env"] = "FLEET_API_KEY"
    from game import build_players
    return build_players(all_stub=not model)


def run_one_game(gdir, players, variant, max_rounds, seed):
    import state as S
    from game import run_turn, closing_comments
    from gamelog import GameLog
    from speech import Table

    random.seed(seed)
    config.STATE_FILE = str(gdir / "state.json")
    config.TRANSCRIPT = str(gdir / "transcript.md")
    config.SNAPSHOT_DIR = str(gdir / "snapshots")

    state = S.new_game()
    apply_setup_overrides(state, variant)
    state["game_id"] = gdir.name
    glog = GameLog(state, gdir / "games")
    table = Table()
    table.on_speak = glog.say

    start = time.time()
    result = {"winner": None, "reason": "draw: round cap", "rounds": 0}
    while state["round"] <= max_rounds:
        for power in [p for p in S.TURN_ORDER
                      if p not in state["eliminated"]]:
            state["turn"] = power
            run_turn(state, players, table, power, glog)
            S.save(state, config.STATE_FILE)
            S.save(state, Path(config.SNAPSHOT_DIR)
                   / f"r{state['round']}_{power}.json")
            win = S.victory(state)
            if win:
                result = {"winner": win[0], "reason": win[1],
                          "rounds": state["round"]}
                break
        else:
            if config.ECONOMIC_VICTORY and (S.side_income(state, "axis")
                                            >= config.ECON_VICTORY_AXIS_INCOME):
                result = {"winner": "axis",
                          "reason": "economic victory",
                          "rounds": state["round"]}
            state["round"] += 1
            continue
        break
    result["rounds"] = result["rounds"] or min(state["round"], max_rounds)
    result["seconds"] = round(time.time() - start, 2)
    result["final_income"] = {p: S.income(state, p) for p in S.TURN_ORDER}
    result["axis_income"] = S.side_income(state, "axis")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=5)
    ap.add_argument("--variant", help="path to a rule-variant json")
    ap.add_argument("--model", help="gateway intent for ALL powers "
                                    "(default: offline stub players)")
    ap.add_argument("--max-rounds", type=int, default=15)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    variant = apply_variant(args.variant) if args.variant else None
    players = build_sim_players(args.model)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = ROOT / "logs" / "sim" / stamp
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps(
        {"variant": variant, "model": args.model, "games": args.games,
         "max_rounds": args.max_rounds, "seed": args.seed}, indent=1))

    results = []
    base_seed = args.seed if args.seed is not None else int(time.time())
    for g in range(args.games):
        gdir = run_dir / f"g{g + 1:03d}"
        gdir.mkdir()
        r = run_one_game(gdir, players, variant, args.max_rounds,
                         base_seed + g)
        r["game"] = gdir.name
        results.append(r)
        with (run_dir / "results.jsonl").open("a") as f:
            f.write(json.dumps(r) + "\n")
        print(f"  {gdir.name}: {r['winner'] or 'draw'} "
              f"({r['reason']}) in {r['rounds']} rounds, {r['seconds']}s")

    wins = {}
    for r in results:
        wins[r["winner"] or "draw"] = wins.get(r["winner"] or "draw", 0) + 1
    avg_rounds = sum(r["rounds"] for r in results) / len(results)
    print(f"\n{args.games} games"
          + (f" [{variant['name']}]" if variant else " [base rules]") + ":")
    for side, n in sorted(wins.items(), key=lambda kv: -kv[1]):
        print(f"  {side}: {n} ({100 * n // len(results)}%)")
    print(f"  avg length: {avg_rounds:.1f} rounds")
    print(f"\nrun dir: {run_dir}")
    print("watch any game on the board: http://localhost:8484/board "
          "(pick its snapshots from the scrubber)")


if __name__ == "__main__":
    main()
