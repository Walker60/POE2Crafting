import { useState } from 'react';
import { api, type TradeSettingsResponse } from '../api';
import { Collapsible } from './Collapsible';

export function TradeSettings() {
  const [settings, setSettings] = useState<TradeSettingsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [leagueInput, setLeagueInput] = useState('');
  const [poesessidInput, setPoesessidInput] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  function load() {
    if (settings || loading) return;
    setLoading(true);
    setError(null);
    api
      .getTradeSettings()
      .then((s) => {
        setSettings(s);
        setLeagueInput(s.league ?? '');
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setLoading(false));
  }

  function save() {
    setSaving(true);
    setSaveMessage(null);
    setError(null);
    api
      .updateTradeSettings({ league: leagueInput || null, poesessid: poesessidInput || null })
      .then((s) => {
        setSettings(s);
        setPoesessidInput('');
        setSaveMessage('Saved.');
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setSaving(false));
  }

  function clearPoesessid() {
    setSaving(true);
    setSaveMessage(null);
    setError(null);
    api
      .updateTradeSettings({ clear_poesessid: true })
      .then((s) => {
        setSettings(s);
        setSaveMessage('Cleared.');
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setSaving(false));
  }

  return (
    <Collapsible title="Trade settings" onOpen={load}>
      {loading && <p>Loading...</p>}
      {error && <p className="error">{error}</p>}
      {settings && (
        <>
          <p className="help-text">
            Needed for live trade pricing ("Compare vs. market", <code>mod-price</code>, <code>trade-compare</code>).
            Saved in a local file on this machine only (never committed, never sent anywhere except to
            pathofexile.com when a query actually runs) -- see docs/data_provenance.md.
          </p>

          <div className="field-row">
            <label>
              Trade league
              {settings.active_leagues ? (
                <select value={leagueInput} onChange={(e) => setLeagueInput(e.target.value)}>
                  <option value="">-- select --</option>
                  {settings.active_leagues.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={leagueInput}
                  onChange={(e) => setLeagueInput(e.target.value)}
                  placeholder="exact trade-site league name"
                />
              )}
            </label>

            <label>
              POESESSID
              <input
                type="password"
                value={poesessidInput}
                onChange={(e) => setPoesessidInput(e.target.value)}
                placeholder={settings.poesessid_set ? 'already set -- leave blank to keep it' : 'optional'}
              />
            </label>
          </div>

          {!settings.active_leagues && (
            <p className="help-text">
              Couldn't fetch the live list of active leagues ({settings.active_leagues_error}) -- type the exact
              name instead.
            </p>
          )}

          <div className="submit-row">
            <button type="button" onClick={save} disabled={saving}>
              {saving ? 'Saving...' : 'Save'}
            </button>
            {settings.poesessid_set && (
              <button type="button" className="start-over" onClick={clearPoesessid} disabled={saving}>
                Clear POESESSID
              </button>
            )}
            {saveMessage && <span className="help-text">{saveMessage}</span>}
          </div>
        </>
      )}
    </Collapsible>
  );
}
