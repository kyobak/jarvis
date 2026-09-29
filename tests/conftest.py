import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from jarvis.core.app import JarvisApp  # noqa: E402
from jarvis.core.config import Config  # noqa: E402


@pytest.fixture
def mock_app(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    return JarvisApp(Config(), mock=True, db_path=str(tmp_path / "jarvis.db"))
