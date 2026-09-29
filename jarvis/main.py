"""Entry point: `jarvis [--mock] [--no-window]`."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from jarvis.core.app import JarvisApp
from jarvis.core.config import REPO_ROOT, load_config
from jarvis.server.app import create_app

log = logging.getLogger("jarvis")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="jarvis", description="Desk assistant HUD")
    p.add_argument("command", nargs="?", default="run", choices=["run", "enroll"])
    p.add_argument("--mock", action="store_true", help="fake camera, mic, and integrations")
    p.add_argument("--dev", action="store_true", help="enable developer shortcuts without mock mode")
    p.add_argument("--voice", choices=["real", "mock"], help="microphone/speaker (default: mock with --mock, else real)")
    p.add_argument("--llm", choices=["claude_code", "api", "off", "mock"], help="override llm.backend")
    p.add_argument(
        "--stt", choices=["auto", "faster_whisper", "whisper_cpp", "apple", "mock"], help="override voice.stt_engine"
    )
    p.add_argument("--config", type=Path, help="path to config.yaml")
    p.add_argument("--no-window", action="store_true", help="server only; open the UI in a browser yourself")
    p.add_argument("--browser", action="store_true", help="with --no-window, open the default browser")
    p.add_argument("--windowed", action="store_true", help="native window but not fullscreen")
    p.add_argument("--port", type=int, help="override server port")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    load_dotenv(REPO_ROOT / ".env")

    if args.command == "enroll":
        print("얼굴 등록은 Phase 4에서 추가될 예정이에요.")
        return 1

    config = load_config(args.config)
    if args.port:
        config.server.port = args.port
    jarvis = JarvisApp(config, mock=args.mock, dev=args.dev, voice=args.voice, llm=args.llm, stt=args.stt)
    app = create_app(jarvis)
    url = f"http://{config.server.host}:{config.server.port}/"

    server = uvicorn.Server(
        uvicorn.Config(app, host=config.server.host, port=config.server.port, log_level="warning", ws="websockets-sansio")
    )

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


if __name__ == "__main__":
    sys.exit(main())
