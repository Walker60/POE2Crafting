"""normalize() + build_mod_stat_mapping()'s exact-after-normalization
matching, and the report-don't-crash posture on genuine mismatches."""
import pytest

from poe2craft.domain.ids import ModId
from poe2craft.domain.mods import Affix, ModCategory, ModDef
from poe2craft.pricing.stat_matching import StatEntry, build_mod_stat_mapping, normalize, parse_stats_catalog


def _mod(mid: str, name: str) -> ModDef:
    return ModDef(id=ModId(mid), name=name, affix=Affix.PREFIX, category=ModCategory.NORMAL, group_keys=frozenset({mid}))


def test_normalize_collapses_placeholders_and_case():
    assert normalize("#% increased Armour") == "# increased armour"
    assert normalize("+# to maximum Life") == "# to maximum life"


def test_normalize_treats_instantiated_numbers_the_same_as_a_placeholder():
    assert normalize("12% increased Armour") == normalize("#% increased Armour")


def test_build_mod_stat_mapping_matches_on_normalized_text():
    mods = {ModId("m1"): _mod("m1", "#% increased Armour")}
    stats = [StatEntry(id="explicit.stat_1", text="#% increased Armour")]
    mapping, unmatched = build_mod_stat_mapping(mods, stats)
    assert mapping == {ModId("m1"): "explicit.stat_1"}
    assert unmatched == []


def test_build_mod_stat_mapping_reports_unmatched_rather_than_guessing():
    mods = {ModId("m1"): _mod("m1", "Some Totally Novel Wording")}
    stats = [StatEntry(id="explicit.stat_1", text="#% increased Armour")]
    mapping, unmatched = build_mod_stat_mapping(mods, stats)
    assert mapping == {}
    assert unmatched == [ModId("m1")]


def test_parse_stats_catalog_flattens_groups():
    raw = {
        "result": [
            {"id": "explicit", "entries": [{"id": "explicit.stat_1", "text": "#% increased Armour"}]},
            {"id": "implicit", "entries": [{"id": "implicit.stat_2", "text": "+# to Strength"}]},
        ]
    }
    entries = parse_stats_catalog(raw)
    assert {e.id for e in entries} == {"explicit.stat_1", "implicit.stat_2"}


def test_parse_stats_catalog_rejects_unexpected_shape():
    with pytest.raises(ValueError):
        parse_stats_catalog({"nope": "wrong shape"})
