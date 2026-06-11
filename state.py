"""Game state: load/save, income, movement legality, victory checks."""
import copy
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAP = json.loads((ROOT / "data" / "map_classic.json").read_text())
TERR = MAP["territories"]
STATS = MAP["unit_stats"]
SIDES = MAP["sides"]
TURN_ORDER = MAP["turn_order"]
CAPITALS = MAP["capitals"]

LAND_UNITS = {"infantry", "armour", "aaGun"}
AIR_UNITS = {"fighter", "bomber"}
SEA_UNITS = {"transport", "submarine", "carrier", "battleship"}


def new_game():
    setup = json.loads((ROOT / "data" / "setup_classic.json").read_text())
    return {
        "round": 1,
        "turn": TURN_ORDER[0],
        "phase": "purchase",
        "ipcs": dict(setup["ipcs"]),
        "owners": dict(setup["owners"]),
        "units": copy.deepcopy(setup["units"]),
        "purchased_pending": {},
        "tech": {p: [] for p in TURN_ORDER},
        "council_notes": {"axis": [], "allies": []},
        "eliminated": [],
    }


def load(path):
    return json.loads(Path(path).read_text())


def save(state, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")  # atomic: the live viewer reads this file
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    os.replace(tmp, p)


def units_in(state, terr, power=None):
    by_power = state["units"].get(terr, {})
    if power:
        return dict(by_power.get(power, {}))
    return {p: dict(u) for p, u in by_power.items()}


def add_units(state, terr, power, units):
    slot = state["units"].setdefault(terr, {}).setdefault(power, {})
    for u, n in units.items():
        slot[u] = slot.get(u, 0) + n


def remove_units(state, terr, power, units):
    """Remove units; raises ValueError if they aren't there."""
    slot = state["units"].get(terr, {}).get(power, {})
    for u, n in units.items():
        if slot.get(u, 0) < n:
            raise ValueError(f"{power} has {slot.get(u, 0)} {u} in {terr}, tried to remove {n}")
        slot[u] -= n
        if slot[u] == 0:
            del slot[u]
    if not slot:
        state["units"].get(terr, {}).pop(power, None)
    if not state["units"].get(terr):
        state["units"].pop(terr, None)


def income(state, power):
    return sum(TERR[t]["ipc_value"] for t, o in state["owners"].items() if o == power)


def side_income(state, side):
    return sum(income(state, p) for p in TURN_ORDER
               if SIDES[p] == side and p not in state["eliminated"])


def is_enemy(power, other):
    return SIDES[power] != SIDES[other]


def hostile_powers_in(state, terr, power):
    return [p for p in units_in(state, terr) if is_enemy(power, p)]


def reachable(start, max_moves, allowed, transit=None):
    """Territories within max_moves steps of start, where allowed(t) gates
    every territory entered, and transit(t) additionally gates passing
    THROUGH t (enter-and-stop is always fine — that's an attack). Returns
    {territory: distance}."""
    seen = {start: 0}
    frontier = [start]
    for dist in range(1, max_moves + 1):
        nxt = []
        for t in frontier:
            for adj in TERR[t]["adjacent"]:
                if adj not in seen and allowed(adj):
                    seen[adj] = dist
                    if transit is None or transit(adj):
                        nxt.append(adj)
        frontier = nxt
    seen.pop(start, None)
    return seen


def air_movement(state, power, unit):
    mv = STATS[unit]["movement"]
    if "long_range_aircraft" in state.get("tech", {}).get(power, []):
        mv += 2
    return mv


def air_landing_issue(state, power, unit, src, dst):
    """Classic air rule: an aircraft's combat move must leave enough
    movement to reach a legal landing spot during noncombat — friendly
    land, or (fighters) a sea zone holding a friendly carrier. Checked
    against territory ownership as it stands now; exotic carrier plans
    are the table referee's call."""
    mv = air_movement(state, power, unit)
    fly = lambda t: True
    d_in = reachable(src, mv, fly).get(dst)
    if d_in is None:
        return None  # plain range failure; reported by the caller
    remaining = mv - d_in
    side = SIDES[power]

    def can_land(t):
        if TERR[t]["water"]:
            return unit == "fighter" and any(
                SIDES.get(p) == side and u.get("carrier")
                for p, u in units_in(state, t).items())
        owner = state["owners"].get(t)
        return owner is not None and SIDES[owner] == side

    if remaining > 0 and any(can_land(t)
                             for t in reachable(dst, remaining, fly)):
        return None
    return (f"{unit} would reach {dst} with {remaining} movement left and "
            f"no friendly landing spot in range — aircraft must end the "
            f"turn landed in friendly territory (fighters may use a "
            f"friendly carrier). Pick a closer target or skip this strike")


_UNIT_ALIASES = {
    # The AIs speak English; the board speaks STATS keys. Map the common
    # names so a "tank" or an "industrial complex" is never silently dropped.
    "factory": ["industrial complex", "industrialcomplex", "complex", "ic",
                "industrial"],
    "armour": ["armor", "tank", "tanks"],
    "aaGun": ["aa gun", "aagun", "aa", "antiaircraft", "anti-aircraft gun",
              "antiaircraft gun"],
    "submarine": ["sub", "subs"],
    "carrier": ["aircraft carrier"],
    "infantry": ["inf"],
}
_CANON = {}
for _k, _names in _UNIT_ALIASES.items():
    for _n in _names:
        _CANON[_n] = _k


def canon_unit(name):
    """Canonical STATS key for a unit name an AI emitted, or None.
    Case/space/underscore-insensitive, tolerates a trailing plural s."""
    if not isinstance(name, str):
        return None
    raw = name.strip()
    if raw in STATS:
        return raw
    low = " ".join(raw.lower().replace("_", " ").replace("-", " ").split())
    for cand in (low, low[:-1] if low.endswith("s") else low):
        if cand in STATS:
            return cand
        if cand in _CANON:
            return _CANON[cand]
        for k in STATS:
            if cand == k.lower():
                return k
    return None


def air_spent_pool(state, src, power, unit):
    """Remaining-movement entries for `unit` aircraft sitting in src that
    flew a combat move this turn. Casualties are unidentified, so be lenient:
    if fewer aircraft remain than entries, assume the survivors are the ones
    with the MOST movement left (keep the largest entries)."""
    spent = (state.get("air_spent", {}).get(src, {})
             .get(power, {}).get(unit) or [])
    total_here = units_in(state, src, power).get(unit, 0)
    if len(spent) > total_here:
        spent = sorted(spent, reverse=True)[:total_here]
    return spent


def note_air_moves(state, power, units, src, dst, combat):
    """Bookkeeping after an applied move. Combat phase: record each air
    unit's REMAINING movement at its destination — leaving home counts as
    the first move, sea zone or not, and what was spent flying to the fight
    constrains where it may land. Noncombat phase: consume entries as the
    aircraft fly off to land (smallest sufficient entry first; movers beyond
    the recorded list are fresh full-movement aircraft)."""
    fly = lambda t: True
    for u, n in units.items():
        if u not in AIR_UNITS or not n:
            continue
        mv = air_movement(state, power, u)
        d = reachable(src, mv, fly).get(dst)
        if d is None:
            continue
        if combat:
            pool = (state.setdefault("air_spent", {}).setdefault(dst, {})
                    .setdefault(power, {}).setdefault(u, []))
            pool += [mv - d] * n
        else:
            pool = air_spent_pool(state, src, power, u)
            usable = sorted([r for r in pool if r >= d])
            keep = list(pool)
            for r in usable[:n]:
                keep.remove(r)
            src_map = state.get("air_spent", {}).get(src, {}).get(power, {})
            if u in src_map:
                if keep:
                    src_map[u] = keep
                else:
                    del src_map[u]


def air_spent_brief(state, power):
    """One-line-per-group reminder for the noncombat prompt: aircraft that
    flew combat this turn and how much movement each has left to land."""
    lines = []
    for terr, by_power in sorted(state.get("air_spent", {}).items()):
        for u in sorted(by_power.get(power, {})):
            pool = air_spent_pool(state, terr, power, u)
            if pool:
                lines.append(f"- {terr}: {len(pool)} {u} with "
                             f"{', '.join(str(r) for r in sorted(pool))} "
                             f"movement left to land")
    if not lines:
        return ""
    return ("\nAIRCRAFT THAT FLEW COMBAT THIS TURN (movement already spent "
            "counts — they must land within what remains):\n"
            + "\n".join(lines))


def retreat_options(state, power, terr):
    """Legal retreat destinations: ADJACENT spaces of the battle that the
    attack came through. A multi-zone naval attack retreats one space back
    along its path (the pass-through hop), never the full distance home."""
    adj = TERR[terr]["adjacent"]
    opts = set()
    for origin in state.get("attack_origins", {}).get(terr, []):
        if origin in adj:
            if not hostile_powers_in(state, origin, power):
                opts.add(origin)
        else:  # 2-space move: the way back is the intermediate hop
            for mid in adj:
                if mid in TERR[origin]["adjacent"] \
                        and TERR[mid]["water"] == TERR[origin]["water"] \
                        and not hostile_powers_in(state, mid, power):
                    opts.add(mid)
    return sorted(opts)


def amphibious_ok(state, power, src, dst):
    """Permissive ferry check for land units crossing water: both ends are
    land with coasts, a sea route of <=2 zones links them, and a friendly
    transport is on or near that route. Loading, capacity, and the exact
    legs are the table referee's domain — the engine just refuses fantasy
    crossings with no transport anywhere nearby."""
    if TERR[src]["water"] or TERR[dst]["water"]:
        return False
    water = lambda t: TERR[t]["water"]
    src_zones = [z for z in TERR[src]["adjacent"] if water(z)]
    dst_zones = set(z for z in TERR[dst]["adjacent"] if water(z))
    if not src_zones or not dst_zones:
        return False
    has_transport = lambda z: units_in(state, z, power).get("transport")
    for z in src_zones:
        route = {z: 0}
        route.update(reachable(z, 2, water))
        if dst_zones & set(route):
            if any(has_transport(t) for t in route) or \
                    any(has_transport(t) for t in dst_zones):
                return True
    return False


def check_move(state, power, units, src, dst, combat_air_landing=False):
    """Best-effort legality check. Returns None if OK, else a reason string.
    Deliberately permissive on the hard parts (amphibious chains, canals,
    neutrals) — the table referees those. With combat_air_landing=True,
    air units must also keep enough movement to land afterward."""
    if src not in TERR or dst not in TERR:
        return f"unknown territory: {src if src not in TERR else dst}"
    have = units_in(state, src, power)
    for u, n in units.items():
        if u not in STATS:
            return f"unknown unit type {u}"
        if have.get(u, 0) < n:
            return f"only {have.get(u, 0)} {u} in {src}"
    # ships and land units stop when they enter an enemy-occupied space —
    # no passing through (rulebook: a submarine's first zone in a 2-zone
    # move "must be unoccupied... or occupied by units of your alliance").
    # Air flies over anything.
    clear = lambda t: not hostile_powers_in(state, t, power)
    for u, n in units.items():
        mv = STATS[u]["movement"]
        transit = clear
        if u in LAND_UNITS:
            ok = lambda t: not TERR[t]["water"]
        elif u in SEA_UNITS:
            ok = lambda t: TERR[t]["water"]
        else:  # air
            ok = lambda t: True
            transit = None
            mv = air_movement(state, power, u)
        if combat_air_landing and u == "aaGun" \
                and hostile_powers_in(state, dst, power):
            return "AA guns can never attack or enter enemy-held spaces"
        if dst not in reachable(src, mv, ok, transit):
            if u in LAND_UNITS and amphibious_ok(state, power, src, dst):
                continue  # ferried by transport; table handles the legs
            blocked = (mv > 1 and transit is not None
                       and dst in reachable(src, mv, ok))
            return (f"{u} cannot reach {dst} from {src}: the path passes "
                    f"through an enemy-occupied space — units must stop "
                    f"and fight where they meet the enemy" if blocked else
                    f"{u} cannot reach {dst} from {src} (move {mv}). If "
                    f"this was meant as an amphibious move, you need a "
                    f"transport positioned on the sea route")
        if combat_air_landing and u in AIR_UNITS:
            issue = air_landing_issue(state, power, u, src, dst)
            if issue:
                return issue
        if not combat_air_landing and u in AIR_UNITS:
            # Landing flight: movement spent on the combat flight counts.
            # A fighter that flew 3 to the fight has only 1 left — Gibraltar,
            # not the long way home.
            spent = air_spent_pool(state, src, power, u)
            if spent:
                d = reachable(src, mv, ok).get(dst, mv)
                fresh = max(0, units_in(state, src, power).get(u, 0) - len(spent))
                capacity = sum(1 for r in spent if r >= d) + fresh
                if n > capacity:
                    return (f"only {capacity} {u} in {src} can fly {d} to "
                            f"{dst}: combat movement already spent — "
                            f"remaining movement is "
                            f"{', '.join(str(r) for r in sorted(spent))}. "
                            f"Land the rest within their remaining range")
    return None


def apply_move(state, power, units, src, dst):
    remove_units(state, src, power, units)
    add_units(state, dst, power, units)


def capture(state, terr, power):
    """Land capture: flips ownership, IPC loot on capital capture."""
    prev = state["owners"].get(terr)
    if prev is None:
        return
    state["owners"][terr] = power
    for cap_power, cap_terr in CAPITALS.items():
        if cap_terr == terr and cap_power != power:
            loot = state["ipcs"].get(cap_power, 0)
            state["ipcs"][power] = state["ipcs"].get(power, 0) + loot
            state["ipcs"][cap_power] = 0


def victory(state):
    """Returns (winner_side, reason) or None. Capitals: a side wins when it
    controls both enemy capitals. Economic victory checked by caller at end
    of round (needs the toggle/threshold from config)."""
    axis_caps = [CAPITALS["germany"], CAPITALS["japan"]]
    allied_caps = [CAPITALS["ussr"], CAPITALS["uk"], CAPITALS["usa"]]
    if all(SIDES[state["owners"][c]] == "allies" for c in axis_caps):
        return ("allies", "both Axis capitals captured")
    if sum(1 for c in allied_caps if SIDES[state["owners"][c]] == "axis") >= 2:
        return ("axis", "two Allied capitals captured")
    return None


def summary_for_ai(state):
    """Compact, deterministic text rendering of the whole board."""
    lines = [f"Round {state['round']}, {state['turn']} to play, phase {state['phase']}."]
    lines.append("IPC treasuries: " + ", ".join(
        f"{p}={state['ipcs'].get(p, 0)}" for p in TURN_ORDER))
    lines.append("Income per round: " + ", ".join(
        f"{p}={income(state, p)}" for p in TURN_ORDER))
    for t in sorted(TERR):
        occupants = state["units"].get(t, {})
        owner = state["owners"].get(t)
        if not occupants and owner is None:
            continue
        bits = []
        if owner:
            bits.append(f"owner={owner}" + (f" ipc={TERR[t]['ipc_value']}" if TERR[t]["ipc_value"] else ""))
        for p, us in sorted(occupants.items()):
            inner = ",".join(f"{n} {u}" for u, n in sorted(us.items()))
            bits.append(f"{p}: {inner}")
        lines.append(f"- {t}: " + "; ".join(bits))
    return "\n".join(lines)
