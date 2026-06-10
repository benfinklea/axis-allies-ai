"""One structured JSONL file per game: roster, every AI prompt and reply,
every spoken line, every dice roll, and the result. This is the corpus for
studying games, judging the AIs, and trying different rosters.

File: logs/games/<game_id>.jsonl — game_id lives in the state, so a resumed
evening appends to the same file. Every event carries ts/round/turn/phase.
"""
import json
import time
from pathlib import Path


class GameLog:
    def __init__(self, state, directory):
        self.state = state
        self.path = Path(directory) / f"{state['game_id']}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, event):
        event["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        event["round"] = self.state.get("round")
        event["turn"] = self.state.get("turn")
        event["phase"] = self.state.get("phase")
        with self.path.open("a") as f:
            f.write(json.dumps(event) + "\n")

    def start(self, roster, rules):
        self._write({"e": "game_start", "roster": roster, "rules": rules})

    def say(self, text):
        self._write({"e": "say", "text": text})

    def ai(self, power, prompt, response):
        self._write({"e": "ai", "power": power, "prompt": prompt,
                     "response": response})

    def dice(self, label, rolls):
        self._write({"e": "dice", "label": label, "rolls": rolls})

    def result(self, winner, reason):
        self._write({"e": "result", "winner": winner, "reason": reason})

    def photo_check(self, photo_paths, report):
        self._write({"e": "photo_check",
                     "photos": [str(p) for p in photo_paths],
                     "report": report})
