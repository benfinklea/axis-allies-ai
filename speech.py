"""Table voice (macOS `say`, local or over SSH) + transcript log.

Speech is serialized through a lock file (one on the speaking machine), so
only one voice plays at a time even if several processes (game, demos,
tools) try to talk at once — overlapping `say` is unintelligible.
"""
import fcntl
import shlex
import shutil
import subprocess
from pathlib import Path

import config

LOCK_FILE = "/tmp/axis-allies-say.lock"

# Runs on the remote Mac: take the lock, then speak. Serializes every
# speaker that goes through this wrapper, across processes and SSH sessions.
REMOTE_WRAPPER = (
    "import fcntl,subprocess,sys;"
    "f=open('" + LOCK_FILE + "','w');"
    "fcntl.flock(f,fcntl.LOCK_EX);"
    "subprocess.run(['say']+sys.argv[1:])"
)


class Table:
    def __init__(self):
        self.say_path = shutil.which("say") if config.SPEECH else None
        self.remote = getattr(config, "SPEECH_HOST", None) if config.SPEECH else None
        self.transcript = Path(config.TRANSCRIPT)
        self.transcript.parent.mkdir(parents=True, exist_ok=True)
        self.voice = None  # set per power by the game loop
        self.on_speak = None  # optional hook: the game log listens here

    def _flags(self, text, voice):
        flags = ["-r", str(config.SPEECH_RATE)]
        if voice:
            flags += ["-v", voice]
        return flags + [text]

    def speak(self, text, voice=None):
        print(f"  ▸ {text}")
        with self.transcript.open("a") as f:
            f.write(text + "\n\n")
        if self.on_speak:
            self.on_speak(text)
        v = voice or self.voice
        if self.remote:
            cmd = (["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3",
                    self.remote, "python3", "-c", shlex.quote(REMOTE_WRAPPER)]
                   + [shlex.quote(a) for a in self._flags(text, v)])
            if subprocess.run(cmd, check=False,
                              stderr=subprocess.DEVNULL).returncode == 0:
                return
            # remote box unreachable — fall through to this machine's voice
        if self.say_path:
            with open(LOCK_FILE, "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                subprocess.run([self.say_path] + self._flags(text, v),
                               check=False)
