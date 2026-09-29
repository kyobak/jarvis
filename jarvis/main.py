"""Entry point: `jarvis [run|stop|enroll] [--mock] [--no-window]`."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

from jarvis.core.config import REPO_ROOT, default_data_dir, load_config
from jarvis.core.instance import Instance, is_jarvis, port_in_use

log = logging.getLogger("jarvis")

LLM_CHOICES = ["openai_compat", "api", "claude_code", "off", "mock"]
STT_CHOICES = ["auto", "faster_whisper", "whisper_cpp", "apple", "mock"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="jarvis", description="Desk assistant HUD")
    p.add_argument("command", nargs="?", default="run", choices=["run", "stop", "enroll"])
    p.add_argument("--mock", action="store_true", help="fake camera, mic, and integrations (the AI stays real)")
    p.add_argument("--dev", action="store_true", help="enable developer shortcuts without mock mode")
    p.add_argument("--voice", choices=["real", "mock"], help="microphone/speaker (default: mock with --mock, else real)")
    p.add_argument("--vision", choices=["real", "mock", "off"], help="camera (default: mock with --mock, else real)")
    p.add_argument("--llm", choices=LLM_CHOICES, help="override llm.backend")
    p.add_argument("--stt", choices=STT_CHOICES, help="override voice.stt_engine")
    p.add_argument("--config", type=Path, help="path to config.yaml")
    p.add_argument("--no-window", action="store_true", help="server only; open the UI in a browser yourself")
    p.add_argument("--browser", action="store_true", help="with --no-window, open the default browser")
    p.add_argument("--windowed", action="store_true", help="native window but not fullscreen")
    p.add_argument("--port", type=int, help="override server port")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _exit_now(code: int) -> None:
    """Leave without waiting for worker threads (e.g. a model download) to finish."""
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from jarvis.core.logs import setup_logging

    setup_logging(verbose=args.verbose)
    load_dotenv(REPO_ROOT / ".env")

    config = load_config(args.config)
    if args.port:
        config.server.port = args.port
    host, port = config.server.host, config.server.port
    instance = Instance(default_data_dir(), host, port)

    if args.command == "stop":
        if instance.read_pid() is None and not is_jarvis(host, port):
            print("실행 중인 자비스가 없어요.")
            return 0
        ok = instance.stop_existing()
        print("자비스를 종료했어요." if ok else f"종료하지 못했어요. `lsof -i :{port}` 로 확인해 주세요.")
        return 0 if ok else 1

    if args.command == "enroll":
        from jarvis.vision.enroll import run_enroll

        return run_enroll(config)

    # One Jarvis at a time: replace a previous instance, refuse to fight a stranger for the port.
    if port_in_use(host, port) or instance.read_pid():
        if is_jarvis(host, port) or instance.read_pid():
            print("이미 실행 중인 자비스를 종료하고 새로 시작할게요…")
            if not instance.stop_existing():
                print(f"기존 자비스를 종료하지 못했어요. `uv run jarvis stop` 또는 `lsof -i :{port}` 로 확인해 주세요.")
                return 1
        else:
            print(
                f"포트 {port}를 다른 프로그램이 쓰고 있어요. `lsof -i :{port}` 로 어떤 프로그램인지 확인하거나,\n"
                f"`uv run jarvis --port 8766` 처럼 다른 포트로 실행해 주세요 (단, OAuth 연결은 8765 기준이에요)."
            )
            return 1

    import uvicorn

    from jarvis.core.app import JarvisApp
    from jarvis.server.app import create_app

    jarvis = JarvisApp(
        config, mock=args.mock, dev=args.dev, voice=args.voice, llm=args.llm, stt=args.stt, vision=args.vision
    )
    app = create_app(jarvis)
    url = f"http://{host}:{port}/"
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning", ws="websockets-sansio"))
    instance.claim()

    try:
        if args.no_window:
            log.info("serving UI at %s", url)
            if args.browser:
                threading.Timer(1.0, webbrowser.open, args=(url,)).start()
            server.run()
            return 0

        try:
            import webview
        except ImportError:
            log.warning("pywebview not available; falling back to the default browser")
            threading.Timer(1.0, webbrowser.open, args=(url,)).start()
            server.run()
            return 0

        # The GUI must own the main thread on macOS, so the server runs beside it.
        thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
        thread.start()
        while not server.started and thread.is_alive():
            threading.Event().wait(0.05)
        if not server.started:
            log.error("server failed to start")
            return 1

        webview.create_window(
            "Jarvis",
            url,
            fullscreen=config.ui.fullscreen and not args.windowed,
            width=1440,
            height=900,
            background_color="#030A12",
        )
        webview.start()
        server.should_exit = True
        thread.join(timeout=5)
        return 0
    finally:
        instance.release()


def run() -> None:
    code = main()
    _exit_now(code or 0)


if __name__ == "__main__":
    run()
