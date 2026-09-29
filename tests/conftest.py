import pytest

from jarvis.core.app import JarvisApp
from jarvis.core.config import Config


@pytest.fixture
def mock_app(tmp_path):
    return JarvisApp(Config(), mock=True, db_path=str(tmp_path / "jarvis.db"))
