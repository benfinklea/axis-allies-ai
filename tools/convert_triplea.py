#!/usr/bin/env python3
"""Convert TripleA's classic.xml into the orchestrator's data files.

Source: https://github.com/triplea-maps/world_war_ii_classic (classic.xml is
the 2nd-edition game). Produces:

  data/map_classic.json    — territories, adjacency, IPC values, unit stats
  data/setup_classic.json  — starting owners, units, and IPC treasuries

Usage:
  python3 tools/convert_triplea.py path/to/classic.xml
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# TripleA player names -> our power ids
POWER = {
    "Russians": "ussr",
    "Germans": "germany",
    "British": "uk",
    "Japanese": "japan",
    "Americans": "usa",
}

# Classic 2nd edition purchasable units only (3rd-edition variant units like
# artillery and destroyer are defined in the XML but never placed; exclude).
CLASSIC_UNITS = [
    "infantry", "armour", "fighter", "bomber", "transport",
    "submarine", "carrier", "battleship", "aaGun", "factory",
]

SIDES = {"ussr": "allies", "uk": "allies", "usa": "allies",
         "germany": "axis", "japan": "axis"}


def options(att):
    return {o.get("name"): o.get("value") for o in att.findall("option")}


def main(xml_path: str) -> None:
    root = ET.parse(xml_path).getroot()
    out_dir = Path(__file__).resolve().parent.parent / "data"

    territories = {}
    for t in root.iter("territory"):
        territories[t.get("name")] = {
            "water": t.get("water") == "true",
            "ipc_value": 0,
            "adjacent": [],
        }
    for c in root.iter("connection"):
        a, b = c.get("t1"), c.get("t2")
        territories[a]["adjacent"].append(b)
        territories[b]["adjacent"].append(a)

    capitals = {}  # power -> territory
    factories_at_start = []
    for att in root.iter("attachment"):
        if att.get("name") != "territoryAttachment":
            continue
        name = att.get("attachTo")
        opts = options(att)
        if name in territories:
            territories[name]["ipc_value"] = int(opts.get("production", 0))
            if "capital" in opts:
                capitals[POWER[opts["capital"]]] = name

    unit_stats = {}
    for att in root.iter("attachment"):
        if att.get("name") != "unitAttachment":
            continue
        unit = att.get("attachTo")
        if unit not in CLASSIC_UNITS:
            continue
        opts = options(att)
        unit_stats[unit] = {
            "attack": int(opts.get("attack", 0)),
            "defense": int(opts.get("defense", 0)),
            "movement": int(opts.get("movement", 0)),
            "two_hit": opts.get("isTwoHit") == "true",
            "is_sub": opts.get("isSub") == "true",
            "is_air": opts.get("isAir") == "true",
            "is_sea": opts.get("isSea") == "true",
            "transport_capacity": int(opts.get("transportCapacity", -1)),
            "transport_cost": int(opts.get("transportCost", -1)),
            "carrier_capacity": int(opts.get("carrierCapacity", -1)),
            "carrier_cost": int(opts.get("carrierCost", -1)),
        }

    costs = {}
    for rule in root.iter("productionRule"):
        cost = rule.find("cost")
        result = rule.find("result")
        unit = result.get("resourceOrUnit")
        # plain buy rules only (skip IndustrialTechnology discounted variants)
        if unit in CLASSIC_UNITS and rule.get("name", "").lower() == f"buy{unit}".lower():
            costs[unit] = int(cost.get("quantity"))
    for unit in CLASSIC_UNITS:
        unit_stats.setdefault(unit, {})["cost"] = costs.get(unit)

    owners = {}
    for to in root.iter("territoryOwner"):
        owners[to.get("territory")] = POWER[to.get("owner")]

    placements = {}
    for up in root.iter("unitPlacement"):
        terr = up.get("territory")
        unit = up.get("unitType")
        qty = int(up.get("quantity"))
        owner = POWER.get(up.get("owner")) or owners.get(terr)
        if unit == "factory":
            factories_at_start.append(terr)
        if owner is None:  # neutral-held oddity; skip
            continue
        placements.setdefault(terr, {}).setdefault(owner, {})
        placements[terr][owner][unit] = placements[terr][owner].get(unit, 0) + qty

    treasuries = {}
    for rg in root.iter("resourceGiven"):
        treasuries[POWER[rg.get("player")]] = int(rg.get("quantity"))

    map_data = {
        "source": "TripleA world_war_ii_classic classic.xml (2nd edition)",
        "territories": territories,
        "capitals": capitals,
        "unit_stats": unit_stats,
        "turn_order": ["ussr", "germany", "uk", "japan", "usa"],
        "sides": SIDES,
    }
    setup = {
        "owners": owners,
        "units": placements,
        "ipcs": treasuries,
        "factories": sorted(set(factories_at_start)),
    }

    (out_dir / "map_classic.json").write_text(json.dumps(map_data, indent=1, sort_keys=True))
    (out_dir / "setup_classic.json").write_text(json.dumps(setup, indent=1, sort_keys=True))
    land = sum(1 for t in territories.values() if not t["water"])
    print(f"territories: {len(territories)} ({land} land), capitals: {capitals}")
    print(f"unit stats: {len(unit_stats)}, treasuries: {treasuries}")


if __name__ == "__main__":
    main(sys.argv[1])
