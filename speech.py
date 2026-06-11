"""Table voice (macOS `say`, local or over SSH) + transcript log.

Speech is serialized through a lock file (one on the speaking machine), so
only one voice plays at a time even if several processes (game, demos,
tools) try to talk at once — overlapping `say` is unintelligible.
"""
import fcntl
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import config

LOCK_FILE = "/tmp/axis-allies-say.lock"

# What the voice says vs what the screen shows: fix TTS pronunciations
# ("USSR" reads as "us-er", aaGun is engine jargon).
SPOKEN_SUBS = [
    (re.compile(r"\bussr\b", re.IGNORECASE), "U.S.S.R."),
    (re.compile(r"\buk\b", re.IGNORECASE), "U.K."),
    (re.compile(r"\busa\b", re.IGNORECASE), "U.S.A."),
    (re.compile(r"\baagun(s?)\b", re.IGNORECASE), r"anti-aircraft gun\1"),
    (re.compile(r"\bIPCs\b"), "I.P.C.s"),
    (re.compile(r"\bIPC\b"), "I.P.C."),
]


def spoken_form(text):
    for pat, rep in SPOKEN_SUBS:
        text = pat.sub(rep, text)
    return text

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

    def note(self, text):
        """Transcript + log + screen, but silent — for per-phase reasoning
        so the table isn't speechified six times per turn."""
        print(f"  ▸ {text}")
        with self.transcript.open("a") as f:
            f.write(text + "\n\n")
        if self.on_speak:
            self.on_speak(text)

    def speak(self, text, voice=None):
        print(f"  ▸ {text}")
        with self.transcript.open("a") as f:
            f.write(text + "\n\n")
        if self.on_speak:
            self.on_speak(text)
        v = voice or self.voice
        text = spoken_form(text)
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
