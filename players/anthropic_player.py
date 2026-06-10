"""Anthropic adapter — claude-fable-5 with structured outputs.

Fable specifics: thinking is always on (omit the parameter), no temperature,
effort via output_config, check stop_reason == "refusal" before reading
content, cache_control on the system prompt so the growing history is cheap.
"""
import os

import anthropic

from players.base import Player


class AnthropicPlayer(Player):
    def __init__(self, power, cfg, system_prompt):
        super().__init__(power, cfg, system_prompt)
        self.client = anthropic.Anthropic(api_key=os.environ[cfg["api_key_env"]])
        self.history = []

    def decide(self, prompt, schema):
        self.history.append({"role": "user", "content": prompt})
        response = self.client.messages.create(
            model=self.cfg["model"],
            max_tokens=16000,
            output_config={
                "effort": self.cfg.get("effort", "high"),
                "format": {"type": "json_schema", "schema": schema},
            },
            system=[{
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=self.history,
        )
        if response.stop_reason == "refusal":
            # Shouldn't happen for a board game; surface it and let the
            # referee retry or sub in a different decision.
            raise RuntimeError(f"{self.power}: model declined the request")
        # Replay rule: append the full content (thinking blocks included,
        # unchanged) so the next turn is valid on the same model.
        self.history.append({"role": "assistant", "content": response.content})
        import json
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)
