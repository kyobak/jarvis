#!/usr/bin/env python3
"""Compatibility check for the deployment Mac (Intel, macOS 12 Monterey).

Stdlib only, so it runs on a fresh python.org install before anything else:

    python3 scripts/check_env.py            # system checks only
    python3 scripts/check_env.py --install  # also try each candidate package in a scratch venv
    python3 scripts/check_env.py --install --write   # append results to docs/decisions.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH_VENV = ROOT / ".check-venv"

# (pip spec, smoke-test code run inside the scratch venv; prints a short detail line)
CANDIDATES: list[tuple[str, str]] = [
    # onnxruntime >= 1.20 needs macOS 13; 1.19.x is the last for Monterey on Intel.
    ("onnxruntime<1.20", "import onnxruntime as o; print(o.__version__)"),
    (
        "opencv-contrib-python",
        "import cv2; print(cv2.__version__, 'YuNet' if hasattr(cv2, 'FaceDetectorYN') else 'no-YuNet',"
        " 'SFace' if hasattr(cv2, 'FaceRecognizerSF') else 'no-SFace',"
        " 'LBF' if hasattr(cv2, 'face') else 'no-LBF')",
    ),
    ("mediapipe", "import mediapipe as mp; print(mp.__version__)"),
    (
        "openwakeword",
        "from openwakeword.model import Model; import openwakeword.utils as u;"
        " getattr(u, 'download_models', lambda **k: None)(model_names=['hey_jarvis']);"
        " print('hey_jarvis OK')",
    ),
    ("webrtcvad-wheels", "import webrtcvad; v = webrtcvad.Vad(2); print('ok')"),
    ("sounddevice", "import sounddevice as sd; print(len(sd.query_devices()), 'devices')"),
    ("faster-whisper", "import faster_whisper, ctranslate2; print(faster_whisper.__version__, 'ct2', ctranslate2.__version__)"),
    # 1.2.0 is the last release with Intel macOS wheels.
    ("pywhispercpp<1.3", "import pywhispercpp; print('ok')"),
    ("pyobjc-framework-Speech", "import Speech; print(Speech.SFSpeechRecognizer.supportedLocales().count(), 'locales')"),
    ("pywebview", "import webview; print(webview.__version__ if hasattr(webview, '__version__') else 'ok')"),
]


def sh(cmd: list[str], timeout: float = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def sysctl(name: str) -> str:
    code, out = sh(["sysctl", "-n", name])
    return out if code == 0 else ""


def system_checks() -> list[tuple[str, str, str]]:
    """Returns (item, result, note) rows."""
    rows: list[tuple[str, str, str]] = []
    mac = platform.mac_ver()[0] or "n/a"
    rows.append(("macOS", mac, "대상: 12.x Monterey"))
    rows.append(("아키텍처", platform.machine(), "대상: x86_64"))
    cpu = sysctl("machdep.cpu.brand_string") or platform.processor()
    rows.append(("CPU", cpu or "n/a", ""))
    leaf7 = sysctl("machdep.cpu.leaf7_features")
    if leaf7:
        rows.append(("AVX2", "OK" if "AVX2" in leaf7.split() else "없음", "whisper 계열 속도에 영향"))
    mem = sysctl("hw.memsize")
    if mem.isdigit():
        rows.append(("RAM", f"{int(mem) / 2**30:.0f} GB", ""))
    py_ok = sys.version_info[:2] == (3, 12)
    rows.append(("Python", platform.python_version(), "OK" if py_ok else "3.12 권장 (python.org)"))
    rows.append(("uv", shutil.which("uv") or "없음", "권장"))
    claude = shutil.which("claude")
    major = int(mac.split(".")[0]) if mac[:1].isdigit() else 0
    if sys.platform == "darwin" and major and major < 13:
        rows.append(("Claude Code", "지원 안 됨", "macOS 13+ 필요 → llm.backend: api 또는 off"))
    elif claude:
        code, ver = sh([claude, "--version"])
        rows.append(("Claude Code", ver.splitlines()[0] if code == 0 and ver else "실행 실패", "llm.backend: claude_code"))
    else:
        rows.append(("Claude Code", "없음", "구독으로 쓰려면 설치 필요 (docs/setup.md 3장)"))

    if sys.platform == "darwin":
        code, voices = sh(["say", "-v", "?"])
        yuna = code == 0 and any(line.startswith("Yuna") for line in voices.splitlines())
        rows.append(("TTS 음성 Yuna", "OK" if yuna else "없음", "시스템 설정 > 손쉬운 사용 > 음성 콘텐츠에서 추가"))
        spotify = Path("/Applications/Spotify.app")
        if spotify.exists():
            _, ver = sh(["defaults", "read", str(spotify / "Contents/Info"), "CFBundleShortVersionString"])
            rows.append(("Spotify 앱", ver or "설치됨", "AppleScript 제어 가능 여부는 Phase 5에서 확인"))
        else:
            rows.append(("Spotify 앱", "없음", "미설치 시 Web API 재생 제어로 대체"))
    return rows


def ensure_venv() -> Path:
    py = SCRATCH_VENV / "bin" / "python"
    if not py.exists():
        venv.EnvBuilder(with_pip=True, clear=True).create(SCRATCH_VENV)
    return py


def install(py: Path, spec: str) -> tuple[bool, str]:
    uv = shutil.which("uv")
    cmd = [uv, "pip", "install", "--python", str(py), spec] if uv else [str(py), "-m", "pip", "install", "-q", spec]
    code, out = sh(cmd, timeout=900)
    if code != 0:
        last = [line for line in out.splitlines() if line.strip()][-3:]
        return False, " / ".join(last)[:300]
    return True, ""


def package_checks() -> list[tuple[str, str, str]]:
    py = ensure_venv()
    rows: list[tuple[str, str, str]] = []
    for spec, smoke in CANDIDATES:
        print(f"  … {spec}", flush=True)
        ok, err = install(py, spec)
        if not ok:
            rows.append((spec, "설치 실패", err))
            continue
        code, out = sh([str(py), "-c", smoke], timeout=120)
        detail = out.splitlines()[-1] if out else ""
        rows.append((spec, "OK" if code == 0 else "import 실패", detail[:200]))
    return rows


def render(title: str, rows: list[tuple[str, str, str]]) -> str:
    lines = [f"### {title}", "", "| 항목 | 결과 | 비고 |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c.replace('|', '/')} |" for a, b, c in rows]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--install", action="store_true", help="try installing candidate packages in .check-venv")
    ap.add_argument("--write", action="store_true", help="append the report to docs/decisions.md")
    ap.add_argument("--json", action="store_true", help="print raw JSON instead of markdown")
    args = ap.parse_args()

    host = platform.node() or "unknown"
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    print("시스템 확인 중…", flush=True)
    sys_rows = system_checks()
    pkg_rows = package_checks() if args.install else []

    if args.json:
        print(json.dumps({"system": sys_rows, "packages": pkg_rows}, ensure_ascii=False, indent=2))
        return 0

    report = f"\n## 환경 체크 — {host} ({stamp})\n\n" + render("시스템", sys_rows)
    if pkg_rows:
        report += "\n" + render("패키지 (설치 + import)", pkg_rows)
    print(report)

    if args.write:
        with open(ROOT / "docs" / "decisions.md", "a", encoding="utf-8") as f:
            f.write(report)
        print("→ docs/decisions.md 에 기록했어요.")
    if args.install:
        print(f"(테스트용 가상환경 {SCRATCH_VENV.name}/ 는 확인 후 지워도 돼요.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
