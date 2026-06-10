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
import time
from pathlib import Path

import config
import council
import state as S
from gamelog import GameLog
from engine import combat, dice
from players.base import (ASSESSMENT_SCHEMA, CASUALTY_SCHEMA, MOVES_SCHEMA,
                          PLACEMENT_SCHEMA, PRESS_SCHEMA, PURCHASE_SCHEMA,
                          TECH_SCHEMA)
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
                   f"classic Axis & Allies game.\n\nHOUSE RULE: you may not "
                   f"use web search, browsing, or any external tool to look "
                   f"up strategy or help. Play purely from your own training "
                   f"knowledge.\n\n{rules}")
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

    def __init__(self, table, players, state, glog):
        self.table = table
        self.players = players
        self.state = state
        self.glog = glog
        self.dice_mode = config.DICE_MODE
        self.dice_log = glog.dice

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
            dump_mind(player)
            self.glog.ai(power, prompt, picked)
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
        prompt = (f"The battle for {terr} continues. Press the attack or "
                  f"retreat? (retreat_to must be a territory you attacked from)")
        decision = player.decide(prompt, PRESS_SCHEMA)
        dump_mind(player)
        self.glog.ai(power, prompt, decision)
        return decision


def dump_mind(player):
    """Snapshot a player's full conversation for the live viewer."""
    hist = getattr(player, "history", None)
    if not hist:
        return
    def clean(msg):
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str):
            return {"role": msg["role"], "content": content}
        parts = []  # Anthropic SDK content blocks -> plain text
        for b in content or []:
            kind = getattr(b, "type", None)
            if kind == "thinking":
                parts.append("[thinking] " + getattr(b, "thinking", ""))
            elif kind == "text":
                parts.append(getattr(b, "text", ""))
        return {"role": msg["role"], "content": "\n".join(parts)}
    path = Path(config.STATE_FILE).parent / "minds" / f"{player.power}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"power": player.power, "history": [clean(m) for m in hist]}, indent=1))


def ai_phase(player, state, prompt, schema, stub_method, glog=None):
    if isinstance(player, StubPlayer):
        decision = stub_method(state)
    else:
        decision = player.decide(prompt, schema)
        dump_mind(player)
    if glog:
        glog.ai(player.power, prompt, decision)
    return decision


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


def run_turn(state, players, table, power, glog):
    table.voice = config.PLAYERS[power].get("voice")
    player = players[power]
    ui = UI(table, players, state, glog)
    board = S.summary_for_ai(state) + council.brief(state, power)
    table.speak(f"{power.upper()}'s turn. Treasury: {state['ipcs'][power]} IPCs.")

    # 0. State of the war — spoken before any decisions
    state["phase"] = "briefing"
    d = ai_phase(player, state,
                 f"{board}\n\nTURN BRIEFING. Before you act: in three to five "
                 f"short sentences, give your read on the war — the overall "
                 f"situation, your side's chances, and what you are watching "
                 f"this turn. Plain speech; it will be read aloud at the table.",
                 ASSESSMENT_SCHEMA, getattr(player, "assessment", None), glog)
    if d.get("assessment"):
        table.speak(d["assessment"])

    # 1. Purchase
    state["phase"] = "purchase"
    d = ai_phase(player, state,
                 f"{board}\n\nPURCHASE PHASE. Treasury: {state['ipcs'][power]} "
                 f"IPCs. Unit costs are in your briefing. Research dice cost 5.",
                 PURCHASE_SCHEMA, getattr(player, "purchases", None), glog)
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
                         config.DICE_MODE, table.speak, glog.dice)[0] == 6:
                roll2 = dice.roll(1, "breakthrough! which technology (1-6)",
                                  config.DICE_MODE, table.speak, glog.dice)[0]
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
                 MOVES_SCHEMA, getattr(player, "combat_moves", None), glog)
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
                 MOVES_SCHEMA, getattr(player, "noncombat_moves", None), glog)
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
                     PLACEMENT_SCHEMA, getattr(player, "placements", None),
                     glog)
        factories = [t for t, by_p in state["units"].items()
                     if by_p.get(power, {}).get("factory")
                     and state["owners"].get(t) == power]
        placed, bounced = {}, {}
        for pl in d.get("placements", []):
            unit, terr = pl.get("unit"), pl.get("territory")
            if pend.get(unit, 0) > 0 and (terr in factories or unit == "factory"):
                S.add_units(state, terr, power, {unit: 1})
                pend[unit] -= 1
                bucket = placed
            else:
                bucket = bounced
            slot = bucket.setdefault(str(terr), {})
            slot[str(unit)] = slot.get(str(unit), 0) + 1
        for terr, units in placed.items():
            desc = ", ".join(f"{n} {u}" for u, n in sorted(units.items()))
            table.speak(f"{power} places {desc} in {terr}.")
        for terr, units in bounced.items():
            desc = ", ".join(f"{n} {u}" for u, n in sorted(units.items()))
            table.speak(f"Placement bounced: {desc} in {terr}.")
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

    # 7. Debrief — comment on how the turn went, spoken before the next power
    state["phase"] = "debrief"
    d = ai_phase(player, state,
                 f"{S.summary_for_ai(state)}\n\nTURN DEBRIEF. Your turn is "
                 f"over. In two or three short sentences, comment on what "
                 f"just happened — what worked, what hurt, and your outlook. "
                 f"Plain speech; it will be read aloud at the table.",
                 ASSESSMENT_SCHEMA, getattr(player, "debrief", None), glog)
    if d.get("assessment"):
        table.speak(d["assessment"])


def closing_comments(state, players, table, glog, result_text):
    """Every commander gets a final word after the game ends."""
    state["phase"] = "closing"
    board = S.summary_for_ai(state)
    for power in S.TURN_ORDER:
        player = players[power]
        d = ai_phase(player, state,
                     f"{board}\n\nTHE GAME IS OVER: {result_text}. Your final "
                     f"word, in three or four short sentences: what went "
                     f"right or wrong for you this game, and what you would "
                     f"do differently next time. Plain speech; read aloud.",
                     ASSESSMENT_SCHEMA, getattr(player, "closing", None), glog)
        if d.get("assessment"):
            table.voice = config.PLAYERS[power].get("voice")
            table.speak(f"{power.upper()}'s final word.")
            table.speak(d["assessment"])


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
    if "game_id" not in state:
        state["game_id"] = time.strftime("%Y%m%d-%H%M%S")
    players = build_players(all_stub="--stub" in sys.argv)
    glog = GameLog(state, Path(config.STATE_FILE).parent / "games")
    if fresh:
        glog.start(
            roster={p: {"provider": c["provider"], "model": c["model"]}
                    for p, c in config.PLAYERS.items()},
            rules={"weapons_development": config.WEAPONS_DEVELOPMENT,
                   "economic_victory": config.ECONOMIC_VICTORY,
                   "econ_threshold": config.ECON_VICTORY_AXIS_INCOME,
                   "war_council": config.WAR_COUNCIL,
                   "dice_mode": config.DICE_MODE,
                   "stub": "--stub" in sys.argv})
    table.on_speak = glog.say
    table.speak("Axis and Allies. Five artificial minds. One world at war."
                if fresh else f"Resuming round {state['round']}.")

    while True:
        order = [p for p in S.TURN_ORDER if p not in state["eliminated"]]
        start = order.index(state["turn"]) if state["turn"] in order else 0
        for power in order[start:]:
            state["turn"] = power
            run_turn(state, players, table, power, glog)
            S.save(state, config.STATE_FILE)
            snap = Path(config.SNAPSHOT_DIR) / f"r{state['round']}_{power}.json"
            S.save(state, snap)
            win = S.victory(state)
            if win:
                glog.result(win[0], win[1])
                table.speak(f"GAME OVER: the {win[0]} win — {win[1]}!")
                closing_comments(state, players, table, glog,
                                 f"the {win[0]} won ({win[1]})")
                return
            turns_played += 1
            if max_turns is not None and turns_played >= max_turns:
                table.speak(f"Stopping after {turns_played} turns as asked. "
                            f"The war continues another day.")
                return
        if config.ECONOMIC_VICTORY and \
                S.side_income(state, "axis") >= config.ECON_VICTORY_AXIS_INCOME:
            glog.result("axis", f"economic victory at "
                                f"{S.side_income(state, 'axis')} IPC income")
            table.speak(f"GAME OVER: Axis economic victory "
                        f"({S.side_income(state, 'axis')} IPC income)!")
            closing_comments(state, players, table, glog,
                             "the Axis won by economic victory")
            return
        state["round"] += 1
        state["turn"] = S.TURN_ORDER[0]
        table.speak(f"Round {state['round']} begins.")


if __name__ == "__main__":
    main()
