import { useEffect, useState } from 'react';
import { api, type BaseOption, type ParseItemResponse, type SolveResponse } from '../api';
import { ItemPasteBox } from './ItemPasteBox';
import { ModPicker, type SelectedMod } from './ModPicker';

interface Props {
  onSolved: (result: SolveResponse, baseId: string, ilvl: number) => void;
}

export function SetupForm({ onSolved }: Props) {
  const [bases, setBases] = useState<BaseOption[]>([]);
  const [baseId, setBaseId] = useState('');
  const [ilvl, setIlvl] = useState(80);
  const [rarity, setRarity] = useState<'normal' | 'magic' | 'rare'>('rare');
  const [currentMods, setCurrentMods] = useState<SelectedMod[]>([]);
  const [targetMods, setTargetMods] = useState<SelectedMod[]>([]);
  const [objective, setObjective] = useState<'steps' | 'cost'>('cost');
  const [precision, setPrecision] = useState<'fast' | 'balanced' | 'precise'>('balanced');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const N_TRIALS: Record<typeof precision, number> = { fast: 150, balanced: 500, precise: 1000 };

  useEffect(() => {
    api.listBases().then(setBases).catch((e) => setError(String((e as Error).message ?? e)));
  }, []);

  function handleParsed(parsed: ParseItemResponse) {
    if (parsed.base_id) setBaseId(parsed.base_id);
    if (parsed.ilvl != null) setIlvl(parsed.ilvl);
    if (parsed.rarity) setRarity(parsed.rarity as typeof rarity);
    if (parsed.base_id && parsed.mods.length > 0) {
      setCurrentMods(parsed.mods.map((m) => ({ mod_id: m.mod_id, ilvl: m.tier_ilvl })));
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!baseId) {
      setError('Pick an item base first.');
      return;
    }
    if (targetMods.length === 0) {
      setError('Pick at least one target modifier.');
      return;
    }
    setLoading(true);
    try {
      const result = await api.createSession({
        base_id: baseId,
        ilvl,
        rarity,
        current_mods: currentMods.map((m) => ({ mod_id: m.mod_id, tier_ilvl: m.ilvl })),
        target_mods: targetMods.map((m) => ({ mod_id: m.mod_id, min_ilvl: m.ilvl })),
        objective,
        n_trials: N_TRIALS[precision],
      });
      onSolved(result, baseId, ilvl);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <h2>Set up a craft</h2>
      <p className="panel-subtitle">Paste an item to read it automatically, or fill in the fields below by hand.</p>

      <div className="split-panel">
        <ItemPasteBox onParsed={handleParsed} />
        <div>
          <h3>How to use</h3>
          <ol className="howto-list">
            <li>Paste your item, or pick its base/level/rarity and current modifiers manually.</li>
            <li>Add the modifiers the finished item must carry, under "Must have" below.</li>
            <li>Choose whether to optimize for the fewest steps or the cheapest real cost.</li>
            <li>Solve, then follow the recommended action in game.</li>
            <li>Paste (or re-enter) the item's new state below to get the next step -- repeat until done.</li>
          </ol>
        </div>
      </div>

      <div className="field-row">
        <label>
          Item base
          <select value={baseId} onChange={(e) => setBaseId(e.target.value)}>
            <option value="">-- select --</option>
            {bases.map((b) => (
              <option key={b.base_id} value={b.base_id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>

        <label>
          Item level
          <input type="number" min={1} max={100} value={ilvl} onChange={(e) => setIlvl(Number(e.target.value))} />
        </label>

        <label>
          Rarity
          <select value={rarity} onChange={(e) => setRarity(e.target.value as typeof rarity)}>
            <option value="normal">Normal</option>
            <option value="magic">Magic</option>
            <option value="rare">Rare</option>
          </select>
        </label>
      </div>

      <fieldset>
        <legend>Current modifiers</legend>
        <ModPicker baseId={baseId || null} ilvl={ilvl} mode="current" value={currentMods} onChange={setCurrentMods} />
      </fieldset>

      <div className="section-label">
        <span className="section-dot must-have" aria-hidden="true" />
        What would satisfy you -- must have
      </div>
      <p className="panel-subtitle">Add the modifiers the finished item must end up with.</p>
      <ModPicker baseId={baseId || null} ilvl={ilvl} mode="target" value={targetMods} onChange={setTargetMods} />

      <div className="settings-row" style={{ marginTop: 18 }}>
        <span className="settings-row-label">Optimize for</span>
        <div className="pill-group">
          <button type="button" className={objective === 'cost' ? 'active' : ''} onClick={() => setObjective('cost')}>
            Cheapest
          </button>
          <button type="button" className={objective === 'steps' ? 'active' : ''} onClick={() => setObjective('steps')}>
            Fewest steps
          </button>
        </div>
      </div>
      <p className="help-text" style={{ marginBottom: 16 }}>
        {objective === 'cost'
          ? 'Finds the plan with the lowest expected currency spend, even if it takes more crafting steps.'
          : 'Finds the plan with the fewest expected crafting actions, without regard to how expensive those actions are.'}
      </p>

      <div className="settings-row" style={{ marginTop: 4 }}>
        <span className="settings-row-label">Solve precision</span>
        <div className="pill-group">
          <button type="button" className={precision === 'fast' ? 'active' : ''} onClick={() => setPrecision('fast')}>
            Fast
          </button>
          <button
            type="button"
            className={precision === 'balanced' ? 'active' : ''}
            onClick={() => setPrecision('balanced')}
          >
            Balanced
          </button>
          <button
            type="button"
            className={precision === 'precise' ? 'active' : ''}
            onClick={() => setPrecision('precise')}
          >
            Precise
          </button>
        </div>
      </div>
      <p className="help-text" style={{ marginBottom: 16 }}>
        {precision === 'fast' && 'Fewer Monte Carlo samples per action -- solves noticeably faster, at the cost of noisier probability estimates.'}
        {precision === 'balanced' && "This project's default sample count -- a reasonable balance of solve time and accuracy."}
        {precision === 'precise' && 'More Monte Carlo samples per action -- more stable probability estimates, at the cost of a slower solve.'}
      </p>

      {error && <p className="error">{error}</p>}

      <div className="submit-row">
        <button type="submit" disabled={loading}>
          {loading ? 'Solving...' : 'Solve'}
        </button>
        <span className="help-text">
          {precision === 'fast' && 'Usually a few seconds.'}
          {precision === 'balanced' && 'Can take up to a minute.'}
          {precision === 'precise' && 'Can take a couple of minutes.'}
        </span>
      </div>
    </form>
  );
}
