// Thin fetch wrapper for the poe2craft web API. Types here mirror
// src/poe2craft/web/schemas.py exactly -- keep them in sync by hand (no
// codegen in this project).

export interface BaseOption {
  base_id: string;
  name: string;
  bgroup_name: string;
  is_jewellery: boolean;
  max_prefix: number;
  max_suffix: number;
}

export interface ModTierOption {
  ilvl: number;
  weight: number;
  rank: number; // 1 = best/highest-ilvl tier ("T1")
  value_ranges: [number, number][];
}

export interface ModOption {
  mod_id: string;
  name: string;
  affix: 'prefix' | 'suffix';
  tags: string[];
  rollable: boolean;
  essence_grantable: boolean;
  tiers: ModTierOption[];
}

export interface ModReport {
  mod_id: string;
  tier_ilvl: number;
}

export interface TargetModRequest {
  mod_id: string;
  min_ilvl: number;
}

export interface SetupRequest {
  base_id: string;
  ilvl: number;
  rarity: string;
  current_mods: ModReport[];
  target_mods: TargetModRequest[];
  objective: 'steps' | 'cost';
  max_steps?: number;
  n_trials?: number;
  seed?: number;
}

export interface AdvanceRequest {
  rarity: string;
  current_mods: ModReport[];
}

export interface TargetProgressItem {
  mod_id: string;
  name: string;
  min_ilvl: number;
  status: 'absent' | 'below_tier' | 'satisfied';
}

export interface RecommendedAction {
  action_id: string;
  name: string;
  cost: number;
}

export interface SolveResponse {
  session_id: string;
  target_progress: TargetProgressItem[];
  prefix_count: number;
  suffix_count: number;
  max_prefix: number;
  max_suffix: number;
  rarity: string;
  is_goal: boolean;
  dead_end: boolean;
  recommended_action: RecommendedAction | null;
  estimated_remaining: number;
  objective: string;
  unit: string;
  converged: boolean;
  iterations: number;
  states_explored: number;
  resolved_via: 'cached_policy' | 'resolved_fresh' | null;
  note: string | null;
}

export interface ParseItemRequest {
  text: string;
  base_id?: string;
}

export interface ParsedModOption {
  mod_id: string;
  name: string;
  affix: 'prefix' | 'suffix';
  tier_ilvl: number;
  rank: number;
}

export interface ParseItemResponse {
  base_id: string | null;
  base_name: string | null;
  ilvl: number | null;
  rarity: string | null;
  mods: ParsedModOption[];
  ambiguous_bases: BaseOption[];
  unmatched_lines: string[];
}

export interface CostSpreadResponse {
  n_rollouts: number;
  n_samples: number;
  success_rate: number;
  mean_cost: number;
  median_cost: number;
  p90_cost: number;
  worst_cost: number;
  unit: string;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // response wasn't JSON -- keep statusText
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

function modQuery(params: { ilvl?: number; affix?: string; q?: string }): string {
  const search = new URLSearchParams();
  if (params.ilvl !== undefined) search.set('ilvl', String(params.ilvl));
  if (params.affix) search.set('affix', params.affix);
  if (params.q) search.set('q', params.q);
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

export const api = {
  listBases: () => request<BaseOption[]>('/api/bases'),
  listMods: (baseId: string, params: { ilvl?: number; affix?: string; q?: string }) =>
    request<ModOption[]>(`/api/bases/${encodeURIComponent(baseId)}/mods${modQuery(params)}`),
  createSession: (body: SetupRequest) =>
    request<SolveResponse>('/api/sessions', { method: 'POST', body: JSON.stringify(body) }),
  advance: (sessionId: string, body: AdvanceRequest) =>
    request<SolveResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/advance`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  deleteSession: (sessionId: string) =>
    request<void>(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }),
  parseItem: (body: ParseItemRequest) =>
    request<ParseItemResponse>('/api/parse-item', { method: 'POST', body: JSON.stringify(body) }),
  costSpread: (sessionId: string, nRollouts?: number) =>
    request<CostSpreadResponse>(
      `/api/sessions/${encodeURIComponent(sessionId)}/cost-spread${nRollouts ? `?n_rollouts=${nRollouts}` : ''}`
    ),
};
