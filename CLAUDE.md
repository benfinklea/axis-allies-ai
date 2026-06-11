# axis-allies-ai — project briefing

Five AIs (one per power) play classic Axis & Allies (Milton Bradley 2nd
edition) on a **physical board**. This Python orchestrator keeps the game
state, talks to all five model providers, speaks moves aloud, and takes
physical dice results typed in. The humans at the table move the plastic.
Read README.md for the concept, PLAN.md for architecture.

You (the assistant working in this repo) are the table engineer: help run
games, troubleshoot providers, and make small fixes between sessions.

## Table rules for the assistant — do not violate

- NEVER restart the game process (or otherwise replay any power's turn)
  without telling Ben what a restart will replay and getting his explicit
  agreement first — even to deploy a fix. Code changes wait, parked, until
  Ben approves a restart moment. (Ben, 2026-06-10 game night.)

## Locked decisions — do not relitigate

- Classic 2nd edition rules (NOT 1942, NOT Revised). One-hit battleships,
  armor defends on 2, no artillery/destroyers.
- Weapons Development ON, Economic victory ON (Axis income ≥ 84),
  War council ON, physical dice (manual entry), casualties always AI-chosen.
- Roster: Germany=ChatGPT (`codex`), Japan=claude-fable-5 (`fable`),
  UK=Gemini (`gemini`), USSR=GLM-4.5-Air (`code-glm`, local),
  USA=Qwen3-235B (`big`, local). Backticked names are fleet-gateway intents.
- No outside help: AIs may not web-search or use external tools for
  strategy — training knowledge only. Enforced in the system prompt
  (game.py persona); we also never pass tools in API requests. Keep it
  that way.
- One voice at a time: all speech is serialized through a lock
  (speech.py). Never call `say` directly on the speech host — route
  through speech.Table or you'll talk over the game.

## Source of truth rules

- `data/*.json` is **generated** from TripleA's classic 2nd-edition XML by
  `tools/convert_triplea.py`. Never hand-edit unit stats or adjacency; if
  something looks wrong, re-check the converter or the rulebook first. The
  one sanctioned manual change: rules discrepancies the table confirms
  against the physical rulebook (document them in PLAN.md §10).
- The engine is a **scorekeeper, not a rules lawyer** (PLAN.md §1). It
  enforces adjacency/range/IPC math/factory placement. Amphibious chains,
  carrier capacity, canals, and neutrals are refereed by the humans. Don't
  build full rules enforcement without being asked — it's a deliberate
  non-goal.
- Don't burn API spend silently: anything that calls paid providers beyond
  a single smoke turn, ask Ben first.

## Getting it running on this Mac

```sh
python3 --version          # need 3.9+; macOS: xcode-select --install or python.org
pip3 install -r requirements.txt
python3 selftest.py        # offline, no keys — must pass before anything else
python3 game.py --stub     # full table loop with offline stub AIs (tests TTS + dice)
```

Then configure the live providers:

1. One env var for all five players:
   `export FLEET_API_KEY=$(cat ~/.config/fleet/key)`. No per-vendor API keys.
2. All five powers route through the fleet gateway at
   `http://gandalf.local:4000/v1` — one OpenAI-compatible endpoint fronting
   every local box AND Ben's frontier subscriptions (ChatGPT/Codex, Claude
   plan, Gemini), so games cost $0 in API spend. The `model` field in
   config.py is a gateway *intent*, not a raw model id; the gateway owns
   routing, health, and failover. Don't point at boxes or vendor APIs
   directly. Note: `code-glm` (ussr) and `big` (usa) both live on gandalf
   and evict each other — ~35s model swap when the turn passes between
   them, acceptable at physical-board pace.
3. `python3 tools/smoke_providers.py` — one tiny JSON decision per
   configured power; prints OK/FAIL per provider. All five OK = ready.
   (Last verified all-5 OK: 2026-06-10.)
4. Japan's `fable` intent is free on the Claude plan through Jun 22, 2026,
   then becomes metered — switch japan to `opus` (still $0) after that.
5. `python3 tools/viewer.py` and open http://localhost:8484 — live view of
   every power, the AI playing it, its latest thinking, full per-AI comms,
   war-council channels, and the board. Read-only; leave it open all game.
6. Audio plays on the Mac named by `SPEECH_HOST` in config.py (over SSH),
   falling back to the local machine if unreachable. Set it to None to
   speak locally.

## Troubleshooting map

| Symptom | Likely fix |
|---|---|
| Local provider FAIL / connection refused | Gateway down or key missing. Verify: `curl http://gandalf.local:4000/v1/models -H "Authorization: Bearer $(cat ~/.config/fleet/key)"`. |
| Local model name not found | The `model` field must be a gateway intent (`code-glm`, `code`, `big`, `fast`, `reason`, ...) — check the live list with the curl above, not a raw model id. |
| Frontier power FAIL (germany/japan/uk) | Same gateway checks as above — these ride subscription routes (`codex`/`fable`/`gemini`), not vendor APIs. If one subscription route is down, the gateway's failover or a sibling intent (`opus`, `sonnet`, `frontier`) is the quick fix. |
| Garbage JSON from a local model | `players/repair.py` should catch it; if a provider rejects `response_format`, the adapter auto-degrades to prompt-enforced JSON. Persistent failures: try the model's "thinking" variant or a bigger quant. |
| No speech | `say` is macOS-only and per-voice downloads live in System Settings → Spoken Content. Missing voices fall back silently; set `SPEECH = False` in config to silence entirely. |
| Anthropic `refusal` stop reason | Shouldn't happen for a board game; if it does, re-send — and check the prompt didn't accumulate something weird. |
| Game interrupted mid-evening | State auto-saves per turn: `python3 game.py` resumes from `logs/state.json`. Snapshots per power-turn in `logs/snapshots/`. |
| AI proposes illegal moves repeatedly | It gets the bounce reason and retries; after `MAX_LEGALITY_RETRIES` the table referees. If one model does it constantly, check its state summary isn't being truncated by a small local context window. |

## Code map (one line each)

- `game.py` — turn/phase loop: briefing (spoken state-of-the-war), purchase+
  research, combat, noncombat, mobilize, income, debrief (spoken turn recap).
- `gamelog.py` — one JSONL per game in `logs/games/` (every prompt, reply,
  spoken line, dice roll, result) — the corpus for judging AIs across games.
- `tools/viewer.py` + `viewer.html` — live web viewer (`python3
  tools/viewer.py`, port 8484): per-power cards with model + latest thinking,
  click-through full AI conversations, war-council channels, transcript, board.
- `state.py` — board state, BFS movement legality, capture/loot, AI text summary.
- `engine/combat.py` — battle rounds: AA, sub surprise, casualties, retreat.
- `engine/dice.py` — manual digit-string entry or auto-roll.
- `players/anthropic_player.py` — Fable 5: structured outputs, omit thinking,
  no temperature, cache_control on system prompt, replay content unchanged.
- `players/openai_compat_player.py` — everyone else; schema → prompt fallback.
- `players/stub.py` — offline canned player; also the casualty fallback.
- `council.py` / `speech.py` — allied notes; `say` TTS + transcript.
- `selftest.py` — offline invariants; keep it passing.

## House style

- Python 3.9-compatible (old Mac): no `match`, no `X | Y` type unions.
- Keep modules small and boring; this is a family-table tool, not a product.
- After any engine change: `python3 selftest.py` before the next game night.
