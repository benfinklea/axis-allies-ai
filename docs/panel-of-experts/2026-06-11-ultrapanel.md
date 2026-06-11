# Ultrapanel review — 2026-06-11 (post game night 1)

**How it ran:** the intended 5 inner Claude-orchestrated fleet panels died on
the Claude monthly spend cap mid-run. Fallback: five direct single-shot review
seats on the fleet's $0 routes — Codex (game loop), Gemini 3.1 (viewer UX),
GLM-4.5-Air (rules fidelity), Qwen3.6 (adapter/tooling robustness), Gemma4
(prompt quality) — synthesized by the main session. No debate round; ticket
#12 tracks a full re-run.

## Fixed immediately (commit a0aec81)
- **P0** resume replayed the round's last completed turn (turn pointer never
  wrapped; turn_start now consumed per turn) — codex
- **P0** negative/zero unit counts and purchase quantities accepted — codex
- **P0** provider failing all retries crashed the game; now an announced
  no-op decision — qwen
- **Rules** Suez/Panama canal control enforced (edge-gated BFS) — glm
- **Rules** neutral territories: no transit; entry pays 3 IPC + claims — glm
- atomic flag-file writes (dice/actions/thinking/minds) — codex
- schema-degrade only on real response_format rejections — qwen
- malformed casualty responses tolerated; mobilize auto-places stranded
  purchases; stale DO THIS cleared per turn — codex
- battle-log parse cached by file size (was full re-parse every 2s) — gemini
- photo verifier KeyError guard + stricter territory matching — qwen
- AA casualty prompts name the cause — gemma

## Discarded as false positives (seat couldn't see game.py)
income-during-captured-capital, econ victory check, amphib retreat ban,
joint defender fire, factory placement rules — all implemented in game.py;
"_trim_history keeps only 4 messages" misreads the 120k-char budget floor.

## Ticketed (milestone: Panel Consensus (Jun 2026))
Battleship support shot · strategic bombing · multi-defender casualty
allocation · transport capacity/unload-ends-move · carrier capacity/launch ·
blitz flip · dice-form cancel · pidfile · smarter sim bot · gamelog isolation ·
vision retry · full ultrapanel re-run.

## Praised (gemini)
DO THIS/Done physical-digital bridge, battle board, war-council eavesdropping,
thinking indicators, photo verification — "a spectacular blend of physical
board gaming and AI agent observability."

Raw seat outputs: .scratch/review/*.out (session-local).
