"""Single-instance handling: a pid file plus a health probe on the server port."""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def is_jarvis(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=1.5) as resp:
            return json.loads(resp.read().decode()).get("ok") is True
    except (OSError, ValueError):
        return False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_jarvis_process(pid: int) -> bool:
    """Guard against a stale pid file whose pid now belongs to another program."""
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    # Match the entry points, not any path that happens to contain "jarvis" (e.g. the venv).
    return bool(re.search(r"(/bin/jarvis|-m jarvis)(\s|$)", out.stdout))


def _pids_on_port(port: int) -> list[int]:
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids = [int(p) for p in out.stdout.split() if p.isdigit() and int(p) != os.getpid()]
    return [p for p in pids if _is_jarvis_process(p)]


class Instance:
    def __init__(self, data_dir: Path, host: str, port: int) -> None:
        self.pidfile = data_dir / "jarvis.pid"
        self.host = host
        self.port = port

    def read_pid(self) -> int | None:
        try:
            pid = int(self.pidfile.read_text().strip())
        except (OSError, ValueError):
            return None
        if pid == os.getpid() or not _alive(pid) or not _is_jarvis_process(pid):
            return None
        return pid

    def claim(self) -> None:
        self.pidfile.parent.mkdir(parents=True, exist_ok=True)
        self.pidfile.write_text(str(os.getpid()))

    def release(self) -> None:
        try:
            if self.pidfile.read_text().strip() == str(os.getpid()):
                self.pidfile.unlink()
        except OSError:
            pass

    def stop_existing(self, timeout: float = 8.0) -> bool:
        """Stop a running Jarvis. Returns True if the port is free afterwards."""
        pids = [p for p in [self.read_pid()] if p]
        if not pids and is_jarvis(self.host, self.port):
            pids = _pids_on_port(self.port)  # started before pid files existed
        for pid in pids:
            log.info("stopping previous Jarvis (pid %d)", pid)
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not port_in_use(self.host, self.port) and not any(_alive(p) for p in pids):
                return True
            time.sleep(0.2)
        for pid in pids:
            if _alive(pid):
                log.warning("pid %d ignored SIGTERM; killing", pid)
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        time.sleep(0.5)
        return not port_in_use(self.host, self.port)
