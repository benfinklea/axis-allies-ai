"""Battle resolution for classic A&A: rounds of fire, AI-chosen casualties,
press/retreat, capture. Special cases kept minimal — AA pre-fire and sub
surprise strike are in; anything weirder gets a referee prompt."""
import state as S
from engine import dice


def _hits(rolls, target):
    return sum(1 for r in rolls if r <= target)


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
        rolls = dice.roll(n_air, f"{aa_owner} AA fire vs {n_air} aircraft",
                          ui.dice_mode, ui.speak, ui.dice_log)
        shot_down = _hits(rolls, 1)
        if shot_down:
            lost = ui.ask_casualties(attacker, air, shot_down, terr, aa_fire=True)
            S.remove_units(state, terr, attacker, lost)
            ui.speak(f"AA fire downs {shot_down} aircraft.")
            atk_units = S.units_in(state, terr, attacker)

    rnd = 0
    while True:
        rnd += 1
        atk_units = S.units_in(state, terr, attacker)
        def_by_power = {p: S.units_in(state, terr, p) for p in defenders}
        def_by_power = {p: u for p, u in def_by_power.items() if u}
        if not any(u for u in atk_units.values() if u):
            ui.speak(f"{attacker}'s attack on {terr} is wiped out.")
            return "defender"
        if not def_by_power:
            break  # attacker holds the field

        ui.speak(f"{terr}, combat round {rnd}.")
        tech_a = state["tech"].get(attacker, [])

        # Sub surprise strike (classic: attacking subs fire first; casualties
        # they cause don't fire back this round)
        pre_removed = {}
        subs = atk_units.get("submarine", 0)
        if subs and "submarine" not in pre_removed:
            sub_target = 3 if "super_subs" in tech_a else 2
            rolls = dice.roll(subs, f"{attacker} submarine surprise strike",
                              ui.dice_mode, ui.speak, ui.dice_log)
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

        # Attacker fire (subs already fired)
        atk_fire = _firepower({u: n for u, n in atk_units.items() if u != "submarine"},
                              "attack", tech_a)
        atk_hits = 0
        for u, n, target in atk_fire:
            rolls = dice.roll(n, f"{attacker} {n} {u} (hit on {target} or less)",
                              ui.dice_mode, ui.speak, ui.dice_log)
            atk_hits += _hits(rolls, target)

        # Defender fire (all defenders, all units, including subs at defense)
        def_hits = 0
        for p, units in def_by_power.items():
            for u, n, target in _firepower(units, "defense", state["tech"].get(p, [])):
                rolls = dice.roll(n, f"{p} {n} {u} defending (hit on {target} or less)",
                                  ui.dice_mode, ui.speak, ui.dice_log)
                def_hits += _hits(rolls, target)

        # Casualties — AI-chosen, simultaneous removal
        if atk_hits:
            remaining = atk_hits
            for p in list(def_by_power):
                pool = def_by_power[p]
                take = min(remaining, sum(pool.values()))
                if take:
                    lost = ui.ask_casualties(p, pool, take, terr)
                    S.remove_units(state, terr, p, lost)
                    remaining -= sum(lost.values())
        if def_hits:
            pool = S.units_in(state, terr, attacker)
            take = min(def_hits, sum(pool.values()))
            if take:
                lost = ui.ask_casualties(attacker, pool, take, terr)
                S.remove_units(state, terr, attacker, lost)

        defenders = S.hostile_powers_in(state, terr, attacker)
        if defenders and S.units_in(state, terr, attacker):
            choice = ui.ask_press(attacker, terr)
            if choice.get("action") == "retreat":
                dest = choice.get("retreat_to")
                err = dest and S.check_move(state, attacker,
                                            S.units_in(state, terr, attacker), terr, dest)
                if dest and not err:
                    S.apply_move(state, attacker,
                                 S.units_in(state, terr, attacker), terr, dest)
                    ui.speak(f"{attacker} retreats from {terr} to {dest}.")
                    return "retreat"
                ui.speak("Retreat destination invalid; fighting on.")

        if not defenders:
            break

    # Attacker took the territory (land only flips ownership; needs a land unit)
    if not S.TERR[terr]["water"]:
        has_land = any(u in S.LAND_UNITS for u in S.units_in(state, terr, attacker))
        if has_land:
            S.capture(state, terr, attacker)
            ui.speak(f"{attacker} captures {terr}!")
        else:
            ui.speak(f"{attacker} wins the air battle over {terr} but cannot "
                     f"capture without land units.")
    else:
        ui.speak(f"{attacker} controls the sea zone {terr}.")
    return "attacker"
