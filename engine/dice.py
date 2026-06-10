"""Dice: physical (typed in) or scripted."""
import random


def roll(n, label, mode="manual", speak=None, log=None):
    """Returns a list of n d6 results. In manual mode the table rolls real
    dice and types them as a digit string, e.g. '61423'."""
    if n <= 0:
        return []
    if mode == "auto":
        rolls = [random.randint(1, 6) for _ in range(n)]
        print(f"  [auto-dice] {label}: {''.join(map(str, rolls))}")
        if log:
            log(label, rolls)
        return rolls
    if speak:
        speak(f"Roll {n} dice: {label}")
    while True:
        raw = input(f"  ROLL {n} dice — {label} > ").strip().replace(" ", "")
        if len(raw) == n and all(c in "123456" for c in raw):
            rolls = [int(c) for c in raw]
            if log:
                log(label, rolls)
            return rolls
        print(f"  need exactly {n} digits, each 1-6 (got {raw!r})")
