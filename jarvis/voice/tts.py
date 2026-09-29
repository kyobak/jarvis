"""Text-to-speech with macOS `say` (offline, free). Publishes a loudness envelope
while playing so the core's speaking waveform follows the actual voice."""

from __future__ import annotations

import array
import asyncio
import logging
import math
import re
import shutil
import tempfile
import wave
from pathlib import Path
from typing import Awaitable, Callable, Protocol

log = logging.getLogger(__name__)

LevelFn = Callable[[float], Awaitable[None]]
ENVELOPE_SEC = 0.05
RENDER_RATE = 22_050

_MARKDOWN = re.compile(r"[*_#`>|~\[\]]+")
_URL = re.compile(r"https?://\S+")
_SPACES = re.compile(r"\s+")


def speakable(text: str) -> str:
    """Strip formatting a model might emit despite instructions."""
    text = _URL.sub("", text)
    text = _MARKDOWN.sub("", text)
    text = re.sub(r"^\s*[-•·]\s+", "", text, flags=re.MULTILINE)
    return _SPACES.sub(" ", text).strip()


def envelope(path: Path) -> list[float]:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        data = array.array("h", w.readframes(w.getnframes()))
    step = max(1, int(rate * ENVELOPE_SEC))
    out = []
    for i in range(0, len(data), step):
        chunk = data[i : i + step]
        mean_sq = sum(s * s for s in chunk) / len(chunk)
        dbfs = 10 * math.log10(mean_sq / 32768.0**2) if mean_sq > 0 else -90
        out.append(max(0.0, min(1.0, (dbfs + 50) / 40)))
    return out


class TTS(Protocol):
    name: str

    async def speak(self, text: str, on_level: LevelFn) -> None: ...

    async def stop(self) -> None: ...


class SayTTS:
    name = "say"

    def __init__(self, voice: str = "Yuna", rate: int = 190) -> None:
        self.voice = voice
        self.rate = rate
        self._player: asyncio.subprocess.Process | None = None

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("say") and shutil.which("afplay"))

    async def speak(self, text: str, on_level: LevelFn) -> None:
        text = speakable(text)
        if not text:
            return
        with tempfile.TemporaryDirectory(prefix="jarvis-tts-") as tmp:
            path = Path(tmp) / "reply.wav"
            render = await asyncio.create_subprocess_exec(
                "say", "-v", self.voice, "-r", str(self.rate), "-o", str(path),
                "--file-format=WAVE", f"--data-format=LEI16@{RENDER_RATE}",
                stdin=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # Text goes through stdin so nothing in it can be read as a flag.
            _, err = await render.communicate(text.encode())
            if render.returncode != 0 or not path.exists():
                log.error("say failed: %s", err.decode(errors="replace").strip())
                return
            levels = envelope(path)
            self._player = await asyncio.create_subprocess_exec("afplay", str(path))
            loop = asyncio.get_running_loop()
            start = loop.time()
            try:
                while self._player.returncode is None:
                    i = int((loop.time() - start) / ENVELOPE_SEC)
                    await on_level(levels[i] if i < len(levels) else 0.0)
                    try:
                        await asyncio.wait_for(self._player.wait(), ENVELOPE_SEC)
                    except asyncio.TimeoutError:
                        pass
            finally:
                await on_level(0.0)
                self._player = None

    async def stop(self) -> None:
        if self._player and self._player.returncode is None:
            self._player.terminate()


class MockTTS:
    """Silent; animates a plausible envelope for as long as the sentence would take."""

    name = "mock"

    def __init__(self, sec_per_char: float = 0.085) -> None:
        self.sec_per_char = sec_per_char
        self._stopped = asyncio.Event()

    async def speak(self, text: str, on_level: LevelFn) -> None:
        text = speakable(text)
        self._stopped.clear()
        duration = 0.4 + len(text) * self.sec_per_char
        t = 0.0
        while t < duration and not self._stopped.is_set():
            await on_level(round(0.2 + 0.6 * abs(math.sin(t * 6.5)), 3))
            await asyncio.sleep(ENVELOPE_SEC)
            t += ENVELOPE_SEC
        await on_level(0.0)

    async def stop(self) -> None:
        self._stopped.set()
