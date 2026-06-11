"""OpenAI-compatible adapter: ChatGPT, Gemini (OpenAI-compat endpoint),
Ollama/LM Studio/vLLM local models. JSON enforced by response_format where
the server supports it, with prompt + repair fallback everywhere."""
import json
import os

from openai import OpenAI

from players.base import Player
from players import repair


class OpenAICompatPlayer(Player):
    def __init__(self, power, cfg, system_prompt):
        super().__init__(power, cfg, system_prompt)
        self.client = OpenAI(
            base_url=cfg["base_url"],
            api_key=os.environ.get(cfg.get("api_key_env", ""), "local"),
        )
        self.history = [{"role": "system", "content": system_prompt}]
        self.supports_schema = True  # optimistic; degrade on first failure

    # Subscription routes on the gateway pass prompts as CLI args, which
    # the OS caps in size — keep total history under this many characters
    # by dropping the oldest exchanges (system prompt always survives).
    HISTORY_CHAR_BUDGET = 120_000

    def _trim_history(self):
        def total():
            return sum(len(str(m.get("content", ""))) for m in self.history)
        while total() > self.HISTORY_CHAR_BUDGET and len(self.history) > 4:
            del self.history[1]  # oldest non-system message

    def _request(self, messages, schema):
        kwargs = dict(model=self.cfg["model"], messages=messages)
        if self.supports_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "decision", "schema": schema, "strict": True},
            }
        return self.client.chat.completions.create(**kwargs)

    def decide(self, prompt, schema):
        ask = (f"{prompt}\n\nRespond with ONLY a JSON object matching this "
               f"schema (no prose, no code fences):\n{json.dumps(schema)}")
        self.history.append({"role": "user", "content": ask})
        self._trim_history()
        try:
            resp = self._request(self.history, schema)
        except Exception:
            if not self.supports_schema:
                raise
            self.supports_schema = False  # server rejected response_format
            resp = self._request(self.history, schema)
        text = resp.choices[0].message.content
        self.history.append({"role": "assistant", "content": text})
        try:
            return repair.parse(text)
        except ValueError as e:
            # one re-ask with the error, then give up to the referee
            self.history.append({"role": "user", "content":
                                 f"Your reply was not valid JSON ({e}). "
                                 f"Reply again with only the JSON object."})
            resp = self._request(self.history, schema)
            text = resp.choices[0].message.content
            self.history.append({"role": "assistant", "content": text})
            return repair.parse(text)
