import { useEffect, useState } from 'react';
import { api, type SolveResponse } from './api';
import { SetupForm } from './components/SetupForm';
import { RecommendationPanel } from './components/RecommendationPanel';
import { ReportStateForm } from './components/ReportStateForm';
import { TradeSettings } from './components/TradeSettings';

interface SetupInfo {
  baseId: string;
  ilvl: number;
}

function writeSessionToUrl(sessionId: string | null) {
  const url = new URL(window.location.href);
  if (sessionId) url.searchParams.set('session', sessionId);
  else url.searchParams.delete('session');
  // replaceState, not pushState -- ordinary crafting steps shouldn't pile up
  // Back-button history entries, just keep the address bar shareable.
  window.history.replaceState(null, '', url);
}

function App() {
  const [result, setResult] = useState<SolveResponse | null>(null);
  const [setupInfo, setSetupInfo] = useState<SetupInfo | null>(null);
  const [rehydrating, setRehydrating] = useState(true);

  // On load, a `?session=<id>` in the URL (from a previously-shared link, or
  // this tab's own earlier reload) rehydrates the craft instead of showing
  // the setup form -- see writeSessionToUrl, called on every solve/advance/undo.
  useEffect(() => {
    const sessionId = new URLSearchParams(window.location.search).get('session');
    if (!sessionId) {
      setRehydrating(false);
      return;
    }
    api
      .getSession(sessionId)
      .then((r) => handleSolved(r, r.base_id, r.ilvl))
      .catch(() => writeSessionToUrl(null)) // expired/unknown session -- fall back to SetupForm, drop the dead link
      .finally(() => setRehydrating(false));
    // Only ever run once, on mount -- this isn't meant to react to later URL changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleSolved(r: SolveResponse, baseId: string, ilvl: number) {
    setResult(r);
    setSetupInfo({ baseId, ilvl });
    writeSessionToUrl(r.session_id);
  }

  function handleAdvanced(r: SolveResponse) {
    setResult(r);
    writeSessionToUrl(r.session_id);
  }

  function handleStartOver() {
    setResult(null);
    setSetupInfo(null);
    writeSessionToUrl(null);
  }

  if (rehydrating) {
    return null;
  }

  return (
    <>
      <header id="site-header">
        <div className="brand">
          poe2craft<span className="brand-accent">.</span>
        </div>
        <nav className="site-nav">
          <span className="site-nav-item active">solver</span>
        </nav>
      </header>
      <main id="root-layout">
        <TradeSettings />
        {!result || !setupInfo ? (
          <SetupForm onSolved={handleSolved} />
        ) : (
          <>
            <RecommendationPanel result={result} onStartOver={handleStartOver} onUndo={handleAdvanced} />
            {!result.is_goal && !result.dead_end && (
              <ReportStateForm
                sessionId={result.session_id}
                baseId={setupInfo.baseId}
                ilvl={setupInfo.ilvl}
                onAdvanced={handleAdvanced}
              />
            )}
          </>
        )}
      </main>
    </>
  );
}

export default App;
