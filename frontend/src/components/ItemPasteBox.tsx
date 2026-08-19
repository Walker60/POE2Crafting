import { useState } from 'react';
import { api, type ParseItemResponse } from '../api';

interface Props {
  onParsed: (parsed: ParseItemResponse) => void;
  // When set, skip auto-detection entirely and always parse against this
  // base -- used when reporting a new state for an already-created session,
  // where the base is already fixed and can't change mid-craft.
  forcedBaseId?: string;
}

// Mirrors craftgaz's "paste the item" workflow: hover in-game, Ctrl+C (or
// Ctrl+Alt+C for advanced mod descriptions, which lets the parser resolve
// tiers exactly instead of guessing from the rolled value). Parsing is
// inherently best-effort -- see solver/item_text.py's module docstring --
// so this always shows "how it read your item" rather than silently trusting
// the result, and lets the user pick manually when the base is ambiguous.
export function ItemPasteBox({ onParsed, forcedBaseId }: Props) {
  const [text, setText] = useState('');
  const [result, setResult] = useState<ParseItemResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function doParse(baseId?: string) {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const parsed = await api.parseItem({ text, base_id: forcedBaseId ?? baseId });
      setResult(parsed);
      onParsed(parsed);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="item-paste-box">
      <label>
        Hover the item in game and copy it (Ctrl+C, or Ctrl+Alt+C for exact tiers), then paste here.
        <textarea
          rows={7}
          placeholder={'Item Class: ...\nRarity: Rare\n...paste the whole thing, straight from the game...'}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => doParse()}
        />
      </label>
      <div className="submit-row">
        <button type="button" onClick={() => doParse()} disabled={loading || !text.trim()}>
          {loading ? 'Reading...' : 'Read item'}
        </button>
        <span className="help-text">Reads automatically when you click away -- the button is for edited text.</span>
      </div>
      {error && <p className="error">{error}</p>}

      {result && (
        <div className="parse-preview">
          <h3>How it read your item</h3>
          {result.base_id ? (
            <p>
              {result.base_name} &middot; ilvl {result.ilvl ?? '?'} &middot; {result.rarity}
            </p>
          ) : result.ambiguous_bases.length > 0 ? (
            <div>
              <p>Couldn&apos;t tell which base this is from the text alone -- pick one:</p>
              <div className="ambiguous-bases">
                {result.ambiguous_bases.map((b) => (
                  <button type="button" key={b.base_id} onClick={() => doParse(b.base_id)}>
                    {b.name}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <p className="error">Couldn&apos;t determine the item&apos;s base -- pick one manually below.</p>
          )}
          {result.mods.length > 0 && (
            <ul className="parse-mod-list">
              {result.mods.map((m) => (
                <li key={m.mod_id}>
                  {m.name} <span className="affix-tag">T{m.rank}</span>
                </li>
              ))}
            </ul>
          )}
          {result.unmatched_lines.length > 0 && (
            <p className="banner banner-warning">
              Couldn&apos;t confidently read {result.unmatched_lines.length} line(s) -- often an implicit or
              unsupported modifier, double check against your item: {result.unmatched_lines.join('; ')}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
