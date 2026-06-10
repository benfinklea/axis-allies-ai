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
    p.write_text(json.dumps(state, indent=1, sort_keys=True))


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


def reachable(start, max_moves, allowed):
    """Territories within max_moves steps of start, where allowed(t) gates
    every intermediate AND final territory. Returns {territory: distance}."""
    seen = {start: 0}
    frontier = [start]
    for dist in range(1, max_moves + 1):
        nxt = []
        for t in frontier:
            for adj in TERR[t]["adjacent"]:
                if adj not in seen and allowed(adj):
                    seen[adj] = dist
                    nxt.append(adj)
        frontier = nxt
    seen.pop(start, None)
    return seen


def check_move(state, power, units, src, dst):
    """Best-effort legality check. Returns None if OK, else a reason string.
    Deliberately permissive on the hard parts (amphibious chains, canals,
    neutrals) — the table referees those."""
    if src not in TERR or dst not in TERR:
        return f"unknown territory: {src if src not in TERR else dst}"
    have = units_in(state, src, power)
    for u, n in units.items():
        if u not in STATS:
            return f"unknown unit type {u}"
        if have.get(u, 0) < n:
            return f"only {have.get(u, 0)} {u} in {src}"
    for u, n in units.items():
        mv = STATS[u]["movement"]
        if u in LAND_UNITS:
            ok = lambda t: not TERR[t]["water"]
        elif u in SEA_UNITS:
            ok = lambda t: TERR[t]["water"]
        else:  # air
            ok = lambda t: True
        if dst not in reachable(src, mv, ok):
            return f"{u} cannot reach {dst} from {src} (move {mv})"
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
