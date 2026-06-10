# Software Plan — Axis & Allies AI-vs-AI Orchestrator

## 1. Goal and constraints

- Five AIs play a full game of classic **Axis & Allies (MB 2nd edition)**,
  one AI per power; humans execute moves on the physical board.
- Runs on an old Mac: Python 3.9+, no GPU required locally. Text-to-speech via
  the built-in `say` command (a distinct voice per power).
- Minimal human input: physical dice entry plus the occasional referee call.
- Providers (planned): Anthropic `claude-fable-5`, OpenAI (ChatGPT), Google
  Gemini, Qwen (local), one more local model TBD. All but Anthropic speak an
  OpenAI-compatible chat API (Gemini and Ollama both expose one), so the code
  needs exactly **two adapapter implementations** — Anthropic-native and
  OpenAI-compatible — and five config entries.
- Local models run wherever is convenient: Ollama on the old Mac if it's Apple
  Silicon, or on any other machine on the LAN (the adapter only needs a
  `base_url`). Don't assume the old Mac can serve inference.

## 2. Why classic edition helps

The 1986 game has a compact ruleset that keeps the engine tractable:

- Units: infantry, armor, fighter, bomber, submarine, transport, aircraft
  carrier, battleship, AA gun, industrial complex. No artillery, destroyers,
  cruisers, or naval/air rules added by later editions.
- Five powers, fixed turn order: USSR → Germany → UK → Japan → USA.
- Victory: capture both enemy capitals (economic-victory variant optional).
- Weapons Development (tech dice) is the one big rules toggle — see §9.

## 3. Architecture

```
axis-allies-ai/
├── game.py              # entry point: round loop, per-power turn loop
├── config.py            # power→AI mapping, models/base_urls, voices, toggles
├── state.py             # load/save/validate game state; income; victory check
├── engine/
│   ├── phases.py        # purchase, combat-move, combat, noncombat, mobilize
│   ├── combat.py        # battle rounds, casualties, retreat, capture, AA fire
│   └── dice.py          # manual dice entry ("61423"), validation, re-prompt
├── players/
│   ├── base.py          # Player interface: propose_purchases(), choose_casualties()…
│   ├── anthropic_player.py   # native Anthropic SDK (structured outputs)
│   └── openai_compat_player.py  # ChatGPT, Gemini, Ollama/Qwen, anything with /chat/completions
├── council.py           # war-council: share allied reasoning notes per round
├── speech.py            # macOS `say` wrapper; per-power voice; transcript log
├── photos.py            # optional: attach photos/inbox/*.jpg to next request
├── data/
│   ├── map_classic.json     # territories, adjacency, IPC values, sea zones
│   └── setup_classic.json   # MB 2nd-edition starting units & IPCs (verify vs the box!)
├── prompts/
│   ├── rules_summary.md     # shared classic-rules brief given to all five AIs
│   └── persona_<power>.md   # per-power briefing (objectives, standard openings)
└── logs/                # full game transcript + state snapshot after every phase
```

### Core loop

```
for round in 1..N:
    for power in [ussr, germany, uk, japan, usa]:
        ai = player_for(power)                       # one of five providers
        council.brief(ai, state)                     # allied notes, if enabled
        purchase   = ai.propose_purchases(state)     # 1 API call
        combat_mv  = ai.propose_combat_moves(state)  # 1 API call
        resolve_battles(state)                       # interactive; calls both sides' AIs
        noncombat  = ai.propose_noncombat(state)     # 1 API call
        placement  = ai.propose_placement(state)     # 1 API call
        collect_income(state)
        council.collect_notes(ai)                    # AI leaves a note for its ally
        snapshot(state)
```

Every applied action is (a) written to the state file, (b) appended to the
transcript, (c) spoken aloud in that power's voice.

### Player adapters

Both adapters implement the same interface and keep a **running conversation
history per power** for strategic continuity across the game. Responsibilities:

- Serialize the relevant slice of state into the user message (full state at
  turn start; deltas within a turn).
- Request **structured output** so move parsing never fails:
  - Anthropic: `output_config={"format": {"type": "json_schema", "schema": …}}`
    (hard guarantee).
  - OpenAI-compatible: JSON-schema response format where the provider supports
    it; otherwise prompt-enforced JSON.
- **JSON repair/retry layer** (shared): local models will produce malformed
  JSON sometimes. On parse failure: strip fences/prose → retry parse → one
  re-ask with the error message → finally fall back to a human referee prompt.
  Frontier models will rarely hit this; Qwen-class models will.
- **Legality retry**: if the engine rejects a move (bad adjacency, units that
  don't exist), the rejection reason is fed back and the AI re-proposes, max 2
  retries, then the referee decides.
- Provider quirks (Anthropic): `claude-fable-5` — omit `thinking` (always on),
  no `temperature`, `output_config.effort: "high"`, check
  `stop_reason == "refusal"` before reading content, `cache_control`
  breakpoint on the system prompt (histories grow long; caching is the main
  cost lever). Fable's tokenizer runs ~30% heavier — size `max_tokens`
  generously (16K is fine for move JSON).

### War council (`council.py`)

Classic A&A is a team game. With five independent minds, allies need a
coordination channel:

- After each power's turn, its AI writes a short "note to allies" (part of the
  placement-phase response — no extra API call).
- At the start of an allied power's turn, accumulated notes are injected into
  its context.
- Config: `WAR_COUNCIL = "on" | "off"`. Off = pure chaos mode; every power
  plays solo. Worth trying both — it's basically a science experiment.

## 4. Game state format (sketch)

```json
{
  "round": 1,
  "turn": "germany",
  "phase": "purchase",
  "powers": {
    "germany": {"side": "axis",   "ipcs": 32, "capital": "germany", "ai": "chatgpt"},
    "ussr":    {"side": "allies", "ipcs": 24, "capital": "russia",  "ai": "fable"}
  },
  "territories": {
    "karelia": {
      "owner": "ussr",
      "ipc_value": 3,
      "units": {"ussr": {"infantry": 3, "armor": 1}}
    },
    "sz_baltic": {
      "type": "sea",
      "units": {"germany": {"submarine": 1, "transport": 1}}
    }
  },
  "purchased_pending": {"germany": {"infantry": 4, "fighter": 1}},
  "council_notes": {"allies": ["UK: I'm reinforcing Egypt; need USSR to hold Karelia."]}
}
```

`map_classic.json` holds static data (adjacency graph, IPC values, starting
factory locations); the state file holds only what changes. Adjacency lets the
script reject impossible moves cheaply before they're spoken. IPC values and
the territory list must be transcribed from the actual MB 2nd-edition board —
**verify `data/` against the physical board before the first real game**
(editions and reprints differ; this is a 30-minute job with the board open).

## 5. Move schemas (per phase)

All schemas use `additionalProperties: false` throughout (required by
Anthropic structured outputs; no recursion, no min/max constraints).

- **Purchase**: `{"purchases": [{"unit": "infantry", "quantity": 4}], "reasoning": "…"}`
- **Combat / noncombat move**: `{"moves": [{"units": [{"type": "armor", "count": 1}], "from": "karelia", "to": "ukraine"}], "reasoning": "…"}`
- **Casualty selection**: `{"remove": [{"type": "infantry", "count": 2}]}` — always AI-chosen (locked decision)
- **Press/retreat**: `{"action": "press" | "retreat", "retreat_to": "territory?"}`
- **Placement + council note**: `{"placements": [{"unit": "fighter", "territory": "germany"}], "note_to_allies": "…"}`

The `reasoning` field is short and gets spoken aloud — hearing each AI explain
*why* it's invading is half the entertainment.

## 6. Combat resolution

1. Script identifies contested territories/sea zones after combat moves.
2. Per battle, loop:
   - Announce required rolls ("Germany: roll 3 dice for 2 infantry, 1 armor").
   - Humans roll **physical dice** and type them as a digit string (`614`).
     `dice.py` validates count/range and re-prompts on typos.
   - Hits assigned → owning AI chooses casualties (locked decision).
   - Attacker AI: press or retreat.
3. Classic special cases in `combat.py`: AA fire on overflight, battleship
   support shot on amphibious assaults, two-hit battleships **(check the 2nd
   edition rule — one-hit in classic unless house-ruled)**, sub surprise
   strike, transports as last casualty. Anything genuinely weird → script
   prompts the human referee with a y/n.

## 7. Photos (optional module, off by default)

Drop phone photos into `photos/inbox/`; the next Anthropic request attaches
them with "verify the board matches the state; list discrepancies." An
occasional ritual, not per-move. ~3–5K tokens per full-res photo.

## 8. Cost envelope (rough)

Per power-turn: ~4–8 API calls, but now spread across five providers — each
provider only handles its own power, so per-provider cost drops to ~⅕ of a
two-AI game. A 10-round game ≈ 50–100 calls per frontier provider. Fable side:
single-digit dollars per game with prompt caching on the system prompt + rules
summary. Local models: free, just slow.

## 9. Milestones

| # | Deliverable | Definition of done |
|---|---|---|
| M1 | Map + setup data | `map_classic.json` + `setup_classic.json` transcribed and verified against the physical board; state load/save; income calc; adjacency checks; unit tests |
| M2 | One scripted turn | `game.py` runs USSR turn 1 with a *stub* player (canned JSON) end-to-end, speaking moves and taking dice entry |
| M3 | Anthropic adapter | Stub replaced by the Fable adapter; one power played live |
| M4 | Combat engine | Full battle loop with manual dice + AI casualties + capture + AA |
| M5 | OpenAI-compat adapter | ChatGPT, Gemini, and one Ollama model all driving powers through the same adapter; full round 1 with five AIs at the table |
| M6 | Polish | War council, photo verification, transcript HTML export, resume-from-snapshot |

M2's stub player matters: it proves the whole table experience (TTS, dice,
state) for free, before any API spend.

## 10. Open questions

1. ~~Weapons Development~~ — **ON** (full classic tech chart).
2. ~~Economic victory~~ — **ON** (Axis income ≥ 84; threshold in config —
   verify the exact number against the 2nd-edition rulebook).
3. **House rules** — none declared yet; brief the AIs if your table has any.
4. ~~War council~~ — **ON**.
5. **Local host details** (still open): base URLs and serving stack
   (Ollama / LM Studio / vLLM) for the LAN boxes (Gandalf / Frodo / Pippin)
   running GLM-4.5-Air and Qwen3-235B → fill into `config.py`.

## 11. Build status

- **Done**: map + setup data converted from TripleA's classic 2nd-edition XML
  (`tools/convert_triplea.py` — 128 territories, unit stats, starting forces,
  treasuries); state engine with adjacency-checked movement; combat engine
  (AA fire, sub surprise strike, AI casualties, press/retreat, capture);
  purchase/research/mobilize/income phases; war council; TTS; JSON repair;
  stub player; Anthropic + OpenAI-compatible adapters; offline selftest.
- **Next**: local base_urls into config → one live-API smoke turn per
  provider → first real game.

## Resolved decisions

- Edition: classic A&A, MB 2nd edition (not 1942).
- Dice: physical, manual entry.
- Casualties: always AI-chosen.
- Five AIs, one per power; two adapter implementations cover all five.
