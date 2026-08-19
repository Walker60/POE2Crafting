"""Parses the real vendored Craft of Exile snapshot and checks the invariants
that matter for solver correctness: clean referential integrity, and the exact
rollable-mod count confirmed by hand-inspecting the raw data this session
(225 prefix + 288 suffix = 513 of 1364 total modifiers)."""
from pathlib import Path

import pytest

from poe2craft.data.coe_parse import parse_coe, referential_integrity_report

VENDOR_PATH = Path(__file__).resolve().parents[2] / "data" / "vendor" / "coe_poe2_data.json"


@pytest.fixture(scope="module")
def parsed():
    raw = VENDOR_PATH.read_text(encoding="utf-8")
    return parse_coe(raw)


def test_no_parse_warnings(parsed):
    assert parsed["_warnings"] == []


def test_referential_integrity_clean(parsed):
    assert referential_integrity_report(parsed) == []


def test_total_and_rollable_mod_counts(parsed):
    mods = parsed["mods"]
    assert len(mods) == 1364
    rollable = [m for m in mods if m["category"] == "normal" and m["affix"] in ("prefix", "suffix")]
    assert len(rollable) == 513
    assert sum(1 for m in rollable if m["affix"] == "prefix") == 225
    assert sum(1 for m in rollable if m["affix"] == "suffix") == 288


def test_orphan_bases_are_patched_in(parsed):
    ids = {b["id"] for b in parsed["bases"]}
    for oid in ("51", "200", "230", "231", "232"):
        assert oid in ids


def test_orphan_base_68_is_deliberately_excluded(parsed):
    # 2026-08-19: id 68's entire mod pool is an exact subset of Ruby/Emerald/
    # Sapphire's own -- it grants nothing a real player couldn't already get
    # from one of those three named jewels, and has no name/art anywhere in
    # the vendored data. Excluded from `bases` (and its tier records dropped)
    # rather than surfaced as a pickable-but-meaningless "Unknown Base 68".
    ids = {b["id"] for b in parsed["bases"]}
    assert "68" not in ids
    assert not any(t["base_id"] == "68" for t in parsed["tiers"])


def test_base_200_is_identified_as_an_uncoloured_jewel(parsed):
    base_200 = next(b for b in parsed["bases"] if b["id"] == "200")
    assert base_200["name"] == "Jewel (Uncoloured)"
    assert base_200["bgroup_id"] == "9"  # Jewels bgroup, alongside Ruby/Emerald/Sapphire


def test_every_mod_has_a_group_key(parsed):
    # Every mod must have at least one exclusion-group key -- either a real
    # `modgroups` family or the synthetic solo key -- so it can never be
    # silently un-excludable from itself.
    for m in parsed["mods"]:
        assert m["group_keys"], m


def test_value_ranges_are_low_high_pairs(parsed):
    for t in parsed["tiers"][:2000]:
        for lo, hi in t["value_ranges"]:
            assert lo <= hi, t
