"""Stub player: free, offline, deterministic-ish. Proves the whole table
loop (speech, dice, state, capture) before any API key is involved.
Strategy: buy infantry, attack an adjacent weaker enemy territory if one
exists, otherwise sit tight. Casualties cheapest-first."""
import state as S
from players.base import Player


class StubPlayer(Player):
    def decide(self, prompt, schema):
        raise NotImplementedError("stub uses the typed helpers below")

    # The orchestrator calls these helpers directly when provider == "stub".
    def assessment(self, state):
        return {"assessment": f"Stub {self.power} reports the lines are "
                              f"holding and sees no reason to panic."}

    def debrief(self, state):
        return {"assessment": f"Stub {self.power} considers that turn "
                              f"entirely adequate."}

    def purchases(self, state):
        ipcs = state["ipcs"][self.power]
        n = ipcs // S.STATS["infantry"]["cost"]
        return {"purchases": [{"unit": "infantry", "quantity": n}],
                "research_dice": 0,
                "reasoning": f"Stub buys {n} infantry."}

    def combat_moves(self, state):
        for terr, by_power in list(state["units"].items()):
            mine = by_power.get(self.power, {})
            movers = {u: n for u, n in mine.items() if u in ("infantry", "armour")}
            if not movers:
                continue
            for adj in S.TERR[terr]["adjacent"]:
                if S.TERR[adj]["water"]:
                    continue
                enemies = S.hostile_powers_in(state, adj, self.power)
                enemy_count = sum(sum(u.values()) for p, u in
                                  S.units_in(state, adj).items() if p in enemies)
                if enemies and enemy_count < sum(movers.values()):
                    return {"moves": [{"units": [{"type": u, "count": n}
                                                 for u, n in movers.items()],
                                       "from": terr, "to": adj}],
                            "reasoning": f"Stub attacks {adj} from {terr}."}
        return {"moves": [], "reasoning": "Stub holds position."}

    def noncombat_moves(self, state):
        return {"moves": [], "reasoning": "Stub stays put."}

    def casualties(self, pool, hits):
        order = ["infantry", "armour", "transport", "submarine", "fighter",
                 "carrier", "bomber", "battleship", "aaGun"]
        remove = {}
        left = hits
        for u in order:
            take = min(pool.get(u, 0), left)
            if take:
                remove[u] = take
                left -= take
        return {"remove": [{"type": u, "count": n} for u, n in remove.items()]}

    def press_or_retreat(self, terr):
        return {"action": "press"}

    def placements(self, state):
        cap = S.CAPITALS[self.power]
        pend = state["purchased_pending"].get(self.power, {})
        return {"placements": [{"unit": u, "territory": cap}
                               for u, n in pend.items() for _ in range(n)],
                "note_to_allies": "",
                "reasoning": "Stub places everything at the capital."}
