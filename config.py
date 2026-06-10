"""Game configuration: who plays whom, rules toggles, table settings."""

# --- Rules toggles (locked decisions) -------------------------------------
WEAPONS_DEVELOPMENT = True   # classic tech chart: 5 IPCs per research die
ECONOMIC_VICTORY = True      # Axis win at income threshold (end of full round)
ECON_VICTORY_AXIS_INCOME = 84  # VERIFY against your 2nd-edition rulebook
WAR_COUNCIL = True           # allies share notes between turns

DICE_MODE = "manual"         # "manual" = physical dice typed in; "auto" = script rolls
CASUALTY_CHOICE = "ai"       # always AI-chosen (locked decision)

# --- The roster (game one) -------------------------------------------------
# provider: "anthropic" | "openai_compat" | "stub"
# Local models go through the fleet gateway (one OpenAI-compatible endpoint
# fronting every box, with health + failover): http://gandalf.local:4000/v1.
# The "model" field is an intent, not a raw model id — the gateway owns the
# machine map. Live list: GET /v1/models. Key: export FLEET_API_KEY before
# running (export FLEET_API_KEY=$(cat ~/.config/fleet/key)); never hardcode it.
FLEET_BASE_URL = "http://gandalf.local:4000/v1"
# Frontier powers also go through the gateway: those routes ride Ben's
# existing subscriptions (ChatGPT/Codex, Claude plan, Gemini), so games cost
# $0 in API spend. Only env var needed for ALL five players: FLEET_API_KEY.
PLAYERS = {
    "germany": {
        "provider": "openai_compat",
        "model": "codex",                # GPT-5.x Codex via ChatGPT subscription
        "base_url": FLEET_BASE_URL,
        "api_key_env": "FLEET_API_KEY",
        "voice": "Daniel",
    },
    "japan": {
        # "fable" is free on the Claude plan through Jun 22, 2026; after that
        # it's metered — switch to "opus" (still $0 on subscription) then.
        "provider": "openai_compat",
        "model": "fable",                # Claude Fable 5 via Claude plan
        "base_url": FLEET_BASE_URL,
        "api_key_env": "FLEET_API_KEY",
        "voice": "Kyoko",
    },
    "uk": {
        "provider": "openai_compat",
        "model": "gemini",               # Gemini 3.1 Pro via subscription
        "base_url": FLEET_BASE_URL,
        "api_key_env": "FLEET_API_KEY",
        "voice": "Moira",  # Serena isn't installed on bens-mac; download it
                           # (System Settings → Spoken Content) to switch back
    },
    "ussr": {
        "provider": "openai_compat",
        "model": "code-glm",             # GLM-4.5-Air 106B on gandalf
        "base_url": FLEET_BASE_URL,
        "api_key_env": "FLEET_API_KEY",
        "voice": "Milena",
    },
    "usa": {
        # "big" shares gandalf with ussr's "code-glm" and they evict each
        # other (~35s model swap when the turn passes between them) — fine
        # for a physical-board pace. The locked roster wants Qwen3-235B
        # (reasoning > coder variants); if the swaps ever annoy, "code"
        # (Qwen3-Coder-Next 80B on pippen) is the swap-free compromise.
        "provider": "openai_compat",
        "model": "big",                  # Qwen3-235B-A22B on gandalf
        "base_url": FLEET_BASE_URL,
        "api_key_env": "FLEET_API_KEY",
        "voice": "Samantha",
    },
}

# --- Table settings ---------------------------------------------------------
SPEECH = True                # macOS `say`; auto-disabled if unavailable
SPEECH_RATE = 190
# Where the audio plays: an SSH target whose Mac speakers should speak
# (passwordless SSH required), or None for this machine. Falls back to
# local `say` automatically if the remote is unreachable.
SPEECH_HOST = "benfinklea@bens-mac.local"
STATE_FILE = "logs/state.json"
TRANSCRIPT = "logs/transcript.md"
SNAPSHOT_DIR = "logs/snapshots"
MAX_LEGALITY_RETRIES = 2     # re-asks after an illegal move before referee steps in
