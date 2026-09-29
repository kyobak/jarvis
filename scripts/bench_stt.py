#!/usr/bin/env python3
"""Benchmark STT engines on short Korean commands (plan §13).

    uv run python scripts/bench_stt.py --synth            # generate test audio with `say -v Yuna`
    uv run python scripts/bench_stt.py --record           # or read the phrases aloud yourself
    uv run python scripts/bench_stt.py --write            # run all installed engines, log to docs/decisions.md
    uv run python scripts/bench_stt.py --engines faster_whisper:base faster_whisper:small

Each engine runs in its own subprocess so a crash (or a macOS permission kill) cannot
take the whole run down, and so memory can be measured per engine.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import re
import resource
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BENCH_DIR = ROOT / ".bench"
PHRASES = [
    "헤이 자비스 지금 몇 시야",
    "4시 반에 과제 제출하라고 알려줘",
    "30분 뒤에 빨래 꺼내라고 해줘",
    "오늘 일정 뭐야",
    "내일 오전에 뭐 있어",
    "잔잔한 재즈 틀어줘",
    "다음 곡",
    "집중 모드 50분 시작해줘",
    "메일 온 거 있어",
    "30분만 잘게",
]
DEFAULT_ENGINES = ["faster_whisper:base", "faster_whisper:small", "whisper_cpp:small", "apple:-"]


def normalize(text: str) -> str:
    return re.sub(r"[\s.,!?~'\"“”]", "", text).lower()


def cer(ref: str, hyp: str) -> float:
    a, b = normalize(ref), normalize(hyp)
    if not a:
        return 0.0 if not b else 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / len(a)


def wav_paths() -> list[Path]:
    return [BENCH_DIR / f"{i:02d}.wav" for i in range(len(PHRASES))]


def synth() -> None:
    BENCH_DIR.mkdir(exist_ok=True)
    for text, path in zip(PHRASES, wav_paths()):
        subprocess.run(
            ["say", "-v", "Yuna", "-o", str(path), "--file-format=WAVE", "--data-format=LEI16@16000", text],
            check=True,
        )
    print(f"{len(PHRASES)}개 음성 파일을 {BENCH_DIR.name}/ 에 만들었어요 (Yuna 합성음).")


def record() -> None:
    import sounddevice as sd

    BENCH_DIR.mkdir(exist_ok=True)
    for text, path in zip(PHRASES, wav_paths()):
        input(f"\n“{text}” — Enter를 누르고 4초 안에 읽어 주세요…")
        audio = sd.rec(int(4 * 16000), samplerate=16000, channels=1, dtype="int16")
        sd.wait()
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(audio.tobytes())
    print("녹음 완료.")


def read_pcm(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise SystemExit(f"{path} must be 16 kHz mono int16")
        frames = w.readframes(w.getnframes())
        return frames, w.getnframes() / 16000


def worker(engine: str, model: str, paths: list[str]) -> None:
    from jarvis.voice import stt

    eng = stt.create(engine, model if model != "-" else "small")
    eng.check()
    t0 = time.perf_counter()
    eng.load()
    load = time.perf_counter() - t0
    results = []
    for p in paths:
        pcm, dur = read_pcm(Path(p))
        t = time.perf_counter()
        text = eng.transcribe(pcm)
        results.append({"file": p, "text": text, "sec": time.perf_counter() - t, "audio_sec": dur})
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss / 2**20 if sys.platform == "darwin" else rss / 1024  # bytes on macOS, KiB on Linux
    print(json.dumps({"load_sec": load, "results": results, "peak_rss_mb": rss_mb}, ensure_ascii=False))


def run_engine(spec: str) -> dict:
    engine, _, model = spec.partition(":")
    cmd = [sys.executable, __file__, "--worker", engine, model or "-", *map(str, wav_paths())]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return {"spec": spec, "error": "timeout"}
    lines = [line for line in proc.stdout.splitlines() if line.startswith("{")]
    if proc.returncode != 0 or not lines:
        tail = (proc.stderr.strip().splitlines() or ["(no output — crashed?)"])[-1]
        return {"spec": spec, "error": tail[:160]}
    data = json.loads(lines[-1])
    data["spec"] = spec
    return data


def summarize(data: dict) -> list[str]:
    if "error" in data:
        return [data["spec"], "실패", "", "", "", "", data["error"]]
    res = data["results"]
    lat = [r["sec"] for r in res]
    errs = [cer(ref, r["text"]) for ref, r in zip(PHRASES, res)]
    exact = sum(e == 0 for e in errs)
    rtf = sum(r["sec"] for r in res) / sum(r["audio_sec"] for r in res)
    worst = max(zip(errs, PHRASES, res), key=lambda x: x[0])
    note = f"최악: “{worst[1]}” → “{worst[2]['text']}”" if worst[0] > 0 else ""
    return [
        data["spec"],
        f"{data['load_sec']:.1f}s",
        f"{sum(lat) / len(lat):.2f}s / {max(lat):.2f}s",
        f"{rtf:.2f}",
        f"{sum(errs) / len(errs) * 100:.1f}% ({exact}/{len(errs)} 정확)",
        f"{data['peak_rss_mb']:.0f} MB",
        note,
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synth", action="store_true", help="generate test audio with macOS say (Yuna)")
    ap.add_argument("--record", action="store_true", help="record the phrases with the microphone")
    ap.add_argument("--engines", nargs="+", default=DEFAULT_ENGINES, help="engine:model specs")
    ap.add_argument("--write", action="store_true", help="append the table to docs/decisions.md")
    ap.add_argument("--worker", nargs="+", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.worker:
        engine, model, *paths = args.worker
        return worker(engine, model, paths)
    if args.synth:
        return synth()
    if args.record:
        return record()
    if not all(p.exists() for p in wav_paths()):
        raise SystemExit("테스트 음성이 없어요. 먼저 --synth 또는 --record 를 실행하세요.")

    rows = []
    for spec in args.engines:
        print(f"  … {spec}", flush=True)
        rows.append(summarize(run_engine(spec)))

    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    header = ["엔진", "로드", "지연 평균/최대", "RTF", "CER", "메모리", "비고"]
    lines = [
        f"\n## STT 벤치마크 — {platform.node()} ({stamp})\n",
        "짧은 한국어 명령 10개. RTF = 처리 시간 ÷ 음성 길이 (1보다 작을수록 빠름).\n",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
        *("| " + " | ".join(c.replace("|", "/") for c in row) + " |" for row in rows),
    ]
    report = "\n".join(lines) + "\n"
    print(report)
    if args.write:
        with open(ROOT / "docs" / "decisions.md", "a", encoding="utf-8") as f:
            f.write(report)
        print("→ docs/decisions.md 에 기록했어요. 가장 좋은 엔진을 config.yaml 의 voice.stt_engine 에 적어 주세요.")


if __name__ == "__main__":
    main()
