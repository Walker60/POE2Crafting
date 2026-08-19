"""TradeSettingsStore's update/current round-trip -- including the
regression this was specifically designed to avoid: updating one field must
never silently persist the *other* field's env-var-only value into the
plaintext settings file."""
import json

import pytest

from poe2craft.pricing.settings_store import TradeSettingsStore


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("POE2CRAFT_POESESSID", raising=False)
    monkeypatch.delenv("POE2CRAFT_TRADE_LEAGUE", raising=False)


def test_update_then_current_round_trips(tmp_path):
    store = TradeSettingsStore(tmp_path / "settings.json")
    store.update(league="Standard", poesessid="cookie123")

    config = store.current()
    assert config.league == "Standard"
    assert config.poesessid == "cookie123"


def test_updating_league_alone_does_not_write_an_env_only_poesessid_to_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2CRAFT_POESESSID", "envcookie")  # never saved via the UI
    store = TradeSettingsStore(tmp_path / "settings.json")

    store.update(league="Standard", poesessid=None)  # only touching league

    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["poesessid"] is None  # not "envcookie" -- the env value must never leak into the file
    # ...but the *effective* config still resolves it from the environment.
    assert store.current().poesessid == "envcookie"


def test_clear_poesessid_removes_it_even_if_previously_saved(tmp_path):
    store = TradeSettingsStore(tmp_path / "settings.json")
    store.update(league="Standard", poesessid="cookie123")
    store.update(league=None, poesessid=None, clear_poesessid=True)

    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["poesessid"] is None
    assert raw["league"] == "Standard"  # unrelated field left untouched


def test_update_with_no_fields_given_leaves_existing_saved_values_untouched(tmp_path):
    store = TradeSettingsStore(tmp_path / "settings.json")
    store.update(league="Standard", poesessid="cookie123")
    store.update(league=None, poesessid=None)

    config = store.current()
    assert config.league == "Standard"
    assert config.poesessid == "cookie123"
