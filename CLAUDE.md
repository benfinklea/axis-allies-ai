# axis-allies-ai — project briefing

Five AIs (one per power) play classic Axis & Allies (Milton Bradley 2nd
edition) on a **physical board**. This Python orchestrator keeps the game
state, talks to all five model providers, speaks moves aloud, and takes
physical dice results typed in. The humans at the table move the plastic.
Read README.md for the concept, PLAN.md for architecture.

You (the assistant working in this repo) are the table engineer: help run
games, troubleshoot providers, and make small fixes between sessions.

## Locked decisions — do not relitigate

- Classic 2nd edition rules (NOT 1942, NOT Revised). One-hit battleships,
  armor defends on 2, no artillery/destroyers.
- Weapons Development ON, Economic victory ON (Axis income ≥ 84),
  War council ON, physical dice (manual entry), casualties always AI-chosen.
- Roster: Germany=ChatGPT, Japan=claude-fable-5, UK=Gemini,
  USSR=GLM-4.5-Air (local), USA=Qwen3-235B (local).

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

1. Env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`.
2. `config.py`: the two local powers (ussr, usa) have `base_url:
   "http://FILL-ME-IN:11434/v1"` — point at the LAN boxes
   (Gandalf/Frodo/Pippin, whichever serve GLM-4.5-Air and Qwen3-235B).
3. `python3 tools/smoke_providers.py` — one tiny JSON decision per
   configured power; prints OK/FAIL per provider. All five OK = ready.
4. Check `config.py` model names against reality: the OpenAI and Gemini
   entries are placeholders from build time — set them to current model IDs.

## Troubleshooting map

| Symptom | Likely fix |
|---|---|
| Local provider FAIL / connection refused | Wrong base_url or service down. Ollama serves `http://host:11434/v1`; LM Studio `http://host:1234/v1`. `curl http://host:11434/v1/models` from this Mac to verify reachability + exact model name. |
| Local model name not found | Model id must match the server's list exactly (`ollama list`), e.g. `glm-4.5-air:latest` not `glm-4.5-air`. |
| Gemini auth/404 | Needs the OpenAI-compat endpoint in base_url (`.../v1beta/openai`) and a current model id. |
| Garbage JSON from a local model | `players/repair.py` should catch it; if a provider rejects `response_format`, the adapter auto-degrades to prompt-enforced JSON. Persistent failures: try the model's "thinking" variant or a bigger quant. |
| No speech | `say` is macOS-only and per-voice downloads live in System Settings → Spoken Content. Missing voices fall back silently; set `SPEECH = False` in config to silence entirely. |
| Anthropic `refusal` stop reason | Shouldn't happen for a board game; if it does, re-send — and check the prompt didn't accumulate something weird. |
| Game interrupted mid-evening | State auto-saves per turn: `python3 game.py` resumes from `logs/state.json`. Snapshots per power-turn in `logs/snapshots/`. |
| AI proposes illegal moves repeatedly | It gets the bounce reason and retries; after `MAX_LEGALITY_RETRIES` the table referees. If one model does it constantly, check its state summary isn't being truncated by a small local context window. |

## Code map (one line each)

- `game.py` — turn/phase loop, purchase+research, mobilize, income, victory.
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
