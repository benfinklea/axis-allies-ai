# Handoff — axis-allies-ai

**Date:** 2026-06-10
**From:** Claude Code cloud session (scoped to `benfinklea/cmf`)
**To:** Ben + the Claude Code instance on the game-night Mac
**State:** Code complete and selftested offline. Never run against a live
API or a real board. Two config values missing (local base URLs).

## What this is

Five AIs play classic Axis & Allies (Milton Bradley 2nd edition) on Ben's
physical board. A Python orchestrator on an old Mac holds the game state,
queries one AI per power, speaks every move aloud, and takes physical dice
results typed in. Ben and his son move the plastic. Full concept in
README.md, architecture in PLAN.md, operating guide in CLAUDE.md.

## Where the code lives (transfer pending)

Built inside the `cmf` repo at `docs/axis-allies-ai/` on branch
`claude/ai-axis-allies-setup-cnusg4` — the cloud session couldn't reach any
other repo. Ben created a dedicated GitHub repo (name assumed
`axis-allies-ai`); **first action on the Mac: copy this folder there as the
repo root and push.** The folder is fully self-contained; nothing references
the surrounding cmf repo. The session branch in cmf is disposable once the
copy is pushed — do not merge it into cmf main.

## Decisions (all final — history in PLAN.md)

| Decision | Value |
|---|---|
| Edition | Classic, MB 2nd edition ("It's old") — NOT 1942/Revised |
| Weapons Development | ON (full classic tech chart) |
| Economic victory | ON — Axis income ≥ 84 (threshold unverified, see Risks) |
| War council | ON — allies share short notes, sides private |
| Dice | Physical, typed as digit strings (e.g. `614`) |
| Casualties | Always chosen by the owning AI |
| Roster | Germany=ChatGPT · Japan=claude-fable-5 · UK=Gemini · USSR=GLM-4.5-Air (local) · USA=Qwen3-235B (local) |
| Bench | Qwen3-Coder (rejected: coder models trade away reasoning), Gemma 3 27B, DeepSeek (game-two candidate) |
| Roster rationale | Two frontier models on Axis offsets classic's Allied tilt; reasoning > coder variants for strategy |

## What is DONE and verified

- **Board data** (`data/*.json`): converted from TripleA's open-source
  classic 2nd-edition XML by `tools/convert_triplea.py`. 128 territories
  (70 land) with adjacency, IPC values, capitals, unit stats, full starting
  setup, treasuries (G32/J25/R24/UK30/US36). Spot-checks match classic:
  one-hit battleships, armor def 2, no artillery/destroyers, Karelia
  factory. **Verified by selftest, not yet against the physical board.**
- **Engine**: turn loop (purchase → combat move → combat → noncombat →
  mobilize → income), BFS movement legality, research dice, factory
  placement caps NOT enforced (see Risks), capture + capital loot,
  capitals + economic victory checks, save/resume per turn.
- **Combat** (`engine/combat.py`): AA pre-fire, sub surprise strike,
  AI-chosen casualties with validation + cheapest-first fallback,
  press/retreat, air-only can't capture.
- **Players**: Anthropic adapter (Fable 5 — structured outputs, omit
  thinking, cache_control, refusal check); OpenAI-compatible adapter
  (ChatGPT/Gemini/local — response_format with auto-degrade to
  prompt-enforced JSON + repair layer); offline stub player.
- **Table**: macOS `say` TTS per-power voices, transcript log, war council.
- **Selftest** (`python3 selftest.py`): passes — 2 stub rounds end-to-end
  plus a seeded synthetic battle (resolution, casualties, capture).

## What has NEVER been tested

1. **Any live API call.** All five adapters are untested against real
   endpoints. `tools/smoke_providers.py` exists for exactly this — run it
   first. Expect the usual first-contact issues: wrong model IDs, auth,
   schema strictness differences.
2. **TTS** — built on this Linux container; `say` paths untested on macOS.
3. **A real game.** Stub players never exercise: research dice purchases,
   retreats, multi-power defense in one territory, transports/amphibious,
   war-council notes from real models, IPC loot on capital capture.

## Immediate next steps (in order)

1. Copy folder → new repo, push.
2. `pip3 install -r requirements.txt && python3 selftest.py` on the Mac.
3. `python3 game.py --stub` — verifies speech + dice entry feel at the table.
4. Fill `config.py`: two local `base_url`s (LAN boxes Gandalf/Frodo/Pippin —
   Ben was looking up which box serves which model; ports likely Ollama
   `:11434/v1` or LM Studio `:1234/v1`), and replace placeholder model IDs
   `gpt-5.2` / `gemini-2.5-pro` with current ones. Export the three API keys.
5. `python3 tools/smoke_providers.py` until all five say OK.
6. First real game. Expect referee moments; log rule gaps in PLAN.md §10.

## Known gaps and risks (deliberate scope, not bugs)

- **Econ victory threshold (84) unverified** — check the 2nd-edition
  rulebook; constant is `ECON_VICTORY_AXIS_INCOME` in config.py.
- **Industrial tech effects are vague** in prompts ("operator will
  confirm") and unimplemented in purchase pricing; heavy bombers and
  long-range aircraft are also prompt-documented but not engine-enforced.
  Tech currently affects combat rolls only (jet power, super subs).
- **Not enforced, table referees**: factory per-turn production caps,
  transport loading/amphibious chains, carrier capacity/landing legality,
  neutrals, canals, strategic bombing (bomber IPC raids), rockets.
- **Power elimination** is tracked (`state["eliminated"]`) but nothing ever
  sets it — a dead power's AI will keep being called with an empty board
  position. Fine for v1; fix if it annoys.
- **Local model JSON** — repair layer + one re-ask, then casualty fallback /
  bounced moves. If GLM or Qwen flail persistently, swap in their thinking
  variants or escalate to DeepSeek (bench).
- **Context growth** — per-power histories grow all game; fine for frontier
  APIs (caching on), but a small local context window will eventually
  truncate. If a local model degrades late-game, that's why (CLAUDE.md
  troubleshooting table has more).

## Cost expectations

~4–8 calls per power-turn, one provider per power. Frontier side: single-digit
dollars per game with prompt caching (system prompt carries cache_control in
the Anthropic adapter). Locals free. `smoke_providers.py` costs cents.

## Session history worth keeping

- Camera/vision input was considered and **rejected** as primary input
  (can't count stacked miniatures reliably); photos remain a future optional
  verification ritual (`photos.py` was planned but NOT built — PLAN.md §6).
- A Raspberry Pi rig was considered and rejected — the old Mac is the rig.
- TripleA data discovery (repo `triplea-maps/world_war_ii_classic`,
  `map/games/classic.xml`) replaced the original plan of hand-transcribing
  the board; keep the converter so the data is regenerable.
