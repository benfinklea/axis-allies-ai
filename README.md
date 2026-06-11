# axis-allies-ai

Five AIs play classic **Axis & Allies** (Milton Bradley 2nd edition, 1942
setup) on a **physical board**. A Python orchestrator keeps the game state,
talks to all five model providers, narrates the war out loud, and takes
physical dice rolls from a web form. The humans at the table move the
plastic — and referee the weird stuff.

| Power | AI | Voice |
|---|---|---|
| 🇩🇪 Germany | GPT-5.x Codex | Jamie (Premium) |
| 🇯🇵 Japan | Claude Fable 5 | Oliver (Enhanced) |
| 🇬🇧 United Kingdom | Gemini 3.1 Pro | Kate (Enhanced) |
| ☭ USSR | GLM-4.5-Air (local) | Stephanie (Enhanced) |
| 🇺🇸 United States | Qwen3-235B (local) | Ava (Premium) |

All five route through one OpenAI-compatible fleet gateway; the frontier
powers ride existing subscriptions, the locals run on home-lab GPUs — games
cost $0 in API spend.

## Game night

```sh
export FLEET_API_KEY=$(cat ~/.config/fleet/key)
./play --new                      # fresh game (./play resumes a saved one)
python3 tools/viewer.py           # war room + board, http://localhost:8484
```

- **War room** (`/`): per-power cards with each AI's live thinking, full
  AI conversations, war-council channels, battle log, photo checks, table
  transcript — plus the table controls: ⏸ pause, 🔇 mute, 🛑 end / ▶ start
  game, ⏪ back up one turn, the gold **DO THIS** checklist with its Done
  button, and the **battle board** dice form (attackers left, defenders
  right, all rolls in one submit).
- **Game board** (`/board`): the world map with every territory, stack,
  capital and contested space — plus a snapshot scrubber that replays any
  live or simulated game turn by turn.
- **Photo verification**: snap the board (AirDrop is fastest), then
  `python3 photos.py --airdrop --count N` — a vision model inventories the
  photos blind and a deterministic diff reports what's missing/extra vs the
  engine.

The engine enforces the classic rules it knows (movement legality, air
landing, stop-on-contact, sub withdrawal, retreat paths, placement rules…)
and every AI re-reads the governing rulebook sections, per phase, before it
acts. Illegal plans bounce back privately until they're legal. Everything
spoken, decided, and rolled lands in one JSONL corpus per game under
`logs/games/` — the raw material for judging AIs across games.

## Fast simulations & rule variants

```sh
python3 simulate.py                              # 5 headless games, <1s each
python3 simulate.py --games 50 --seed 42         # reproducible batches
python3 simulate.py --variant variants/rich-allies.json
python3 simulate.py --model fast                 # all powers on a real AI
```

Variants are plain JSON — config toggles, unit-stat overrides, setup
tweaks — see `variants/`. Every sim records per-turn snapshots you can
replay on `/board`.

## Layout

- `game.py` — the 6-step action sequence per turn, validation loops, table gates
- `state.py` / `engine/` — board state, movement legality, battle resolution, dice
- `players/` — AI adapters (OpenAI-compatible via the gateway) + offline stub
- `prompts/` — rules summary + distilled rulebook KB injected per phase
- `tools/` — viewer/board web UI, TripleA map converter, provider smoke test
- `data/` — map, setup, and board layout (generated; don't hand-edit)
- `selftest.py` — offline invariants; keep it green

Classic 2nd-edition rulebook scan + OCR stay local (gitignored) — the repo
is public.
