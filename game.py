#!/usr/bin/env python3
"""Axis & Allies AI-vs-AI orchestrator. Run from this directory:

    python3 game.py            # resume logs/state.json or start a new game
    python3 game.py --new      # force a fresh game
    python3 game.py --stub     # all five powers driven by the offline stub
    python3 game.py --auto-dice     # script rolls the dice (simulation)
    python3 game.py --max-turns N   # stop after N power-turns (simulation)
"""
import copy
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

# Structured rulebook knowledge: the relevant sections are injected into
# each phase's prompt so an AI re-reads the governing rules right before
# it acts (full-book-in-system-prompt blew the gateway's size limits).
RULES_KB = json.loads((ROOT / "prompts" / "rules_kb.json").read_text())


def _kb_units(state, power):
    """Rule entries for every unit type this power owns or has pending."""
    owned = set()
    for by_power in state["units"].values():
        owned |= set(by_power.get(power, {}))
    owned |= set(state.get("purchased_pending", {}).get(power, {}))
    lines = []
    for unit in sorted(owned & set(RULES_KB["units"])):
        u = RULES_KB["units"][unit]
        lines.append(f"- {unit.upper()} (cost {u['cost']}, attack "
                     f"{u['attack']}, defense {u['defense']}, move "
                     f"{u['move']}): {u['rules']}")
    return "\n".join(lines)


def phase_rules(phase, state, power):
    """The rulebook text an AI must read before acting in this phase."""
    kb = RULES_KB
    if phase == "purchase":
        body = (kb["action_sequence"]["1_develop_weapons_purchase"]
                + "\n" + kb["weapons_development"]["technologies"]
                + "\nPLACEMENT LIMITS (buy with these in mind): "
                + kb["action_sequence"]["5_place_units"])
    elif phase == "combat_move":
        body = (kb["action_sequence"]["2_combat_movement"] + "\n"
                + "\n".join(f"{k.upper()}: {v}"
                            for k, v in kb["movement_rules"].items())
                + "\nAMPHIBIOUS ASSAULTS: "
                + kb["combat_rules"]["amphibious_assault"]
                + "\nAIR CANNOT CAPTURE: "
                + kb["combat_rules"]["air_cannot_capture"]
                + "\n\nYOUR UNITS — read each before moving it:\n"
                + _kb_units(state, power))
    elif phase == "noncombat":
        body = (kb["action_sequence"]["4_noncombat_movement"] + "\n"
                + "STOP_ON_CONTACT: " + kb["movement_rules"]["stop_on_contact"]
                + "\nNEUTRALS: " + kb["movement_rules"]["neutral_territories"]
                + "\nCANALS: " + kb["movement_rules"]["canals"]
                + "\n\nYOUR UNITS — read each before moving it:\n"
                + _kb_units(state, power))
    elif phase == "mobilize":
        body = kb["action_sequence"]["5_place_units"]
    else:
        return ""
    return f"\n\nRULEBOOK FOR THIS STEP — read before deciding:\n{body}\n"


def build_players(all_stub=False):
    rules = (ROOT / "prompts" / "rules_summary.md").read_text()
    rulebook = ROOT / "prompts" / "rulebook_full.txt"
    if getattr(config, "RULEBOOK_IN_PROMPT", False) and rulebook.exists():
        rules += ("\n\n--- FULL RULEBOOK (classic 2nd edition, OCR of the "
                  "physical manual — authoritative when it conflicts with "
                  "the summary above; OCR artifacts possible) ---\n\n"
                  + rulebook.read_text())
    players = {}
    for power, cfg in config.PLAYERS.items():
        persona = (f"You are the supreme commander of {power.upper()} in a "
                   f"classic Axis & Allies game.\n\nHOUSE RULE: you may not "
                   f"use web search, browsing, or any external tool to look "
                   f"up strategy or help. Play purely from your own training "
                   f"knowledge.\n\nACTION SEQUENCE: every turn follows the "
                   f"classic action sequence, strictly in order — "
                   f"1 develop weapons and purchase units, 2 combat "
                   f"movement (declare and move ALL attacking units for ALL "
                   f"of this turn's attacks in one batch — there is no "
                   f"second wave; any unit not moved now cannot join combat "
                   f"this turn), 3 combat (every battle you set up resolves, "
                   f"one territory at a time), 4 noncombat movement, "
                   f"5 mobilize new units, 6 collect income. You will be "
                   f"prompted for each step one at a time, in order. Answer "
                   f"ONLY for the step you are asked about: no moves during "
                   f"purchase, no purchases during movement, and your "
                   f"reasoning should stay on the current step.\n\n{rules}")
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
        # only consult the AI when a real choice exists — forced outcomes
        # resolve instantly so the dice keep their rhythm
        types = [u for u, n in pool.items() if n]
        if hits >= sum(pool.values()):
            remove = dict(pool)
        elif len(types) == 1:
            remove = {types[0]: hits}
        else:
            player = self.players[power]
            if isinstance(player, StubPlayer):
                picked = player.casualties(pool, hits)
            else:
                prompt = (f"Battle in {terr}. You must remove exactly {hits} "
                          f"of these units as casualties: {json.dumps(pool)}.")
                picked = call_ai(player, self.state, prompt, CASUALTY_SCHEMA)
                dump_mind(player)
                self.glog.ai(power, prompt, picked)
            remove = {c["type"]: c["count"] for c in picked["remove"]}
            # hard-validate: exactly `hits` units, all from the pool
            if (sum(remove.values()) != hits
                    or any(pool.get(u, 0) < n for u, n in remove.items())):
                self.table.note(f"{power} chose invalid casualties; "
                                f"cheapest-first applied.")
                remove = {c["type"]: c["count"] for c in
                          StubPlayer(power, {}, "")
                          .casualties(pool, hits)["remove"]}
        self.speak(f"{power} loses " + ", ".join(f"{n} {u}" for u, n in remove.items()))
        return remove

    def table_removals(self, terr, items):
        """Combat outcome for the humans: list the pieces to take off the
        board (and any capture bookkeeping), wait for Done."""
        post_actions(items)
        await_done(self.table, items)

    def ask_sub_withdraw(self, power, terr, n_subs, dests):
        """Classic special: defending submarines may withdraw after a round
        of fire, to an adjacent friendly or unoccupied sea zone."""
        player = self.players[power]
        if isinstance(player, StubPlayer):
            return {"action": "press"}
        attackers = {p: S.units_in(self.state, terr, p)
                     for p in S.hostile_powers_in(self.state, terr, power)}
        prompt = (f"Your {n_subs} submarine(s) in {terr} survived this "
                  f"combat round. Attackers still present: "
                  f"{json.dumps(attackers)}. Classic rule: defending "
                  f"submarines may withdraw to ONE adjacent friendly or "
                  f"unoccupied sea zone. Legal destinations: {dests}. "
                  f"action 'retreat' (with retreat_to) withdraws the subs; "
                  f"'press' keeps them fighting.")
        decision = call_ai(player, self.state, prompt, PRESS_SCHEMA)
        dump_mind(player)
        self.glog.ai(power, prompt, decision)
        return decision

    def ask_press(self, power, terr):
        player = self.players[power]
        if isinstance(player, StubPlayer):
            return player.press_or_retreat(terr)
        mine = S.units_in(self.state, terr, power)
        theirs = {p: S.units_in(self.state, terr, p)
                  for p in S.hostile_powers_in(self.state, terr, power)}
        origins = [o for o in
                   self.state.get("attack_origins", {}).get(terr, [])
                   if not S.hostile_powers_in(self.state, o, power)]
        retreat_help = (f"If you retreat, ALL surviving attackers fall back "
                        f"together, the way they came, to exactly ONE of "
                        f"these spaces: {origins}. No other destination is "
                        f"legal." if origins else
                        "Retreat is NOT possible for this battle (no "
                        "friendly origin space to fall back to).")
        prompt = (f"The battle for {terr} continues. Your remaining "
                  f"attackers: {json.dumps(mine)}. Defenders still "
                  f"standing: {json.dumps(theirs)}. Press the attack or "
                  f"retreat? {retreat_help}")
        decision = call_ai(player, self.state, prompt, PRESS_SCHEMA)
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


def call_ai(player, state, prompt, schema):
    """Every model call goes through here: a thinking flag for the viewer,
    and retries with backoff so a provider hiccup doesn't kill game night."""
    flag = Path(config.STATE_FILE).parent / "thinking.json"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(json.dumps({"power": player.power,
                                "phase": state.get("phase")}))
    delay = 5
    try:
        for attempt in range(4):
            try:
                return player.decide(prompt, schema)
            except Exception as e:
                if attempt == 3:
                    raise
                print(f"  [provider] {player.power} call failed "
                      f"({str(e)[:100]}); retry in {delay}s")
                time.sleep(delay)
                delay *= 3
    finally:
        flag.unlink(missing_ok=True)


def ai_phase(player, state, prompt, schema, stub_method, glog=None):
    if isinstance(player, StubPlayer):
        decision = stub_method(state)
    else:
        decision = call_ai(player, state, prompt, schema)
        dump_mind(player)
    if glog:
        glog.ai(player.power, prompt, decision)
    return decision


def post_actions(items):
    """Put physical actions on the viewer's DO THIS panel immediately —
    BEFORE the audio reads them — so the table moves plastic while the
    voice catches up."""
    if items:
        actions = Path(config.STATE_FILE).parent / "actions.json"
        actions.write_text(json.dumps({"items": items}))


def await_done(table, items):
    """Block until the table presses Done (manual-dice games only)."""
    if not items or config.DICE_MODE != "manual":
        return
    actions = Path(config.STATE_FILE).parent / "actions.json"
    table.speak("Press done when the board matches.")
    while True:
        try:
            if not json.loads(actions.read_text()).get("items"):
                return
        except (OSError, json.JSONDecodeError):
            return
        time.sleep(1)


def validate_moves(state, power, decision, combat_allowed):
    """Dry-run a full move plan against a copy of the state; returns a list
    of error strings (empty = the whole plan is legal)."""
    trial = copy.deepcopy(state)
    errs = []
    for mv in decision.get("moves", []):
        units = {(S.canon_unit(u["type"]) or u["type"]): u["count"]
                 for u in mv.get("units", [])}
        desc = ", ".join(f"{n} {u}" for u, n in units.items())
        err = S.check_move(trial, power, units, mv.get("from", ""),
                           mv.get("to", ""),
                           combat_air_landing=combat_allowed)
        if err is None and not combat_allowed and \
                S.hostile_powers_in(trial, mv["to"], power):
            err = "noncombat move into a hostile territory"
        if err:
            errs.append(f"- {desc} {mv.get('from')} -> {mv.get('to')}: {err}")
        else:
            S.apply_move(trial, power, units, mv["from"], mv["to"])
            S.note_air_moves(trial, power, units, mv["from"], mv["to"],
                             combat=combat_allowed)
    return errs


def decide_moves(player, state, power, table, glog, base_prompt, stub_method,
                 combat_allowed):
    """Think, plan, THEN respond: the AI's plan is validated privately and
    bounced back with reasons until it's fully legal (or retries run out).
    Only the final plan gets spoken and applied."""
    prompt = base_prompt
    d = ai_phase(player, state, prompt, MOVES_SCHEMA, stub_method, glog)
    for _ in range(config.MAX_LEGALITY_RETRIES):
        errs = validate_moves(state, power, d, combat_allowed)
        if not errs or isinstance(player, StubPlayer):
            break
        table.note(f"{power} plan has {len(errs)} illegal moves; re-asking.")
        prompt = (f"Your plan contains ILLEGAL moves:\n" + "\n".join(errs)
                  + f"\n\nResubmit your ENTIRE corrected move list (legal "
                  f"moves included again, illegal ones fixed or dropped). "
                  f"Remember: units only reach adjacent territories per "
                  f"their movement range; land units cannot cross sea.")
        d = ai_phase(player, state, prompt, MOVES_SCHEMA, stub_method, glog)
    return d


def apply_moves(state, table, power, decision, combat_allowed):
    todo, lines = [], []
    for mv in decision.get("moves", []):
        units = {(S.canon_unit(u["type"]) or u["type"]): u["count"]
                 for u in mv.get("units", [])}
        err = S.check_move(state, power, units, mv.get("from", ""),
                           mv.get("to", ""),
                           combat_air_landing=combat_allowed)
        if err is None and not combat_allowed:
            if S.hostile_powers_in(state, mv["to"], power):
                err = "noncombat move into a hostile territory"
        if err:
            # logged + on screen, but silent — no audio for AI mistakes
            table.note(f"Illegal move bounced ({err}).")
            continue
        defenders = S.hostile_powers_in(state, mv["to"], power)
        # ferried land units: flag it so the table loads the transports
        land_ok = lambda t: not S.TERR[t]["water"]
        amphib = (any(u in S.LAND_UNITS for u in units)
                  and mv["to"] not in S.reachable(mv["from"], 2, land_ok))
        S.apply_move(state, power, units, mv["from"], mv["to"])
        S.note_air_moves(state, power, units, mv["from"], mv["to"],
                         combat=combat_allowed)
        desc = ", ".join(f"{n} {u}" for u, n in units.items())
        attack_tag = (f" — ATTACKING {' and '.join(defenders)} there"
                      if defenders else "")
        if amphib:
            attack_tag += " — AMPHIBIOUS: load onto transport, sail, unload"
        if combat_allowed and defenders and not amphib:
            # remember where this attack came from: retreats may only fall
            # back to one of these origins (landed troops never retreat)
            origins = state.setdefault("attack_origins", {}) \
                           .setdefault(mv["to"], [])
            if mv["from"] not in origins:
                origins.append(mv["from"])
        # unopposed entry into enemy-owned land flips it during combat movement
        if (combat_allowed and not S.TERR[mv["to"]]["water"]
                and not S.hostile_powers_in(state, mv["to"], power)
                and S.is_enemy(power, state["owners"].get(mv["to"], power))
                and any(u in S.LAND_UNITS for u in units)):
            S.capture(state, mv["to"], power)
            lines.append(f"{power} occupies undefended {mv['to']}.")
        lines.append(f"{power}: move {desc} from {mv['from']} to "
                     f"{mv['to']}{attack_tag}.")
        todo.append(f"From {mv['from']}: move {desc} to {mv['to']}"
                    f"{attack_tag}")
    if todo and decision.get("reasoning") and any(
            "transport" in t or "AMPHIBIOUS" in t for t in todo):
        todo.append(f"📝 {power}'s stated plan: {decision['reasoning']}")
    post_actions(todo)        # panel first: move plastic while audio reads
    for line in lines:
        table.speak(line)
    await_done(table, todo)
    return todo


def run_turn(state, players, table, power, glog):
    table.voice = config.PLAYERS[power].get("voice")
    player = players[power]
    ui = UI(table, players, state, glog)

    def checkpoint():
        # keep the live viewer fresh between phases, and honor the pause
        # flag (logs/PAUSE — toggled by the viewer's pause button)
        S.save(state, config.STATE_FILE)
        pause = Path(config.STATE_FILE).parent / "PAUSE"
        if pause.exists():
            table.speak("Game paused.")
            while pause.exists():
                time.sleep(1)
            table.speak("The war resumes.")

    # clean snapshot of the turn's start: if the game dies mid-turn, resume
    # replays from HERE, not from a half-mutated checkpoint
    S.save(state, Path(config.STATE_FILE).parent / "turn_start.json")
    table.turn_buffer = []
    board = S.summary_for_ai(state) + council.brief(state, power)
    checkpoint()
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
    checkpoint()

    # 1. Purchase
    state["phase"] = "purchase"
    checkpoint()
    d = ai_phase(player, state,
                 f"{board}\n\nPURCHASE PHASE. Treasury: {state['ipcs'][power]} "
                 f"IPCs. Unit costs are in your briefing. Research dice cost "
                 f"5. This phase is ONLY buying — movement comes later."
                 + phase_rules("purchase", state, power),
                 PURCHASE_SCHEMA, getattr(player, "purchases", None), glog)
    if d.get("reasoning"):
        table.note(d["reasoning"])
    unknown = []
    for p in d.get("purchases", []):
        cu = S.canon_unit(p.get("unit"))
        if cu:
            p["unit"] = cu
        else:
            unknown.append(str(p.get("unit")))
    if unknown:
        table.speak(f"{power} asked to buy unknown unit(s) "
                    f"{', '.join(unknown)} — skipped; the table referees "
                    f"any correction.")
    cost = sum(S.STATS[p["unit"]]["cost"] * p["quantity"]
               for p in d.get("purchases", []) if p["unit"] in S.STATS)
    research = max(0, int(d.get("research_dice", 0))) if config.WEAPONS_DEVELOPMENT else 0
    cost += research * 5
    if cost > state["ipcs"][power]:
        table.speak(f"{power} overspent ({cost} > {state['ipcs'][power]}); purchase voided.")
    else:
        state["ipcs"][power] -= cost
        bought = ", ".join(f"{p['quantity']} {p['unit']}"
                           for p in d.get("purchases", [])
                           if p["unit"] in S.STATS and p["quantity"])
        line = f"{power} buys {bought}" if bought else f"{power} buys nothing"
        if research:
            line += f" and {research} research dice" if bought else \
                    f" but {research} research dice"
        table.speak(f"{line} — {cost} IPCs spent, "
                    f"{state['ipcs'][power]} left.")
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
    state["attack_origins"] = {}  # fresh each turn; retreats consult this
    state["air_spent"] = {}  # fresh each turn; landing legality consults this
    checkpoint()
    board = S.summary_for_ai(state)
    d = decide_moves(player, state, power, table, glog,
                     f"{board}\n\nCOMBAT MOVEMENT PHASE. Declare ALL of this "
                     f"turn's attacks NOW, in one list — every territory you "
                     f"are assaulting and every unit joining each assault. "
                     f"This is your only combat movement this turn: there is "
                     f"no second wave, and once battles start no more "
                     f"attackers can join. Multi-territory offensives are "
                     f"normal — list every prong. Empty moves list = no "
                     f"attacks. Plan carefully: your full plan is validated "
                     f"before anything is announced at the table."
                     + phase_rules("combat_move", state, power),
                     getattr(player, "combat_moves", None),
                     combat_allowed=True)
    if d.get("reasoning"):
        table.note(d["reasoning"])
    apply_moves(state, table, power, d, combat_allowed=True)

    state["phase"] = "combat"
    checkpoint()
    for terr in sorted(list(state["units"])):
        if S.units_in(state, terr, power) and S.hostile_powers_in(state, terr, power):
            combat.resolve_battle(state, terr, power, ui)
            checkpoint()

    # 4. Noncombat
    state["phase"] = "noncombat"
    checkpoint()
    board = S.summary_for_ai(state)
    d = decide_moves(player, state, power, table, glog,
                     f"{board}\n\nNONCOMBAT MOVEMENT PHASE. Reposition "
                     f"freely; no moves into hostile territory. Plan "
                     f"carefully: your full plan is validated before "
                     f"anything is announced at the table."
                     + S.air_spent_brief(state, power)
                     + phase_rules("noncombat", state, power),
                     getattr(player, "noncombat_moves", None),
                     combat_allowed=False)
    if d.get("reasoning"):
        table.note(d["reasoning"])
    apply_moves(state, table, power, d, combat_allowed=False)

    # 5. Mobilize
    state["phase"] = "mobilize"
    checkpoint()
    pend = state["purchased_pending"].get(power, {})
    if pend:
        d = ai_phase(player, state,
                     f"{S.summary_for_ai(state)}\n\nMOBILIZE PHASE. Place these "
                     f"purchased units at your industrial complexes: "
                     f"{json.dumps(pend)}. Also leave a short note_to_allies."
                     + phase_rules("mobilize", state, power),
                     PLACEMENT_SCHEMA, getattr(player, "placements", None),
                     glog)
        factories = [t for t, by_p in state["units"].items()
                     if by_p.get(power, {}).get("factory")
                     and state["owners"].get(t) == power]
        placed, bounced = {}, {}
        for pl in d.get("placements", []):
            unit = S.canon_unit(pl.get("unit")) or pl.get("unit")
            terr = pl.get("territory")
            if pend.get(unit, 0) > 0 and (terr in factories or unit == "factory"):
                S.add_units(state, terr, power, {unit: 1})
                pend[unit] -= 1
                bucket = placed
            else:
                bucket = bounced
            slot = bucket.setdefault(str(terr), {})
            slot[str(unit)] = slot.get(str(unit), 0) + 1
        todo = [f"Place {', '.join(f'{n} {u}' for u, n in sorted(units.items()))} "
                f"in {terr}" for terr, units in placed.items()]
        post_actions(todo)
        for terr, units in placed.items():
            desc = ", ".join(f"{n} {u}" for u, n in sorted(units.items()))
            table.speak(f"{power} places {desc} in {terr}.")
        await_done(table, todo)
        for terr, units in bounced.items():
            desc = ", ".join(f"{n} {u}" for u, n in sorted(units.items()))
            table.note(f"Placement bounced: {desc} in {terr}.")
        council.record(state, power, d.get("note_to_allies", ""))
        if d.get("reasoning"):
            table.note(d["reasoning"])
        state["purchased_pending"][power] = {u: n for u, n in pend.items() if n > 0}

    # 6. Income
    state["phase"] = "income"
    checkpoint()
    if state["owners"].get(S.CAPITALS[power]) == power:
        gain = S.income(state, power)
        state["ipcs"][power] += gain
        table.speak(f"{power} collects {gain} IPCs.")
    else:
        table.speak(f"{power}'s capital is occupied — no income.")

    # 7. Debrief — comment on how the turn went, spoken before the next power
    state["phase"] = "debrief"
    checkpoint()
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
    ts_path = Path(config.STATE_FILE).parent / "turn_start.json"
    if not fresh and ts_path.exists():
        ts = S.load(ts_path)
        if (ts.get("round"), ts.get("turn")) == \
                (state.get("round"), state.get("turn")):
            state = ts  # interrupted mid-turn: replay from the clean start
    if "game_id" not in state:
        state["game_id"] = time.strftime("%Y%m%d-%H%M%S")
    for stale in ("dice_request.json", "dice_response.json"):
        (Path(config.STATE_FILE).parent / stale).unlink(missing_ok=True)
    players = build_players(all_stub="--stub" in sys.argv)
    if fresh:  # a new game gets clean table surfaces; the old game's
        # transcript/minds/actions live on in its corpus JSONL
        Path(config.TRANSCRIPT).parent.mkdir(parents=True, exist_ok=True)
        Path(config.TRANSCRIPT).write_text("")
        for leftover in ("PAUSE", "actions.json", "turn_start.json"):
            p = Path(config.STATE_FILE).parent / leftover
            if p.exists():
                p.unlink()
        minds = Path(config.STATE_FILE).parent / "minds"
        for f in (minds.glob("*.json") if minds.exists() else []):
            f.unlink()
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
            # brief every OTHER commander on what just happened, so they
            # carry the whole game's story into their own next turn
            report = (f"TURN REPORT — {power} has finished their turn:\n"
                      + "\n".join(table.turn_buffer)
                      + "\n\nIPC treasuries: "
                      + ", ".join(f"{p}={state['ipcs'].get(p, 0)}"
                                  for p in S.TURN_ORDER)
                      + "\n(For your situational awareness while you wait. "
                        "Do not reply; you will be prompted on your turn.)")
            for other, pl in players.items():
                if other != power and getattr(pl, "history", None):
                    pl.history.append({"role": "user", "content": report})
                    dump_mind(pl)
            # advance the pointer so a resume starts with the NEXT power
            # instead of replaying the turn that just finished
            nxt = order.index(power) + 1
            if nxt < len(order):
                state["turn"] = order[nxt]
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
        S.save(state, config.STATE_FILE)
        table.speak(f"Round {state['round']} begins.")


if __name__ == "__main__":
    main()
