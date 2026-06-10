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


def board_text(use_setup):
    if use_setup:
        setup = json.loads((ROOT / "data" / "setup_classic.json").read_text())
        st = {"round": 0, "turn": "setup", "phase": "setup",
              "ipcs": setup["ipcs"], "owners": setup["owners"],
              "units": setup["units"], "tech": {}, "eliminated": []}
        return S.summary_for_ai(st)
    path = ROOT / config.STATE_FILE
    if not path.exists():
        sys.exit(f"no game state at {path} — use --setup for a fresh board")
    return S.summary_for_ai(S.load(path))


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
        "max_tokens": 2000,
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
    if "--airdrop" in args:
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
    else:
        prompt = (f"These are photos of a physical classic Axis & Allies "
                  f"board mid-game. {PIECE_COLORS}\n\nThe game engine "
                  f"believes the board is:\n{board_text('--setup' in args)}\n\n"
                  f"Compare the photos against the engine's state. Report:\n"
                  f"1. DISCREPANCIES — territories where the photos clearly "
                  f"contradict the engine (wrong units, counts, or owner). "
                  f"Only report what you can see clearly.\n"
                  f"2. UNREADABLE — board areas the photos don't show or are "
                  f"too blurry/far to count.\n"
                  f"3. VERDICT — one spoken sentence: either 'board matches' "
                  f"or the most important mismatch to fix.\n"
                  f"Be conservative: a stack you can't count is UNREADABLE, "
                  f"not a discrepancy.")

    print("asking the vision model...")
    answer = ask_vision(photos, prompt)
    print("\n" + answer + "\n")
    (photos[0].parent / "verdict.md").write_text(answer + "\n")

    table = Table()
    spoken = "Photo check complete. Read the report on screen."
    lines = answer.splitlines()
    for i, line in enumerate(lines):
        bare = line.strip().strip("*#").strip()
        if bare.upper().startswith(("VERDICT", "3. VERDICT")):
            after = bare.split(":", 1)[-1].strip() if ":" in bare else ""
            if not after:  # verdict text on the following line(s)
                after = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
            if after:
                spoken = after
            break
    table.speak(f"Photo verification: {spoken}")


if __name__ == "__main__":
    main()
