import { useState } from 'react';
import { api, type CostSpreadResponse, type SolveResponse, type TradeComparisonResponse } from '../api';
import { Collapsible } from './Collapsible';

const RECOMMENDATION_LABEL: Record<string, string> = {
  keep_crafting: 'Keep crafting',
  buy: 'Buy the target off trade',
  sell_and_restart: 'Sell this item and start over',
  insufficient_data: 'Not enough listing data for a recommendation',
};

interface Props {
  result: SolveResponse;
  onStartOver: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  absent: 'absent',
  below_tier: 'low tier',
  satisfied: 'ok',
};

function fmtDivine(n: number): string {
  return `${n.toFixed(2)} d`;
}

export function RecommendationPanel({ result, onStartOver }: Props) {
  const [spread, setSpread] = useState<CostSpreadResponse | null>(null);
  const [spreadLoading, setSpreadLoading] = useState(false);
  const [spreadError, setSpreadError] = useState<string | null>(null);

  function loadSpread() {
    if (spread || spreadLoading) return;
    setSpreadLoading(true);
    setSpreadError(null);
    api
      .costSpread(result.session_id)
      .then(setSpread)
      .catch((e) => setSpreadError(String((e as Error).message ?? e)))
      .finally(() => setSpreadLoading(false));
  }

  const [trade, setTrade] = useState<TradeComparisonResponse | null>(null);
  const [tradeLoading, setTradeLoading] = useState(false);
  const [tradeError, setTradeError] = useState<string | null>(null);

  // Never fetched automatically -- only `runTradeCompare` (a button click,
  // see below) triggers a real pathofexile.com/trade2 request. See
  // docs/data_provenance.md.
  function runTradeCompare() {
    if (tradeLoading) return;
    setTradeLoading(true);
    setTradeError(null);
    api
      .tradeCompare(result.session_id)
      .then(setTrade)
      .catch((e) => setTradeError(String((e as Error).message ?? e)))
      .finally(() => setTradeLoading(false));
  }

  return (
    <div className="recommendation-panel">
      {result.resolved_via === 'resolved_fresh' && (
        <div className="banner banner-warning">
          <strong>Note:</strong> {result.note}
        </div>
      )}

      {!result.converged && (
        <div className="banner banner-warning">
          The solver did not fully converge within its iteration budget — the recommendation below may be
          approximate.
        </div>
      )}

      {result.is_goal && <div className="banner banner-success">Target reached — craft complete.</div>}

      {!result.is_goal && result.dead_end && (
        <div className="banner banner-error">
          Dead end: the target can no longer be reached from this item's current state with the modeled actions.
        </div>
      )}

      {!result.is_goal && !result.dead_end && result.recommended_action && (
        <div className="hero-action">
          <span className="hero-action-label">DO THIS</span>
          <div className="stat-row">
            <span className="action-name">{result.recommended_action.name}</span>
            <span className="action-cost">{fmtDivine(result.recommended_action.cost)}</span>
          </div>
          <p className="loop-caption">
            LOOP &middot; NOT ONE CLICK -- apply this, then report the item's new state below.
          </p>
        </div>
      )}

      <Collapsible title="Target progress" defaultOpen>
        <ul className="target-progress">
          {result.target_progress.map((t) => (
            <li key={t.mod_id} className={`status-${t.status}`}>
              <span className="status-dot" aria-hidden="true" />
              <span className="mod-name">{t.name}</span>
              {t.min_ilvl > 0 && <span className="min-ilvl">min ilvl {t.min_ilvl}</span>}
              <span className="status-label">{STATUS_LABEL[t.status] ?? t.status}</span>
            </li>
          ))}
        </ul>
        <p className="affix-counts">
          <span>
            prefix <b>{result.prefix_count}</b>/{result.max_prefix}
          </span>
          <span>
            suffix <b>{result.suffix_count}</b>/{result.max_suffix}
          </span>
          <span className={`rarity-tag rarity-${result.rarity}`}>{result.rarity}</span>
        </p>
      </Collapsible>

      <Collapsible title="Cost to finish from here" onOpen={loadSpread}>
        {spreadLoading && <p>Rolling out the policy...</p>}
        {spreadError && <p className="error">{spreadError}</p>}
        {spread && (
          <>
            <div className="stat-row">
              <span>average</span>
              <span>{fmtDivine(spread.mean_cost)}</span>
            </div>
            <div className="stat-row">
              <span>half finish under</span>
              <span>{fmtDivine(spread.median_cost)}</span>
            </div>
            <div className="stat-row">
              <span>9 in 10 finish within</span>
              <span>{fmtDivine(spread.p90_cost)}</span>
            </div>
            <div className="stat-row">
              <span>worst run seen</span>
              <span>{fmtDivine(spread.worst_cost)}</span>
            </div>
            <p className="help-text">
              From {spread.n_samples} of {spread.n_rollouts} simulated rollouts of the current plan (
              {(spread.success_rate * 100).toFixed(0)}% reached the target). Reflects the plan currently
              recommended, which may favor speed over price if you chose "fewest steps".
            </p>
          </>
        )}
      </Collapsible>

      <Collapsible title="Compare vs. market">
        {result.objective !== 'cost' ? (
          <p className="help-text">
            Only available for a "cheapest" (cost-objective) session, so every number is in real Divine Orb terms.
          </p>
        ) : (
          <>
            <p className="help-text">
              Checks pathofexile.com/trade2 for real listing prices -- a live network request, only made when you
              click below.
            </p>
            <button type="button" className="start-over" onClick={runTradeCompare} disabled={tradeLoading}>
              {tradeLoading ? 'Checking trade...' : 'Check trade prices'}
            </button>
            {tradeError && <p className="error">{tradeError}</p>}
            {trade && (
              <>
                <div className="stat-row">
                  <span>keep crafting</span>
                  <span>{fmtDivine(trade.craft_cost)}</span>
                </div>
                <div className="stat-row">
                  <span>buy the target</span>
                  <span>{trade.buy_price !== null ? `${fmtDivine(trade.buy_price)} (${trade.buy_price_n_listings} listings)` : 'n/a'}</span>
                </div>
                <div className="stat-row">
                  <span>sell current item</span>
                  <span>
                    {trade.sell_value !== null ? `${fmtDivine(trade.sell_value)} (${trade.sell_value_n_listings} listings)` : 'n/a'}
                  </span>
                </div>
                {trade.sell_and_restart_net_cost !== null && (
                  <div className="stat-row">
                    <span>sell + restart, net</span>
                    <span>{fmtDivine(trade.sell_and_restart_net_cost)}</span>
                  </div>
                )}
                <p className="loop-caption">
                  {trade.league} &middot; recommendation: {RECOMMENDATION_LABEL[trade.recommendation] ?? trade.recommendation}
                </p>
                {trade.caveats.map((c, i) => (
                  <p key={i} className="help-text">
                    {c}
                  </p>
                ))}
              </>
            )}
          </>
        )}
      </Collapsible>

      <Collapsible title="Under the hood">
        <div className="stat-row stat-row-muted">
          <span>session</span>
          <span>{result.session_id}</span>
        </div>
        <div className="stat-row stat-row-muted">
          <span>converged</span>
          <span>{result.converged ? 'yes' : 'no'}</span>
        </div>
        <div className="stat-row stat-row-muted">
          <span>iterations</span>
          <span>{result.iterations}</span>
        </div>
        <div className="stat-row stat-row-muted">
          <span>states explored</span>
          <span>{result.states_explored}</span>
        </div>
        <div className="stat-row stat-row-muted">
          <span>resolved via</span>
          <span>{result.resolved_via ?? 'initial solve'}</span>
        </div>
        <div className="stat-row stat-row-muted">
          <span>estimated remaining ({result.unit})</span>
          <span>{result.objective === 'cost' ? fmtDivine(result.estimated_remaining) : result.estimated_remaining.toFixed(2)}</span>
        </div>
      </Collapsible>

      <button type="button" className="start-over" onClick={onStartOver}>
        Start over
      </button>
    </div>
  );
}
