import { useState } from 'react';
import type { SolveResponse } from './api';
import { SetupForm } from './components/SetupForm';
import { RecommendationPanel } from './components/RecommendationPanel';
import { ReportStateForm } from './components/ReportStateForm';

interface SetupInfo {
  baseId: string;
  ilvl: number;
}

function App() {
  const [result, setResult] = useState<SolveResponse | null>(null);
  const [setupInfo, setSetupInfo] = useState<SetupInfo | null>(null);

  function handleSolved(r: SolveResponse, baseId: string, ilvl: number) {
    setResult(r);
    setSetupInfo({ baseId, ilvl });
  }

  function handleStartOver() {
    setResult(null);
    setSetupInfo(null);
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
        {!result || !setupInfo ? (
          <SetupForm onSolved={handleSolved} />
        ) : (
          <>
            <RecommendationPanel result={result} onStartOver={handleStartOver} />
            {!result.is_goal && !result.dead_end && (
              <ReportStateForm
                sessionId={result.session_id}
                baseId={setupInfo.baseId}
                ilvl={setupInfo.ilvl}
                onAdvanced={setResult}
              />
            )}
          </>
        )}
      </main>
    </>
  );
}

export default App;
