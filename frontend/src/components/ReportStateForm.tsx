import { useState } from 'react';
import { api, type ParseItemResponse, type SolveResponse } from '../api';
import { ItemPasteBox } from './ItemPasteBox';
import { ModPicker, type SelectedMod } from './ModPicker';

interface Props {
  sessionId: string;
  baseId: string;
  ilvl: number;
  onAdvanced: (result: SolveResponse) => void;
}

export function ReportStateForm({ sessionId, baseId, ilvl, onAdvanced }: Props) {
  const [rarity, setRarity] = useState<'normal' | 'magic' | 'rare'>('rare');
  const [currentMods, setCurrentMods] = useState<SelectedMod[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleParsed(parsed: ParseItemResponse) {
    if (parsed.rarity) setRarity(parsed.rarity as typeof rarity);
    if (parsed.mods.length > 0) {
      setCurrentMods(parsed.mods.map((m) => ({ mod_id: m.mod_id, ilvl: m.tier_ilvl })));
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await api.advance(sessionId, {
        rarity,
        current_mods: currentMods.map((m) => ({ mod_id: m.mod_id, tier_ilvl: m.ilvl })),
      });
      onAdvanced(result);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="report-state-form" onSubmit={handleSubmit}>
      <h2>After applying that action, what does the item look like now?</h2>
      <p className="loop-caption">LOOP &middot; NOT ONE CLICK -- paste or re-enter the item after applying the step above.</p>

      <ItemPasteBox onParsed={handleParsed} forcedBaseId={baseId} />

      <label>
        Rarity
        <select value={rarity} onChange={(e) => setRarity(e.target.value as typeof rarity)}>
          <option value="normal">Normal</option>
          <option value="magic">Magic</option>
          <option value="rare">Rare</option>
        </select>
      </label>

      <fieldset>
        <legend>Current modifiers</legend>
        <ModPicker baseId={baseId} ilvl={ilvl} mode="current" value={currentMods} onChange={setCurrentMods} />
      </fieldset>

      {error && <p className="error">{error}</p>}

      <div className="submit-row">
        <button type="submit" disabled={loading}>
          {loading ? 'Solving...' : 'Report state'}
        </button>
        <span className="help-text">Same as pasting above -- asks with the target as it stands.</span>
      </div>
    </form>
  );
}
