# Axis & Allies: Five AIs, One Board

Five different AIs — one per power — play classic **Axis & Allies (Milton
Bradley, 2nd edition)** against each other on a **physical board**. The humans
at the table are the hands: they move the plastic, roll the dice, and watch the
war unfold. An old Mac runs the orchestrator, announces every move out loud,
and keeps the authoritative game state.

| Power | AI (game one) |
|---|---|
| USSR | GLM-4.5-Air (local, thinking mode) |
| Germany | ChatGPT |
| UK | Gemini |
| Japan | Claude Fable 5 |
| USA | Qwen3-235B (local, thinking mode) |

Bench: Qwen3-Coder and Gemma 3 27B (local), DeepSeek (API) as a candidate
swap-in for game two. Power assignments are config, not code — reshuffle every
game and keep a standings table across games.

> **Note:** This folder is staged inside the `cmf` repo only because the
> planning session was scoped here. It is self-contained and should be moved
> to its own repository (`axis-allies-ai`) as the project root.

## Design principles

1. **Text state is the ground truth, not photos.** Vision models can't reliably
   count stacked miniatures across a big board. The orchestrator keeps the game
   state as JSON; the AIs play from that. Phone photos are an optional periodic
   sanity check, not the input pipeline.
2. **Humans never type moves.** The AIs *generate* the moves (as structured
   JSON), the script applies them to the state and speaks them aloud via macOS
   `say`. The humans' only typed input is physical dice results — a short digit
   string per battle round.
3. **The script is a scorekeeper, not a rules lawyer.** It validates the easy
   stuff (IPC math, unit existence, territory adjacency) and trusts the humans
   at the table to referee edge cases, exactly like a normal game night.
4. **Five minds, two alliances.** Allied powers are played by *different* AIs.
   A configurable "war council" lets allies share their strategic reasoning
   with each other each round — or not, if you want them stepping on each
   other's plans like real coalition partners.

## Locked decisions

- **Edition:** Classic A&A, Milton Bradley 2nd edition.
- **Dice:** physical, rolled at the table, entered as a digit string.
- **Casualties:** always chosen by the owning AI (never auto-assigned).
- **Players:** five AIs, one per power, provider-pluggable per config.

## What a turn looks like at the table

1. Mac announces: *"Germany's turn. Purchasing units…"*
2. Germany's AI returns purchases as JSON → script deducts IPCs, speaks them.
3. Combat moves arrive as JSON → script speaks each one → you move the plastic.
4. For each battle: you roll real dice and type the results, the AIs choose
   their casualties and whether to press or retreat. Script narrates rounds.
5. Noncombat moves, unit placement, income collection — same pattern.
6. Next power. Repeat until a side holds the enemy capitals.

## Rules in play

Weapons Development **on** · Economic victory **on** (Axis income ≥ 84) ·
War council **on** · Physical dice · AI-chosen casualties.

## Running it

```sh
pip3 install -r requirements.txt
python3 selftest.py                  # offline smoke test — no API keys needed
python3 game.py --stub               # full table experience (speech, dice) with stub AIs
python3 tools/smoke_providers.py     # one tiny live call per provider — all five must say OK
python3 game.py --new                # the real thing
```

Working on this repo with Claude Code? `CLAUDE.md` briefs the assistant on
the locked decisions, code map, and a troubleshooting table.

Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, and fill in the
two local `base_url`s in `config.py`. State auto-saves to `logs/state.json`
after every turn — `python3 game.py` resumes mid-game (table sessions can
span evenings).

The board data in `data/` is converted from the open-source TripleA project's
classic 2nd-edition map (`tools/convert_triplea.py`), so adjacency, IPC
values, and the starting setup are battle-tested — spot-check a few
territories against your board rather than transcribing anything.

## Status

Engine, data, stub player, and both API adapters are built; offline selftest
passes (two full rounds + combat resolution). Remaining: fill in local
base_urls, live smoke test each provider, first real game. See
[PLAN.md](PLAN.md) for architecture and milestones.
