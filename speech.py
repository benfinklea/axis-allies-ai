"""Table voice (macOS `say`) + transcript log."""
import shutil
import subprocess
from pathlib import Path

import config


class Table:
    def __init__(self):
        self.say_path = shutil.which("say") if config.SPEECH else None
        self.transcript = Path(config.TRANSCRIPT)
        self.transcript.parent.mkdir(parents=True, exist_ok=True)
        self.voice = None  # set per power by the game loop

    def speak(self, text, voice=None):
        print(f"  ▸ {text}")
        with self.transcript.open("a") as f:
            f.write(text + "\n\n")
        v = voice or self.voice
        if self.say_path:
            cmd = [self.say_path, "-r", str(config.SPEECH_RATE)]
            if v:
                cmd += ["-v", v]
            subprocess.run(cmd + [text], check=False)
