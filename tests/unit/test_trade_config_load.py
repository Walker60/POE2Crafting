"""TradeConfig.load()'s precedence: environment variables as the baseline,
overlaid by a local settings file (what the web UI's Trade settings panel
writes) -- see poe2craft.pricing.settings_store for the write side."""
import json

import pytest

from poe2craft.pricing.config import TradeConfig


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("POE2CRAFT_POESESSID", raising=False)
    monkeypatch.delenv("POE2CRAFT_TRADE_LEAGUE", raising=False)


def test_load_falls_back_to_env_when_no_file_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2CRAFT_TRADE_LEAGUE", "Standard")
    monkeypatch.setenv("POE2CRAFT_POESESSID", "envcookie")
    config = TradeConfig.load(tmp_path / "does-not-exist.json")
    assert config.league == "Standard"
    assert config.poesessid == "envcookie"


def test_load_prefers_the_saved_file_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2CRAFT_TRADE_LEAGUE", "Standard")
    monkeypatch.setenv("POE2CRAFT_POESESSID", "envcookie")
    path = tmp_path / "trade_settings.json"
    path.write_text(json.dumps({"league": "HardcoreLeague", "poesessid": "uicookie"}), encoding="utf-8")

    config = TradeConfig.load(path)
    assert config.league == "HardcoreLeague"
    assert config.poesessid == "uicookie"


def test_load_falls_back_to_env_for_a_field_the_file_leaves_null(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2CRAFT_TRADE_LEAGUE", "Standard")
    monkeypatch.setenv("POE2CRAFT_POESESSID", "envcookie")
    path = tmp_path / "trade_settings.json"
    path.write_text(json.dumps({"league": "HardcoreLeague", "poesessid": None}), encoding="utf-8")

    config = TradeConfig.load(path)
    assert config.league == "HardcoreLeague"
    assert config.poesessid == "envcookie"  # cleared in the file -- falls back, not "no credential at all"


def test_load_tolerates_a_corrupt_settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2CRAFT_TRADE_LEAGUE", "Standard")
    path = tmp_path / "trade_settings.json"
    path.write_text("not valid json{{{", encoding="utf-8")

    config = TradeConfig.load(path)
    assert config.league == "Standard"  # degrades to env rather than raising
