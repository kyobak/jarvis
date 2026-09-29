from datetime import time

import pytest
import yaml

from jarvis.core.config import Config, HourRange, REPO_ROOT, load_config


def test_example_config_is_valid():
    data = yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    cfg = Config.model_validate(data)
    assert cfg.user_name == "재원"
    assert cfg.server.port == 8765
    assert cfg.vision.active_hours.contains(time(1, 0))


def test_hour_range_wraps_midnight():
    r = HourRange.parse("22:00-06:00")
    assert r.contains(time(23, 0)) and r.contains(time(5, 59))
    assert not r.contains(time(6, 0)) and not r.contains(time(12, 0))


def test_hour_range_rejects_garbage():
    with pytest.raises(ValueError):
        HourRange.parse("nine to five")


def test_server_must_be_loopback():
    with pytest.raises(ValueError):
        Config.model_validate({"server": {"host": "0.0.0.0"}})


def test_partial_config_fills_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("user_name: 테스트\nllm:\n  max_tokens: 200\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.user_name == "테스트"
    assert cfg.llm.max_tokens == 200
    assert cfg.llm.default_model == "claude-haiku-4-5"
