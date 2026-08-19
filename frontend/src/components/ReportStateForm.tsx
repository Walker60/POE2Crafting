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

  async function submitAdvance(nextRarity: typeof rarity, nextMods: SelectedMod[]) {
    setError(null);
    setLoading(true);
    try {
      const result = await api.advance(sessionId, {
        rarity: nextRarity,
        current_mods: nextMods.map((m) => ({ mod_id: m.mod_id, tier_ilvl: m.ilvl })),
      });
      onAdvanced(result);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }

  function handleParsed(parsed: ParseItemResponse) {
    const nextRarity = parsed.rarity ? (parsed.rarity as typeof rarity) : rarity;
    const nextMods = parsed.mods.length > 0 ? parsed.mods.map((m) => ({ mod_id: m.mod_id, ilvl: m.tier_ilvl })) : currentMods;
    if (parsed.rarity) setRarity(nextRarity);
    if (parsed.mods.length > 0) setCurrentMods(nextMods);

    // Auto-advance on a paste that read cleanly (a rarity was found and
    // nothing was left unmatched) -- this is the "detect a change in the
    // pasted item and move on automatically" loop the user asked for. A
    // parse with unmatched lines needs a human glance first, so it only
    // pre-fills the fields and waits for the manual "Report state" click.
    if (parsed.rarity && parsed.unmatched_lines.length === 0) {
      void submitAdvance(nextRarity, nextMods);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await submitAdvance(rarity, currentMods);
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
