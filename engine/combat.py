"""Battle resolution for classic A&A: rounds of fire, AI-chosen casualties,
press/retreat, capture. Special cases kept minimal — AA pre-fire and sub
surprise strike are in; anything weirder gets a referee prompt."""
import state as S
from engine import dice


def _hits(rolls, target):
    return sum(1 for r in rolls if r <= target)


def _combatants(units):
    """AA guns and factories are never combat casualties — the rulebook:
    'AA guns are never destroyed'; both transfer with the territory."""
    return {u: n for u, n in units.items()
            if u not in ("aaGun", "factory") and n}


def _firepower(units, role, tech=()):
    """[(unit, count, to-hit)] for attack/defense, with classic tech bumps."""
    out = []
    for u, n in sorted(units.items()):
        stat = S.STATS[u]["attack" if role == "attack" else "defense"]
        if u == "submarine" and "super_subs" in tech and role == "attack":
            stat = 3
        if u == "fighter" and "jet_power" in tech and role == "defense":
            stat = 5
        if stat > 0 and u not in ("factory", "aaGun"):
            out.append((u, n, stat))
    return out


def resolve_battle(state, terr, attacker, ui):
    """Fight until one side is gone or the attacker retreats.
    ui provides: speak(text), ask_casualties(power, units, hits, terr),
    ask_press(power, terr), referee(question)."""
    defenders = S.hostile_powers_in(state, terr, attacker)
    ui.speak(f"Battle in {terr}: {attacker} attacks {', '.join(defenders)}.")

    atk_units = S.units_in(state, terr, attacker)
    # AA fire: one die per attacking air unit, before anything else
    aa_owner = next((p for p in defenders if S.units_in(state, terr, p).get("aaGun")), None)
    air = {u: n for u, n in atk_units.items() if u in S.AIR_UNITS}
    if aa_owner and air and not S.TERR[terr]["water"]:
        n_air = sum(air.values())
        rolls = dice.battle(
            [{"id": "aa", "side": "defender", "power": aa_owner,
              "unit": "aaGun", "count": n_air, "target": 1}],
            {"territory": terr, "round": 0, "attacker": attacker,
             "defenders": defenders,
             "note": f"AA fire vs {n_air} aircraft (one die each)"},
            ui.dice_mode, ui.speak, ui.dice_log)["aa"]
        shot_down = _hits(rolls, 1)
        if shot_down:
            lost = ui.ask_casualties(attacker, air, shot_down, terr, aa_fire=True)
            S.remove_units(state, terr, attacker, lost)
            ui.speak(f"AA fire downs {shot_down} aircraft.")
            ui.table_removals(terr, [
                f"Remove {attacker} {n} {u} from {terr} (AA fire)"
                for u, n in lost.items()])
            atk_units = S.units_in(state, terr, attacker)

    rnd = 0
    while True:
        rnd += 1
        atk_units = _combatants(S.units_in(state, terr, attacker))
        def_by_power = {p: _combatants(S.units_in(state, terr, p))
                        for p in defenders}
        def_by_power = {p: u for p, u in def_by_power.items() if u}
        if not any(u for u in atk_units.values() if u):
            ui.speak(f"{attacker}'s attack on {terr} is wiped out.")
            return "defender"
        if not def_by_power:
            break  # attacker holds the field (AA guns don't hold it)

        ui.speak(f"{terr}, combat round {rnd}.")
        tech_a = state["tech"].get(attacker, [])

        # Sub surprise strike — classic rule: the surprise attack happens ONCE,
        # at the start of the FIRST round of a sea battle only. Casualties it
        # causes are removed immediately and don't fire back. In every later
        # round submarines fire on the normal battle board like any other ship
        # (the fire-first-every-round variant is Revised 2004, not classic).
        pre_removed = {}
        subs = atk_units.get("submarine", 0)
        if rnd == 1 and subs:
            sub_target = 3 if "super_subs" in tech_a else 2
            rolls = dice.battle(
                [{"id": "sub", "side": "attacker", "power": attacker,
                  "unit": "submarine", "count": subs, "target": sub_target}],
                {"territory": terr, "round": rnd, "attacker": attacker,
                 "defenders": list(def_by_power),
                 "note": "submarine surprise strike"},
                ui.dice_mode, ui.speak, ui.dice_log)["sub"]
            h = _hits(rolls, sub_target)
            if h:
                for p in list(def_by_power):
                    sea_units = {u: n for u, n in def_by_power[p].items() if u in S.SEA_UNITS}
                    if sea_units and h:
                        lost = ui.ask_casualties(p, sea_units, min(h, sum(sea_units.values())), terr)
                        S.remove_units(state, terr, p, lost)
                        h -= sum(lost.values())
                        pre_removed[p] = lost
                ui.speak(f"Surprise strike sinks: {pre_removed}")
                def_by_power = {p: u for p, u in
                                ((p, S.units_in(state, terr, p)) for p in defenders) if u}

        # One battle board per round: every firing group, both sides, at once.
        # Attacking subs sit out the round-1 board (they already made their
        # surprise strike); from round 2 on they fire here like everyone else.
        groups = [{"id": f"a:{u}", "side": "attacker", "power": attacker,
                   "unit": u, "count": n, "target": t}
                  for u, n, t in _firepower(
                      {u: n for u, n in atk_units.items()
                       if not (rnd == 1 and u == "submarine")}, "attack", tech_a)]
        for p, units in def_by_power.items():
            groups += [{"id": f"d:{p}:{u}", "side": "defender", "power": p,
                        "unit": u, "count": n, "target": t}
                       for u, n, t in _firepower(units, "defense",
                                                 state["tech"].get(p, []))]
        if not groups:
            ui.speak(f"Neither side in {terr} can fire — the table referees "
                     f"this standoff; attacker withdraws.")
            return "stalemate"
        rolls = dice.battle(groups,
                            {"territory": terr, "round": rnd,
                             "attacker": attacker,
                             "defenders": list(def_by_power)},
                            ui.dice_mode, ui.speak, ui.dice_log)
        atk_hits = sum(_hits(rolls[g["id"]], g["target"])
                       for g in groups if g["side"] == "attacker")
        def_hits = sum(_hits(rolls[g["id"]], g["target"])
                       for g in groups if g["side"] == "defender")

        # Casualties — AI-chosen, simultaneous removal
        removals = [f"Remove {p} {n} {u} from {terr} (surprise strike)"
                    for p, lost in pre_removed.items()
                    for u, n in lost.items()]
        if atk_hits:
            remaining = atk_hits
            for p in list(def_by_power):
                pool = def_by_power[p]
                take = min(remaining, sum(pool.values()))
                if take:
                    lost = ui.ask_casualties(p, pool, take, terr)
                    S.remove_units(state, terr, p, lost)
                    remaining -= sum(lost.values())
                    removals += [f"Remove {p} {n} {u} from {terr}"
                                 for u, n in lost.items()]
        if def_hits:
            pool = _combatants(S.units_in(state, terr, attacker))
            take = min(def_hits, sum(pool.values()))
            if take:
                lost = ui.ask_casualties(attacker, pool, take, terr)
                S.remove_units(state, terr, attacker, lost)
                removals += [f"Remove {attacker} {n} {u} from {terr}"
                             for u, n in lost.items()]
        if removals:
            ui.table_removals(terr, removals)

        # Classic special: surviving DEFENDING submarines may withdraw to an
        # adjacent friendly/unoccupied sea zone after the exchange. (A full
        # attacking-force retreat is the press question below; partial
        # attacker sub-withdrawal stays a referee call.)
        if S.units_in(state, terr, attacker):
            for p in list(S.hostile_powers_in(state, terr, attacker)):
                n_subs = S.units_in(state, terr, p).get("submarine", 0)
                dests = [z for z in S.TERR[terr]["adjacent"]
                         if S.TERR[z]["water"]
                         and not S.hostile_powers_in(state, z, p)]
                if not n_subs or not dests:
                    continue
                choice = ui.ask_sub_withdraw(p, terr, n_subs, dests)
                dest = choice.get("retreat_to")
                if choice.get("action") == "retreat" and dest in dests:
                    S.apply_move(state, p, {"submarine": n_subs}, terr, dest)
                    ui.speak(f"{p}'s submarines withdraw from {terr} "
                             f"to {dest}.")

        defenders = [p for p in S.hostile_powers_in(state, terr, attacker)
                     if _combatants(S.units_in(state, terr, p))]
        if defenders and S.units_in(state, terr, attacker):
            choice = ui.ask_press(attacker, terr)
            if choice.get("action") == "retreat":
                dest = choice.get("retreat_to")
                origins = [o for o in
                           state.get("attack_origins", {}).get(terr, [])
                           if not S.hostile_powers_in(state, o, attacker)]
                if dest in origins:
                    S.apply_move(state, attacker,
                                 S.units_in(state, terr, attacker), terr, dest)
                    ui.speak(f"{attacker} retreats from {terr} to {dest}.")
                    return "retreat"
                ui.speak(f"Retreat to {dest} is illegal — attackers may "
                         f"only fall back the way they came; fighting on.")

        if not defenders:
            break

    # Attacker took the territory (land only flips ownership; needs a land unit)
    if not S.TERR[terr]["water"]:
        has_land = any(u in S.LAND_UNITS for u in S.units_in(state, terr, attacker))
        if has_land:
            S.capture(state, terr, attacker)
            # AA guns and factories are never destroyed: they transfer
            captured = []
            for p in list(state["units"].get(terr, {})):
                if S.is_enemy(attacker, p):
                    leftovers = S.units_in(state, terr, p)
                    if leftovers:
                        S.remove_units(state, terr, p, leftovers)
                        S.add_units(state, terr, attacker, leftovers)
                        captured += [f"{n} {u}" for u, n in leftovers.items()]
            ui.speak(f"{attacker} captures {terr}!"
                     + (f" Captured intact: {', '.join(captured)}."
                        if captured else ""))
            ui.table_removals(terr, [
                f"{attacker} captures {terr}: move the surviving attackers "
                f"in and flip its control marker to {attacker}"
                + (f" (the {', '.join(captured)} now belong to {attacker} "
                   f"— leave them in place)" if captured else "")])
        else:
            ui.speak(f"{attacker} wins the air battle over {terr} but cannot "
                     f"capture without land units.")
    else:
        ui.speak(f"{attacker} controls the sea zone {terr}.")
    return "attacker"
