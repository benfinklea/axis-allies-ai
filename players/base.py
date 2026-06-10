"""Player interface + JSON schemas for every decision the AIs make."""

# Schemas are written to satisfy Anthropic structured outputs (every object
# carries additionalProperties:false, no min/max constraints) and double as
# the prompt-side contract for OpenAI-compatible providers.

def _obj(props, required=None):
    return {"type": "object", "properties": props,
            "required": required or list(props), "additionalProperties": False}

UNIT_COUNT = _obj({"type": {"type": "string"}, "count": {"type": "integer"}})

PURCHASE_SCHEMA = _obj({
    "purchases": {"type": "array", "items": _obj({
        "unit": {"type": "string"}, "quantity": {"type": "integer"}})},
    "research_dice": {"type": "integer"},
    "reasoning": {"type": "string"},
})

MOVES_SCHEMA = _obj({
    "moves": {"type": "array", "items": _obj({
        "units": {"type": "array", "items": UNIT_COUNT},
        "from": {"type": "string"},
        "to": {"type": "string"}})},
    "reasoning": {"type": "string"},
})

CASUALTY_SCHEMA = _obj({
    "remove": {"type": "array", "items": UNIT_COUNT},
})

PRESS_SCHEMA = _obj({
    "action": {"type": "string", "enum": ["press", "retreat"]},
    "retreat_to": {"type": "string"},
}, required=["action"])

PLACEMENT_SCHEMA = _obj({
    "placements": {"type": "array", "items": _obj({
        "unit": {"type": "string"}, "territory": {"type": "string"}})},
    "note_to_allies": {"type": "string"},
    "reasoning": {"type": "string"},
})

TECH_SCHEMA = _obj({
    "choice": {"type": "string"},
})

ASSESSMENT_SCHEMA = _obj({
    "assessment": {"type": "string"},
})


class Player:
    """One power's brain. Implementations keep their own running message
    history so strategy persists across the whole game."""

    def __init__(self, power, cfg, system_prompt):
        self.power = power
        self.cfg = cfg
        self.system_prompt = system_prompt

    def decide(self, prompt, schema):
        """Send prompt (str) with a JSON schema; return the parsed dict."""
        raise NotImplementedError
