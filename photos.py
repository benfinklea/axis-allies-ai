#!/usr/bin/env python3
"""Board photo verification ritual. Snap the board with the iPhone (it
syncs to Photos on the Mac via iCloud), then:

    python3 photos.py                # newest 3 photos vs logs/state.json
    python3 photos.py --count 5      # use the newest 5 photos
    python3 photos.py --setup        # compare against the starting setup
    python3 photos.py --wait         # wait (up to 5 min) for new photos
                                     # to sync before grabbing them
    python3 photos.py --describe     # no comparison; just inventory what
                                     # the vision model can see
    python3 photos.py --folder       # pull from the iCloud Drive folder
                                     # (Files app -> iCloud Drive ->
                                     # AxisAllies) instead of Photos —
                                     # use when Photos sync lags
    python3 photos.py --airdrop      # pull from ~/Downloads on the host:
                                     # AirDrop the shots to the Mac for
                                     # instant transfer (no iCloud wait)

Pulls the newest photos out of the Photos library on PHOTOS_HOST over SSH,
downsizes them, sends them with the engine's board state to VISION_MODEL
(the only gateway route that passes images through; OpenRouter-metered,
cents per check), and speaks/prints any disagreements. The table referees:
this is a sanity ritual, not an umpire.
"""
import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config
import state as S
from speech import Table

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
EXPORT_DIR = "/tmp/axis-allies-photos"
LONG_EDGE = "2048"   # enough detail to count pieces in section close-ups

# Photo technique that actually verifies (tested 2026-06-10):
# one straight-down full-board shot for layout, then section close-ups at
# ~45 degrees — high enough that territory names are readable, low enough
# that the chip stacks under pieces show edge-on. Near-horizontal shots
# fail (pieces occlude each other; can't tell which territory is which).
# Stills beat video — video frames are softer.

PIECE_COLORS = ("Piece colors (Milton Bradley classic): Germany=gray, "
                "Japan=orange/yellow, UK=tan/brown, USSR=reddish brown, "
                "USA=olive green. COUNTING CHIPS: a single plastic piece "
                "standing on a stack of chips represents multiple copies of "
                "that unit — each white/gray chip adds 1 and each RED chip "
                "adds 5 (a piece on 2 white chips = 3 units; a piece on 1 "
                "red + 1 white = 7). Count chips edge-on in angled shots "
                "instead of trying to separate plastic figures.")


def host():
    h = getattr(config, "PHOTOS_HOST", None)
    if not h:
        sys.exit("config.PHOTOS_HOST is not set")
    return h


def photo_count():
    out = subprocess.run(
        SSH + [host(), "osascript", "-e",
               "'tell application \"Photos\" to get count of media items'"],
        capture_output=True, text=True)
    return int(out.stdout.strip()) if out.returncode == 0 else None


def fetch_newest(count):
    """Export the newest `count` photos on the Photos host, downsized;
    returns local paths under logs/photos/<timestamp>/."""
    refs = ", ".join(f"item -{i} of mi" for i in range(1, count + 1))
    script = (f'tell application \\"Photos\\"\n set mi to media items\n '
              f'export {{{refs}}} to POSIX file \\"{EXPORT_DIR}\\"\n end tell')
    remote = (f"rm -rf {EXPORT_DIR} && mkdir -p {EXPORT_DIR} && "
              f"osascript -e \"{script}\" >/dev/null && cd {EXPORT_DIR} && "
              f"i=1; for f in $(ls -t); do sips -Z {LONG_EDGE} \"$f\" "
              f"--out small_$i.jpg >/dev/null 2>&1; i=$((i+1)); done && "
              f"ls small_*.jpg")
    out = subprocess.run(SSH + [host(), remote], capture_output=True, text=True)
    names = out.stdout.split()
    if out.returncode != 0 or not names:
        sys.exit(f"photo export failed: {out.stderr.strip()[:300]}")
    dest = ROOT / "logs" / "photos" / time.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["scp", "-q"] + [f"{host()}:{EXPORT_DIR}/{n}" for n in names]
                   + [str(dest)], check=True)
    return sorted(dest.glob("small_*.jpg"))


def fetch_from_folder(count, folder=None):
    """Newest `count` images from a folder on the host. Default is the
    iCloud Drive AxisAllies folder; --airdrop uses ~/Downloads (AirDrop
    lands there — instant over LAN, no cloud round-trip)."""
    if folder is None:
        folder = getattr(config, "PHOTOS_FOLDER",
                         "Library/Mobile Documents/com~apple~CloudDocs/AxisAllies")
    remote = (
        f'cd "$HOME/{folder}" || exit 1; '
        f"rm -rf {EXPORT_DIR} && mkdir -p {EXPORT_DIR}; i=1; "
        f"for f in $(ls -t | grep -iE '\\.(jpe?g|heic|png)$' | head -{count}); "
        f'do sips -s format jpeg -Z {LONG_EDGE} "$f" '
        f"--out {EXPORT_DIR}/small_$i.jpg >/dev/null 2>&1; i=$((i+1)); done; "
        f"ls {EXPORT_DIR}/small_*.jpg 2>/dev/null")
    out = subprocess.run(SSH + [host(), remote], capture_output=True, text=True)
    names = [Path(n).name for n in out.stdout.split()]
    if not names:
        sys.exit(f"no images found in iCloud Drive {folder} on {host()}")
    dest = ROOT / "logs" / "photos" / time.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["scp", "-q"] + [f"{host()}:{EXPORT_DIR}/{n}" for n in names]
                   + [str(dest)], check=True)
    return sorted(dest.glob("small_*.jpg"))


def wait_for_new(count, timeout=300):
    base = photo_count()
    if base is None:
        sys.exit("cannot reach the Photos host")
    print(f"waiting for {count} new photos to sync (library has {base})...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(20)
        n = photo_count()
        if n and n >= base + count:
            print(f"synced: {n - base} new photos")
            return
        print(f"  ...{(n or base) - base} of {count}")
    sys.exit("timed out waiting for photos to sync; try again or drop --wait")


def _norm(s):
    return "".join(c for c in s.lower() if c.isalnum() or c == " ").strip()


def _match_territory(name):
    """Map the model's territory string to a board name ('Karelia' ->
    'Karelia S.S.R.'). None if nothing plausible matches."""
    n = _norm(name)
    if not n:
        return None
    by_norm = {_norm(t): t for t in S.TERR}
    if n in by_norm:
        return by_norm[n]
    hits = [t for k, t in by_norm.items() if n in k or k in n]
    return hits[0] if len(hits) == 1 else None


POWER_ALIASES = {"germany": "germany", "german": "germany", "japan": "japan",
                 "japanese": "japan", "uk": "uk", "britain": "uk",
                 "british": "uk", "united kingdom": "uk", "ussr": "ussr",
                 "soviet": "ussr", "soviet union": "ussr", "russia": "ussr",
                 "usa": "usa", "us": "usa", "united states": "usa",
                 "america": "usa", "american": "usa"}


def _match_power(name):
    return POWER_ALIASES.get(_norm(name), _norm(name))


def ask_vision(images, prompt):
    key_path = Path.home() / ".config" / "fleet" / "key"
    key = key_path.read_text().strip()
    content = [{"type": "text", "text": prompt}]
    for img in images:
        b64 = base64.b64encode(img.read_bytes()).decode()
        content.append({"type": "image_url", "image_url":
                        {"url": f"data:image/jpeg;base64,{b64}"}})
    body = json.dumps({
        "model": getattr(config, "VISION_MODEL", "frontier-or"),
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": content}],
    }).encode()
    req = urllib.request.Request(
        config.FLEET_BASE_URL + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def main():
    args = sys.argv[1:]
    count = int(args[args.index("--count") + 1]) if "--count" in args else 3
    if "--wait" in args:
        wait_for_new(count)
    if "--reuse" in args:  # re-run the analysis on already-fetched photos
        photos = sorted(Path(args[args.index("--reuse") + 1]).glob("*.jpg"))
        if not photos:
            sys.exit("no jpgs in the --reuse directory")
    elif "--airdrop" in args:
        photos = fetch_from_folder(count, folder="Downloads")
    elif "--folder" in args:
        photos = fetch_from_folder(count)
    else:
        photos = fetch_newest(count)
    print(f"fetched {len(photos)} photos -> {photos[0].parent}")

    if "--describe" in args:
        prompt = (f"These are photos of a physical classic Axis & Allies "
                  f"board. {PIECE_COLORS} Inventory everything you can read: "
                  f"for each territory you can identify, list the units you "
                  f"see (type, count, owning power). Then say which parts of "
                  f"the board you cannot read and what additional photos "
                  f"would help.")
        print("asking the vision model...")
        answer = ask_vision(photos, prompt)
        print("\n" + answer + "\n")
        (photos[0].parent / "verdict.md").write_text(answer + "\n")
        Table().speak("Photo description done. Report is in the viewer.")
        return

    # Stage 1 — BLIND inventory. The model never sees the engine state, so
    # it cannot pattern-complete a checklist into false confirmations.
    prompt = (
        f"These are photos of a physical classic Axis & Allies board. "
        f"{PIECE_COLORS}\n\n"
        f"Inventory ONLY what you can positively see. For every territory "
        f"or sea zone you can identify by its printed name, list the units "
        f"physically present. Do NOT use knowledge of Axis & Allies setups "
        f"to fill in what 'should' be there — unseen is unseen. If you "
        f"cannot read a territory's name or attribute its pieces, skip it.\n"
        f"Unit types: infantry, armour, fighter, bomber, aaGun, factory, "
        f"transport, submarine, carrier, battleship.\n"
        f"Counting: count = plastic figures PLUS chips under them (each "
        f"white/gray chip +1, each red chip +5). If a piece stands on chips "
        f"you cannot clearly count, report count as your best estimate and "
        f"countable: false. Ships belong to sea zones, not the island or "
        f"coast they sit near — if you can't read the sea zone name, skip "
        f"the ship.\n"
        f"IMPORTANT — inset boxes: the small labeled boxes along the board "
        f"edges are zoom areas for crowded territories (Germany, United "
        f"Kingdom, Japan, Eastern US, Western US, etc.). This table places "
        f"factories, AA guns, and sometimes other units IN those boxes. "
        f"Units in an inset box belong to the territory printed on the box "
        f"— report them under that territory's name, merged with any units "
        f"on the territory itself.\n"
        f"Reply with ONLY a JSON object, no prose:\n"
        f'{{"observations": [{{"territory": "<printed name>", '
        f'"power": "<germany|japan|uk|ussr|usa>", '
        f'"units": [{{"type": "<unit>", "count": <n>, '
        f'"countable": <true if you could count pieces/chips, else false>}}]'
        f"}}]}}")
    print("asking the vision model for a blind inventory...")
    answer = ask_vision(photos, prompt)
    try:
        from players import repair
        observed = repair.parse(answer).get("observations", [])
    except Exception:
        sys.exit(f"could not parse the inventory:\n{answer[:500]}")

    # Stage 2 — deterministic diff against the engine. No model judgement.
    engine = (json.loads((ROOT / "data" / "setup_classic.json").read_text())
              ["units"] if "--setup" in args
              else S.load(ROOT / config.STATE_FILE)["units"])
    seen = {}
    for o in observed:
        terr = _match_territory(o.get("territory", ""))
        if terr:
            slot = seen.setdefault(terr, {}).setdefault(
                _match_power(o.get("power", "")), {})
            for u in o.get("units", []):
                if u.get("type") in S.STATS or u.get("type") == "factory":
                    slot[u["type"]] = {"count": u.get("count", 0),
                                       "countable": bool(u.get("countable"))}
    def in_adjacent_sea(terr, power, utype):
        for adj in S.TERR[terr]["adjacent"]:
            if S.TERR[adj]["water"] and \
                    engine.get(adj, {}).get(power, {}).get(utype):
                return True
        return False

    missing, extra, count_off, color_checks, unseen_terr = [], [], [], [], []
    for terr, by_power in sorted(engine.items()):
        if terr not in seen:
            unseen_terr.append(terr)
            continue
        for power, units in by_power.items():
            obs = seen[terr].get(power, {})
            for utype, n in units.items():
                if utype not in obs:
                    others = [p for p, us in seen[terr].items()
                              if p != power and utype in us]
                    if others:  # probably the same piece, color misread
                        color_checks.append(
                            f"{terr}: a {utype} read as {others[0]} — engine "
                            f"says it should be {power}; check the color")
                    else:
                        missing.append(f"{terr}: {power} {utype} not seen")
                elif obs[utype]["countable"] and obs[utype]["count"] != n:
                    count_off.append(f"{terr}: {power} {utype} — engine says "
                                     f"{n}, photos show {obs[utype]['count']}")
    for terr, by_power in seen.items():
        for power, units in by_power.items():
            expected = engine.get(terr, {}).get(power, {})
            for utype in units:
                if utype in expected:
                    continue
                if utype in S.SEA_UNITS and not S.TERR[terr]["water"] \
                        and in_adjacent_sea(terr, power, utype):
                    continue  # ship attributed to the coast it sits near
                if any(utype in engine.get(terr, {}).get(p, {})
                       for p in engine.get(terr, {})):
                    continue  # color misread, already in color_checks
                extra.append(f"{terr}: {power} {utype} seen but not in "
                             f"the engine")

    report = ["# Photo check — " + time.strftime("%H:%M"),
              f"photos: {len(photos)} | territories read: {len(seen)} | "
              f"occupied territories not visible: {len(unseen_terr)}", ""]
    for title, rows in (("MISSING (in engine, not in photos)", missing),
                        ("EXTRA (in photos, not in engine)", extra),
                        ("COUNT MISMATCHES", count_off),
                        ("COLOR CHECKS (piece there, owner unclear)",
                         color_checks)):
        report.append(f"## {title}")
        report += [f"- {r}" for r in rows] or ["- none"]
        report.append("")
    report.append("## Not visible in these photos")
    report.append(", ".join(unseen_terr) or "everything was visible")
    text = "\n".join(report)
    print("\n" + text + "\n")
    (photos[0].parent / "verdict.md").write_text(
        text + "\n\n## Raw inventory\n" + answer + "\n")

    # photo checks become part of the game's corpus log (with the photos)
    state_path = ROOT / config.STATE_FILE
    if state_path.exists():
        st = S.load(state_path)
        if st.get("game_id"):
            from gamelog import GameLog
            GameLog(st, Path(config.STATE_FILE).parent / "games") \
                .photo_check(photos, text)

    problems = len(missing) + len(extra) + len(count_off)
    if problems:
        spoken = (f"{problems} problems. " +
                  ". ".join((missing + extra + count_off)[:3]))
    else:
        spoken = (f"No discrepancies in the {len(seen)} territories I could "
                  f"read. {len(unseen_terr)} territories were not visible.")
    Table().speak(f"Photo verification: {spoken}")


if __name__ == "__main__":
    main()
