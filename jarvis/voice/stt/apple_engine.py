"""Apple Speech framework (SFSpeechRecognizer), on-device when the OS supports it for ko-KR.

Runs in a helper subprocess: macOS may kill a process that requests speech-recognition
permission without a usage description, and that must not take Jarvis down with it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading

from jarvis.voice.stt.base import pcm_to_wav

TIMEOUT_SEC = 20


class AppleSpeechEngine:
    name = "apple"

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def check(self) -> None:
        if sys.platform != "darwin":
            raise ImportError("Apple Speech is macOS-only")
        import Speech  # noqa: F401

    def load(self) -> None:
        self._ensure()

    def _ensure(self) -> subprocess.Popen[str]:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "jarvis.voice.stt.apple_worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        return self._proc

    def transcribe(self, pcm16: bytes) -> str:
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(pcm_to_wav(pcm16))
            with self._lock:
                proc = self._ensure()
                assert proc.stdin and proc.stdout
                proc.stdin.write(json.dumps({"path": path}) + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
            if not line:
                raise RuntimeError("apple speech worker exited (permission denied or crashed)")
            reply = json.loads(line)
            if "error" in reply:
                raise RuntimeError(reply["error"])
            return reply["text"].strip()
        finally:
            os.unlink(path)
