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
# Local boxes: fill in base_url once the LAN hostnames/ports are known
# (e.g. http://gandalf.local:11434/v1 for Ollama's OpenAI-compatible API).
PLAYERS = {
    "germany": {
        "provider": "openai_compat",
        "model": "gpt-5.2",            # set to your current ChatGPT API model
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "voice": "Daniel",
    },
    "japan": {
        "provider": "anthropic",
        "model": "claude-fable-5",
        "effort": "high",
        "api_key_env": "ANTHROPIC_API_KEY",
        "voice": "Kyoko",
    },
    "uk": {
        "provider": "openai_compat",
        "model": "gemini-2.5-pro",      # set to your current Gemini model
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
        "voice": "Serena",
    },
    "ussr": {
        "provider": "openai_compat",
        "model": "glm-4.5-air",
        "base_url": "http://FILL-ME-IN:11434/v1",   # Gandalf? Frodo? Pippin?
        "api_key_env": "LOCAL_API_KEY",  # often unused; "ollama" works
        "voice": "Milena",
    },
    "usa": {
        "provider": "openai_compat",
        "model": "qwen3-235b",
        "base_url": "http://FILL-ME-IN:11434/v1",
        "api_key_env": "LOCAL_API_KEY",
        "voice": "Samantha",
    },
}

# --- Table settings ---------------------------------------------------------
SPEECH = True                # macOS `say`; auto-disabled if unavailable
SPEECH_RATE = 190
STATE_FILE = "logs/state.json"
TRANSCRIPT = "logs/transcript.md"
SNAPSHOT_DIR = "logs/snapshots"
MAX_LEGALITY_RETRIES = 2     # re-asks after an illegal move before referee steps in
