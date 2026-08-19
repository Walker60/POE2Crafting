import { useEffect, useState } from 'react';
import { api, type ModOption } from '../api';

// The "ilvl" field means different things depending on `mode`: the exact
// tier they say is currently rolled ("current" mode) or the minimum tier
// they're willing to accept ("target" mode, 0 = any tier).
export interface SelectedMod {
  mod_id: string;
  ilvl: number;
}

interface Props {
  baseId: string | null;
  ilvl: number;
  mode: 'current' | 'target';
  value: SelectedMod[];
  onChange: (mods: SelectedMod[]) => void;
}

function formatValueRanges(ranges: [number, number][]): string {
  if (ranges.length === 0) return '';
  const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));
  return ranges.map(([lo, hi]) => (lo === hi ? fmt(lo) : `${fmt(lo)}-${fmt(hi)}`)).join(', ');
}

// Shared by the current-mods and target-mods pickers: a list of selected
// (mod, tier) rows plus a search-and-add row. The tier selector is always a
// dropdown built from that mod's real tier list from the catalog endpoint,
// never a freeform ilvl field -- this makes it structurally impossible for
// the UI to submit a (mod_id, ilvl) pair that doesn't correspond to a real
// tier (the backend's item_from_report validates defensively regardless).
export function ModPicker({ baseId, ilvl, mode, value, onChange }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ModOption[]>([]);
  const [modIndex, setModIndex] = useState<Record<string, ModOption>>({});
  const [searchError, setSearchError] = useState<string | null>(null);

  useEffect(() => {
    if (!baseId) {
      setResults([]);
      return;
    }
    const handle = setTimeout(() => {
      api
        .listMods(baseId, { ilvl, q: query || undefined })
        .then((mods) => {
          setSearchError(null);
          setResults(mods);
          setModIndex((prev) => {
            const next = { ...prev };
            for (const m of mods) next[m.mod_id] = m;
            return next;
          });
        })
        .catch((e) => setSearchError(String((e as Error).message ?? e)));
    }, 250);
    return () => clearTimeout(handle);
  }, [baseId, ilvl, query]);

  function addMod(mod: ModOption) {
    if (value.some((v) => v.mod_id === mod.mod_id)) return;
    const defaultIlvl = mode === 'target' ? 0 : (mod.tiers[0]?.ilvl ?? 0);
    onChange([...value, { mod_id: mod.mod_id, ilvl: defaultIlvl }]);
    setQuery('');
  }

  function removeMod(modId: string) {
    onChange(value.filter((v) => v.mod_id !== modId));
  }

  function setModIlvl(modId: string, newIlvl: number) {
    onChange(value.map((v) => (v.mod_id === modId ? { ...v, ilvl: newIlvl } : v)));
  }

  return (
    <div className="mod-picker">
      {value.length > 0 && (
        <ul className="mod-picker-selected">
          {value.map((v) => {
            const mod = modIndex[v.mod_id];
            const tierOptions =
              mode === 'target'
                ? [{ ilvl: 0, weight: 0, rank: 0, value_ranges: [] as [number, number][] }, ...(mod?.tiers ?? [])]
                : (mod?.tiers ?? []);
            return (
              <li key={v.mod_id}>
                <span className="mod-name">{mod?.name ?? v.mod_id}</span>
                <select value={v.ilvl} onChange={(e) => setModIlvl(v.mod_id, Number(e.target.value))}>
                  {tierOptions.map((t) => (
                    <option key={t.ilvl} value={t.ilvl}>
                      {mode === 'target' && t.ilvl === 0
                        ? 'any tier'
                        : `T${t.rank} (ilvl ${t.ilvl})${t.value_ranges.length ? ` — ${formatValueRanges(t.value_ranges)}` : ''}`}
                    </option>
                  ))}
                  {/* the currently-selected tier might not be in tierOptions yet
                      (e.g. this mod's catalog entry hasn't loaded for this ilvl) --
                      keep the select valid rather than silently resetting it */}
                  {!tierOptions.some((t) => t.ilvl === v.ilvl) && <option value={v.ilvl}>ilvl {v.ilvl}</option>}
                </select>
                <button type="button" onClick={() => removeMod(v.mod_id)}>
                  remove
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <input
        type="text"
        placeholder={baseId ? 'Search modifiers to add...' : 'Pick a base first'}
        value={query}
        disabled={!baseId}
        onChange={(e) => setQuery(e.target.value)}
      />
      {searchError && <p className="error">{searchError}</p>}
      {results.length > 0 && (
        <ul className="mod-picker-results">
          {results
            .filter((m) => !value.some((v) => v.mod_id === m.mod_id))
            .map((m) => (
              <li key={m.mod_id}>
                <button type="button" onClick={() => addMod(m)}>
                  {m.name} <span className="affix-tag">({m.affix})</span>
                </button>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
