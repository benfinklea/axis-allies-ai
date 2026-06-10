"""War council: allied powers leave notes for each other (toggle in config)."""
import config
import state as S


def brief(state, power):
    if not config.WAR_COUNCIL:
        return ""
    side = S.SIDES[power]
    notes = state["council_notes"].get(side, [])
    if not notes:
        return ""
    return ("\n\nWAR COUNCIL — notes from your allies (most recent last):\n"
            + "\n".join(f"- {n}" for n in notes[-6:]))


def record(state, power, note):
    if not config.WAR_COUNCIL or not note:
        return
    side = S.SIDES[power]
    state["council_notes"].setdefault(side, []).append(f"{power}: {note}")
    # keep the channel short — two notes per ally is plenty of context
    state["council_notes"][side] = state["council_notes"][side][-10:]
