#!/usr/bin/env python3
"""Generate data/board_layout.json: approximate board positions (x,y in
0-100) for every territory, from hand-curated lat/lon. Projection matches
the classic board: split through the Americas (~lon -100), so the Pacific
theater is contiguous like the printed map. Rerun after map changes."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LATLON = {
    # --- land ---
    "Afghanistan": (34, 66), "Alaska": (64, -150), "Algeria": (30, 2),
    "Anglo Sudan Egypt": (22, 30), "Angola": (-12, 17),
    "Argentina-Chile": (-35, -65), "Australia": (-25, 134),
    "Borneo Celebes": (0, 116), "Brazil": (-10, -50),
    "Caroline Islands": (7, 150), "Caucasus": (42, 44), "China": (32, 105),
    "Columbia": (4, -72), "Congo": (-3, 22), "Cuba": (21, -78),
    "East Canada": (50, -75), "East Europe": (50, 21),
    "East Indies": (-4, 106), "East US": (38, -80), "Eire": (53, -8),
    "Evenki National Okrug": (62, 95), "Finland Norway": (64, 18),
    "French Equatorial Africa": (6, 16), "French Indo China": (14, 103),
    "French West Africa": (14, -5), "Germany": (51, 10),
    "Gibraltar": (35, -7), "Hawaiian Islands": (20, -156),
    "India": (22, 78), "Italian East Africa": (8, 40), "Japan": (37, 138),
    "Karelia S.S.R.": (63, 32), "Kazakh S.S.R.": (48, 67),
    "Kenya-Rhodesia": (-8, 32), "Kwangtung": (23, 113), "Libya": (27, 17),
    "Madagascar": (-19, 47), "Manchuria": (45, 125), "Mexico": (23, -102),
    "Midway": (28, -177), "Mongolia": (46, 103), "Mozambique": (-18, 35),
    "New Guinea": (-6, 143), "New Zealand": (-41, 174),
    "Novosibirsk": (55, 80), "Okinawa": (26.5, 128), "Panama": (9, -80),
    "Persia": (32, 53), "Peru": (-12, -75), "Philippines": (12, 122),
    "Rio del Oro": (24, -13), "Russia": (56, 38), "Saudi Arabia": (24, 45),
    "Sinkiang": (41, 85), "Solomon Islands": (-10, 161),
    "South Africa": (-30, 24), "South Europe": (42, 13),
    "Soviet Far East": (60, 150), "Spain": (40, -4), "Sweden": (61, 15),
    "Switzerland": (46.5, 8), "Syria Jordan": (33, 37), "Turkey": (39, 33),
    "Ukraine S.S.R.": (48.5, 32), "United Kingdom": (54, -2),
    "Wake Island": (19, 167), "West Canada": (55, -115),
    "West Europe": (47, 2), "West US": (38, -118), "Yakut S.S.R.": (64, 128),
    # --- sea zones ---
    "Alaska Sea Zone": (55, -160), "Angola Sea Zone": (-14, 5),
    "Antartic Sea Zone": (-62, 20), "Baltic Sea Zone": (57, 19),
    "Black Sea Zone": (43, 34), "Borneo Sea Zone": (4, 112),
    "Caroline Islands Sea Zone": (3, 148), "Carribean Sea Zone": (15, -73),
    "Caspian Sea Zone": (42, 50),
    "Central Mediteranean Sea Zone": (36, 16), "Congo Sea Zone": (-4, 8),
    "East Argentina Sea Zone": (-45, -55), "East Canada Sea Zone": (45, -55),
    "East Compass Sea Zone": (-35, 95), "East Indies Sea Zone": (-9, 103),
    "East Mediteranean Sea Zone": (33, 28), "East Pacific Sea Zone": (0, -110),
    "East US Sea Zone": (34, -70), "French Indo China Sea Zone": (10, 108),
    "Gulf of Mexico Sea Zone": (24, -90), "Hawaii Sea Zone": (17, -158),
    "Indian Ocean Sea Zone": (0, 78), "Japan Sea Zone": (34, 133),
    "Karelia Sea Zone": (70, 35), "Kwangtung Sea Zone": (18, 114),
    "Mexico Sea Zone": (14, -98), "Midway Sea Zone": (31, -179),
    "Mozambique Sea Zone": (-22, 40), "New Guinea Sea Zone": (-9, 147),
    "New Zealand Sea Zone": (-38, 170), "North Atlantic Sea Zone": (45, -40),
    "North Australia Sea Zone": (-14, 130), "North Brazil Sea Zone": (0, -40),
    "North Pacific Sea Zone": (45, 178), "North Sea Zone": (57, -8),
    "Okinawa Sea Zone": (24, 131), "Peru Sea Zone": (-15, -82),
    "Philippines Sea Zone": (13, 126), "Red Sea Zone": (18, 39),
    "Solomon Islands Sea Zone": (-7, 158), "South Africa Sea Zone": (-38, 20),
    "South Argentina Sea Zone": (-55, -68),
    "South Atlantic Sea Zone": (-30, -15),
    "South Australia Sea Zone": (-40, 135), "South Brazil Sea Zone": (-25, -38),
    "South Compass Sea Zone": (-50, 80),
    "South East Madagascar Sea Zone": (-28, 54),
    "South Pacific Sea Zone": (-30, -150),
    "Soviet Far East Sea Zone": (55, 158), "Wake Island Sea Zone": (16, 169),
    "West Africa Sea Zone": (12, -20), "West Australia Sea Zone": (-28, 105),
    "West Canada Sea Zone": (50, -135), "West Compass Sea Zone": (-35, 62),
    "West Mediteranean Sea Zone": (37, 1), "West Spain Sea Zone": (41, -13),
    "West Panama Sea Zone": (4, -86), "West US Sea Zone": (32, -126),
}

SPLIT = -100  # board edge runs through the Americas, like the printed map


def project(lat, lon):
    x = ((lon - SPLIT) % 360) / 3.6
    y = (90 - lat) / 1.65 - 8     # crop empty polar bands
    return round(x, 1), round(max(2, min(98, y)), 1)


def main():
    terr = json.loads((ROOT / "data" / "map_classic.json").read_text())[
        "territories"]
    missing = sorted(set(terr) - set(LATLON))
    extra = sorted(set(LATLON) - set(terr))
    if missing or extra:
        raise SystemExit(f"layout out of sync: missing={missing} extra={extra}")
    layout = {t: project(*LATLON[t]) for t in sorted(terr)}
    out = ROOT / "data" / "board_layout.json"
    out.write_text(json.dumps(layout, indent=1))
    print(f"wrote {out} ({len(layout)} positions)")


if __name__ == "__main__":
    main()
