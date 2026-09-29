import os
import subprocess
import sys

from jarvis.core.instance import Instance, port_in_use


def test_stale_pidfile_for_unrelated_process_is_ignored(tmp_path):
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        inst = Instance(tmp_path, "127.0.0.1", 1)
        inst.pidfile.write_text(str(sleeper.pid))
        assert inst.read_pid() is None  # alive, but not a jarvis process: never signal it
        assert sleeper.poll() is None
    finally:
        sleeper.kill()
        sleeper.wait()


def test_claim_and_release(tmp_path):
    inst = Instance(tmp_path, "127.0.0.1", 1)
    inst.claim()
    assert inst.pidfile.read_text() == str(os.getpid())
    inst.release()
    assert not inst.pidfile.exists()


def test_port_probe():
    assert port_in_use("127.0.0.1", 1) is False
