"""Maps a base item to pathofexile.com/trade2's `type_filters.category`
option (e.g. "accessory.amulet") -- confirmed live to be the right way to
scope a search to "any base of this slot" (`query.type`, an exact base-type
name like "Agate Amulet", was tried first and rejected with "Unknown item
base type": this project's `BaseItemDef.name` values are CoE's *generic*
slot names, e.g. "Amulet", not real trade base-type names, so an exact-type
filter can never work against them).

Only `"Amulet" -> "accessory.amulet"` was actually confirmed against a real,
live search (2026-08-19, logged out, no POESESSID) -- everything else below
follows PoE's long-standing trade category taxonomy (unchanged across PoE1
and, as far as this spot check went, PoE2) but hasn't been individually
re-verified live. Matched by *exact* base name, not a prefix/substring --
tried substring matching first and it silently collapsed "One Hand Mace"/
"Two Hand Mace" onto the same (wrong) category, since trade splits one- and
two-handed variants of Axe/Mace/Sword into distinct categories.

Bases with no entry here (Waystones, Tablets, Charms, Flasks, Talisman) are
PoE2-specific or otherwise not confirmed at all -- `trade_category_for`
returns None rather than guessing, and every caller must treat that as
"search without a category filter" (broader, less precise, not a crash)."""
from __future__ import annotations

from poe2craft.data.loader import GameData
from poe2craft.domain.ids import BaseId

_BY_BASE_NAME: dict[str, str] = {
    "Amulet": "accessory.amulet",  # the one entry actually confirmed live
    "Belt": "accessory.belt",
    "Ring": "accessory.ring",
    "Emerald": "jewel",
    "Ruby": "jewel",
    "Sapphire": "jewel",
    "Jewel (Uncoloured)": "jewel",
    "Body Armour (STR)": "armour.chest",
    "Body Armour (DEX)": "armour.chest",
    "Body Armour (INT)": "armour.chest",
    "Body Armour (STR/DEX)": "armour.chest",
    "Body Armour (STR/INT)": "armour.chest",
    "Body Armour (DEX/INT)": "armour.chest",
    "Body Armour (STR/DEX/INT)": "armour.chest",
    "Boots (STR)": "armour.boots",
    "Boots (DEX)": "armour.boots",
    "Boots (INT)": "armour.boots",
    "Boots (STR/DEX)": "armour.boots",
    "Boots (STR/INT)": "armour.boots",
    "Boots (DEX/INT)": "armour.boots",
    "Boots (STR/DEX/INT)": "armour.boots",
    "Gloves (STR)": "armour.gloves",
    "Gloves (DEX)": "armour.gloves",
    "Gloves (INT)": "armour.gloves",
    "Gloves (STR/DEX)": "armour.gloves",
    "Gloves (STR/INT)": "armour.gloves",
    "Gloves (DEX/INT)": "armour.gloves",
    "Gloves (STR/DEX/INT)": "armour.gloves",
    "Helmet (STR)": "armour.helmet",
    "Helmet (DEX)": "armour.helmet",
    "Helmet (INT)": "armour.helmet",
    "Helmet (STR/DEX)": "armour.helmet",
    "Helmet (STR/INT)": "armour.helmet",
    "Helmet (DEX/INT)": "armour.helmet",
    "Helmet (STR/DEX/INT)": "armour.helmet",
    "Shield (STR)": "armour.shield",
    "Shield (DEX)": "armour.shield",
    "Shield (STR/DEX)": "armour.shield",
    "Shield (STR/INT)": "armour.shield",
    "Focus": "armour.focus",
    "Quiver": "weapon.quiver",
    "Bow": "weapon.bow",
    "Claw": "weapon.claw",
    "Crossbow": "weapon.crossbow",
    "Dagger": "weapon.dagger",
    "Flail": "weapon.flail",
    "Sceptre": "weapon.sceptre",
    "Spear": "weapon.spear",
    "One Hand Axe": "weapon.oneaxe",
    "Two Hand Axe": "weapon.twoaxe",
    "One Hand Mace": "weapon.onemace",
    "Two Hand Mace": "weapon.twomace",
    "One Hand Sword": "weapon.onesword",
    "Two Hand Sword": "weapon.twosword",
    "Wand": "weapon.wand",
    "Chaos Wand": "weapon.wand",
    "Fire Wand": "weapon.wand",
    "Ice Wand": "weapon.wand",
    "Lightning Wand": "weapon.wand",
    "Physical Wand": "weapon.wand",
    "Staff": "weapon.warstaff",
    "Warstaff": "weapon.warstaff",
    "Chaos Staff": "weapon.warstaff",
    "Fire Staff": "weapon.warstaff",
    "Ice Staff": "weapon.warstaff",
    "Lightning Staff": "weapon.warstaff",
    "Physical Staff": "weapon.warstaff",
}


def trade_category_for(gamedata: GameData, base_id: BaseId) -> str | None:
    return _BY_BASE_NAME.get(gamedata.bases[base_id].name)
