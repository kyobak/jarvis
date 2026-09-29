"""Microphone input as an async stream of 80 ms, 16 kHz, mono int16 frames."""

from __future__ import annotations

import array
import asyncio
import logging
import math
from typing import AsyncIterator, Protocol

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1_280  # 80 ms — openWakeWord's native chunk size
FRAME_SEC = FRAME_SAMPLES / SAMPLE_RATE
QUEUE_FRAMES = 64


def rms_level(frame: bytes) -> float:
    """Loudness mapped to 0..1 (-60 dBFS → 0, -10 dBFS → 1)."""
    samples = array.array("h", frame)
    if not samples:
        return 0.0
    mean_sq = sum(s * s for s in samples) / len(samples)
    if mean_sq <= 0:
        return 0.0
    dbfs = 10 * math.log10(mean_sq / (32768.0**2))
    return max(0.0, min(1.0, (dbfs + 60) / 50))


def downsample(frame: bytes, factor: int) -> bytes:
    """Integer-factor decimation with a box filter (enough for speech at 48k → 16k)."""
    if factor == 1:
        return frame
    src = array.array("h", frame)
    out = array.array("h", (sum(src[i : i + factor]) // factor for i in range(0, len(src) - factor + 1, factor)))
    return out.tobytes()


class AudioSource(Protocol):
    state: str  # on | error | mock | off

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def frames(self) -> AsyncIterator[bytes]: ...


class MicStream:
    """Real microphone via sounddevice (PortAudio)."""

    def __init__(self, device: str | int | None = None) -> None:
        self.device = device
        self.state = "off"
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=QUEUE_FRAMES)
        self._stream = None
        self._factor = 1
        self._pending = b""

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            log.error("sounddevice unavailable: %s", e)
            self.state = "error"
            return

        def callback(indata, frames, time_info, status) -> None:  # runs on the PortAudio thread
            if status:
                log.debug("mic status: %s", status)
            loop.call_soon_threadsafe(self._push, bytes(indata))

        for rate in (SAMPLE_RATE, 48_000):
            try:
                self._factor = rate // SAMPLE_RATE
                self._stream = sd.RawInputStream(
                    samplerate=rate,
                    channels=1,
                    dtype="int16",
                    blocksize=FRAME_SAMPLES * self._factor,
                    device=self.device,
                    callback=callback,
                )
                self._stream.start()
                self.state = "on"
                log.info("microphone open at %d Hz", rate)
                return
            except Exception as e:  # PortAudio raises various error types
                log.warning("mic open at %d Hz failed: %s", rate, e)
                self._stream = None
        self.state = "error"

    def _push(self, chunk: bytes) -> None:
        data = self._pending + downsample(chunk, self._factor)
        size = FRAME_SAMPLES * 2
        while len(data) >= size:
            frame, data = data[:size], data[size:]
            if self._queue.full():
                self._queue.get_nowait()  # drop the oldest frame rather than lag
            self._queue.put_nowait(frame)
        self._pending = data

    async def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.state = "off"

    async def frames(self) -> AsyncIterator[bytes]:
        while True:
            yield await self._queue.get()


class MockMic:
    """Emits silent frames in real time so the voice loop runs without hardware."""

    def __init__(self) -> None:
        self.state = "mock"
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def frames(self) -> AsyncIterator[bytes]:
        silence = bytes(FRAME_SAMPLES * 2)
        while self._running:
            await asyncio.sleep(FRAME_SEC)
            yield silence
