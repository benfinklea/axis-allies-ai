#!/usr/bin/env python3
"""Axis & Allies AI-vs-AI orchestrator. Run from this directory:

    python3 game.py            # resume logs/state.json or start a new game
    python3 game.py --new      # force a fresh game
    python3 game.py --stub     # all five powers driven by the offline stub
    python3 game.py --auto-dice     # script rolls the dice (simulation)
    python3 game.py --max-turns N   # stop after N power-turns (simulation)
"""
import json
import sys
from pathlib import Path

import config
import council
import state as S
from engine import combat, dice
from players.base import (CASUALTY_SCHEMA, MOVES_SCHEMA, PLACEMENT_SCHEMA,
                          PRESS_SCHEMA, PURCHASE_SCHEMA, TECH_SCHEMA)
from players.stub import StubPlayer
from speech import Table

ROOT = Path(__file__).resolve().parent
TECHS = ["jet_power", "rockets", "super_subs", "long_range_aircraft",
         "industrial_technology", "heavy_bombers"]


def build_players(all_stub=False):
    rules = (ROOT / "prompts" / "rules_summary.md").read_text()
    players = {}
    for power, cfg in config.PLAYERS.items():
        persona = (f"You are the supreme commander of {power.upper()} in a "
                   f"classic Axis & Allies game.\n\n{rules}")
        provider = "stub" if all_stub else cfg["provider"]
        if provider == "stub":
            players[power] = StubPlayer(power, cfg, persona)
        elif provider == "anthropic":
            from players.anthropic_player import AnthropicPlayer
            players[power] = AnthropicPlayer(power, cfg, persona)
        else:
            from players.openai_compat_player import OpenAICompatPlayer
            players[power] = OpenAICompatPlayer(power, cfg, persona)
    return players


class UI:
    """What the combat engine needs from the table."""

    def __init__(self, table, players, state):
        self.table = table
        self.players = players
        self.state = state
        self.dice_mode = config.DICE_MODE

    def speak(self, text):
        self.table.speak(text)

    def ask_casualties(self, power, pool, hits, terr, aa_fire=False):
        player = self.players[power]
        if isinstance(player, StubPlayer):
            picked = player.casualties(pool, hits)
        else:
            prompt = (f"Battle in {terr}. You must remove exactly {hits} of "
                      f"these units as casualties: {json.dumps(pool)}.")
            picked = player.decide(prompt, CASUALTY_SCHEMA)
        remove = {c["type"]: c["count"] for c in picked["remove"]}
        # hard-validate: exactly `hits` units, all from the pool
        if (sum(remove.values()) != hits
                or any(pool.get(u, 0) < n for u, n in remove.items())):
            self.speak(f"{power} chose invalid casualties; cheapest-first applied.")
            remove = {c["type"]: c["count"] for c in
                      StubPlayer(power, {}, "").casualties(pool, hits)["remove"]}
        self.speak(f"{power} loses " + ", ".join(f"{n} {u}" for u, n in remove.items()))
        return remove

    def ask_press(self, power, terr):
        player = self.players[power]
        if isinstance(player, StubPlayer):
            return player.press_or_retreat(terr)
        return player.decide(
            f"The battle for {terr} continues. Press the attack or retreat? "
            f"(retreat_to must be a territory you attacked from)", PRESS_SCHEMA)


def ai_phase(player, state, prompt, schema, stub_method):
    if isinstance(player, StubPlayer):
        return stub_method(state)
    return player.decide(prompt, schema)


def apply_moves(state, table, power, decision, combat_allowed):
    legal = []
    for mv in decision.get("moves", []):
        units = {u["type"]: u["count"] for u in mv.get("units", [])}
        err = S.check_move(state, power, units, mv.get("from", ""), mv.get("to", ""))
        if err is None and not combat_allowed:
            if S.hostile_powers_in(state, mv["to"], power):
                err = "noncombat move into a hostile territory"
        if err:
            table.speak(f"Illegal move bounced ({err}).")
            continue
        S.apply_move(state, power, units, mv["from"], mv["to"])
        # unopposed entry into enemy-owned land flips it during combat movement
        if (combat_allowed and not S.TERR[mv["to"]]["water"]
                and not S.hostile_powers_in(state, mv["to"], power)
                and S.is_enemy(power, state["owners"].get(mv["to"], power))
                and any(u in S.LAND_UNITS for u in units)):
            S.capture(state, mv["to"], power)
            table.speak(f"{power} occupies undefended {mv['to']}.")
        desc = ", ".join(f"{n} {u}" for u, n in units.items())
        table.speak(f"{power}: move {desc} from {mv['from']} to {mv['to']}.")
        legal.append(mv)
    return legal


def run_turn(state, players, table, power):
    table.voice = config.PLAYERS[power].get("voice")
    player = players[power]
    ui = UI(table, players, state)
    board = S.summary_for_ai(state) + council.brief(state, power)
    table.speak(f"{power.upper()}'s turn. Treasury: {state['ipcs'][power]} IPCs.")

    # 1. Purchase
    state["phase"] = "purchase"
    d = ai_phase(player, state,
                 f"{board}\n\nPURCHASE PHASE. Treasury: {state['ipcs'][power]} "
                 f"IPCs. Unit costs are in your briefing. Research dice cost 5.",
                 PURCHASE_SCHEMA, getattr(player, "purchases", None))
    if d.get("reasoning"):
        table.speak(d["reasoning"])
    cost = sum(S.STATS[p["unit"]]["cost"] * p["quantity"]
               for p in d.get("purchases", []) if p["unit"] in S.STATS)
    research = max(0, int(d.get("research_dice", 0))) if config.WEAPONS_DEVELOPMENT else 0
    cost += research * 5
    if cost > state["ipcs"][power]:
        table.speak(f"{power} overspent ({cost} > {state['ipcs'][power]}); purchase voided.")
    else:
        state["ipcs"][power] -= cost
        pend = state["purchased_pending"].setdefault(power, {})
        for p in d.get("purchases", []):
            if p["unit"] in S.STATS:
                pend[p["unit"]] = pend.get(p["unit"], 0) + p["quantity"]
        for _ in range(research):
            if dice.roll(1, f"{power} research die (6 = breakthrough)",
                         config.DICE_MODE, table.speak)[0] == 6:
                roll2 = dice.roll(1, "breakthrough! which technology (1-6)",
                                  config.DICE_MODE, table.speak)[0]
                tech = TECHS[roll2 - 1]
                if tech not in state["tech"][power]:
                    state["tech"][power].append(tech)
                table.speak(f"{power} develops {tech.replace('_', ' ')}!")

    # 2-3. Combat movement + combat
    state["phase"] = "combat_move"
    board = S.summary_for_ai(state)
    d = ai_phase(player, state,
                 f"{board}\n\nCOMBAT MOVEMENT PHASE. Declare attacks (moves "
                 f"into enemy territory). Empty moves list = no attacks.",
                 MOVES_SCHEMA, getattr(player, "combat_moves", None))
    if d.get("reasoning"):
        table.speak(d["reasoning"])
    apply_moves(state, table, power, d, combat_allowed=True)

    state["phase"] = "combat"
    for terr in sorted(list(state["units"])):
        if S.units_in(state, terr, power) and S.hostile_powers_in(state, terr, power):
            combat.resolve_battle(state, terr, power, ui)

    # 4. Noncombat
    state["phase"] = "noncombat"
    board = S.summary_for_ai(state)
    d = ai_phase(player, state,
                 f"{board}\n\nNONCOMBAT MOVEMENT PHASE. Reposition freely; no "
                 f"moves into hostile territory.",
                 MOVES_SCHEMA, getattr(player, "noncombat_moves", None))
    if d.get("reasoning"):
        table.speak(d["reasoning"])
    apply_moves(state, table, power, d, combat_allowed=False)

    # 5. Mobilize
    state["phase"] = "mobilize"
    pend = state["purchased_pending"].get(power, {})
    if pend:
        d = ai_phase(player, state,
                     f"{S.summary_for_ai(state)}\n\nMOBILIZE PHASE. Place these "
                     f"purchased units at your industrial complexes: "
                     f"{json.dumps(pend)}. Also leave a short note_to_allies.",
                     PLACEMENT_SCHEMA, getattr(player, "placements", None))
        factories = [t for t, by_p in state["units"].items()
                     if by_p.get(power, {}).get("factory")
                     and state["owners"].get(t) == power]
        for pl in d.get("placements", []):
            unit, terr = pl.get("unit"), pl.get("territory")
            if pend.get(unit, 0) > 0 and (terr in factories or unit == "factory"):
                S.add_units(state, terr, power, {unit: 1})
                pend[unit] -= 1
                table.speak(f"{power} places a {unit} in {terr}.")
            else:
                table.speak(f"Placement bounced: {unit} in {terr}.")
        council.record(state, power, d.get("note_to_allies", ""))
        if d.get("reasoning"):
            table.speak(d["reasoning"])
        state["purchased_pending"][power] = {u: n for u, n in pend.items() if n > 0}

    # 6. Income
    if state["owners"].get(S.CAPITALS[power]) == power:
        gain = S.income(state, power)
        state["ipcs"][power] += gain
        table.speak(f"{power} collects {gain} IPCs.")
    else:
        table.speak(f"{power}'s capital is occupied — no income.")


def main():
    if "--auto-dice" in sys.argv:
        config.DICE_MODE = "auto"
    max_turns = None
    if "--max-turns" in sys.argv:
        max_turns = int(sys.argv[sys.argv.index("--max-turns") + 1])
    turns_played = 0
    table = Table()
    fresh = "--new" in sys.argv or not Path(config.STATE_FILE).exists()
    state = S.new_game() if fresh else S.load(config.STATE_FILE)
    players = build_players(all_stub="--stub" in sys.argv)
    table.speak("Axis and Allies. Five artificial minds. One world at war."
                if fresh else f"Resuming round {state['round']}.")

    while True:
        order = [p for p in S.TURN_ORDER if p not in state["eliminated"]]
        start = order.index(state["turn"]) if state["turn"] in order else 0
        for power in order[start:]:
            state["turn"] = power
            run_turn(state, players, table, power)
            S.save(state, config.STATE_FILE)
            snap = Path(config.SNAPSHOT_DIR) / f"r{state['round']}_{power}.json"
            S.save(state, snap)
            win = S.victory(state)
            if win:
                table.speak(f"GAME OVER: the {win[0]} win — {win[1]}!")
                return
            turns_played += 1
            if max_turns is not None and turns_played >= max_turns:
                table.speak(f"Stopping after {turns_played} turns as asked. "
                            f"The war continues another day.")
                return
        if config.ECONOMIC_VICTORY and \
                S.side_income(state, "axis") >= config.ECON_VICTORY_AXIS_INCOME:
            table.speak(f"GAME OVER: Axis economic victory "
                        f"({S.side_income(state, 'axis')} IPC income)!")
            return
        state["round"] += 1
        state["turn"] = S.TURN_ORDER[0]
        table.speak(f"Round {state['round']} begins.")


if __name__ == "__main__":
    main()
