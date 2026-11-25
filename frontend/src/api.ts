// Client API — rispecchia docs/API.md

export type Source = 'llm' | 'regole';
export type ScopeId = 'journey_incrementality' | 'touchpoint_value' | 'universal_holdout' | 'frequency' | string;
export type KpiId = 'revenue_per_contact' | 'conversion_rate' | 'orders_per_contact' | 'avg_order_value';
export type ActivityType = 'ENTRY' | 'EMAIL' | 'SMS' | 'PUSH' | 'WAIT' | 'DECISION' | 'EXIT';

export interface Health {
  version: string;
  sfmc_mode: 'mock' | 'live' | string;
  sfmc_error?: string | null;
  llm: { base_url: string; model: string; enabled: boolean; reachable: boolean };
}

export interface Settings {
  llm_enabled: boolean;
  llm_base_url: string;
  llm_model: string;
  sfmc_mode: 'mock' | 'live' | string;
  sfmc_subdomain: string;
  sfmc_mid: string;
  sfmc_client_id: string;
  sfmc_client_secret_set: boolean;
}
export type SettingsUpdate = Partial<Omit<Settings, 'sfmc_client_secret_set'>> & { sfmc_client_secret?: string };

export interface Scope {
  id: ScopeId;
  name: string;
  question: string;
  description: string;
  position_rule: string;
  volume_need: string;
  requires_activity: boolean;
  enabled: boolean;
  disabled_reason: string | null;
}

export interface Baseline { conversion_rate: number; avg_order_value: number; expected_lift?: number | null }

export interface Journey {
  id: string;
  key: string;
  name: string;
  status: string;
  entry_source: string;
  monthly_volume: number;
  activity_count: number;
  baseline: Baseline;
  active_control_groups?: string[];
  folder?: string | null;
  last_modified?: string | null;
  channels?: string[];
}

export interface JourneyQuery {
  q?: string;
  status?: string;
  folder?: string;
  channel?: string;
  sort?: 'name' | 'volume' | 'modified' | string;
  page?: number;
  page_size?: number;
}

export interface JourneyPage {
  items: Journey[];
  total: number;
  page: number;
  page_size: number;
  facets: { status?: Record<string, number>; folder?: Record<string, number> };
}

export interface Activity {
  key: string;
  name: string;
  type: ActivityType;
  channel: string | null;
  step: number;
  lane: number;
  reach_rate: number;
  monthly_volume: number;
  next: string[];
  branch_label: string | null;
}

export interface JourneyDetail extends Journey { activities: Activity[] }

export interface InterpretResponse {
  scope_id: ScopeId;
  activity_key: string | null;
  confidence: 'alta' | 'media' | 'bassa' | string;
  rationale: string;
  kpi_suggestion: KpiId | string;
  source: Source;
}

export interface Candidate {
  id: string;
  activity_key: string | null;
  label: string;
  description: string;
  monthly_volume: number;
  recommended: boolean;
  pros: string[];
  cons: string[];
  expected_lift?: number | null;
}

export interface PositionsResponse { candidates: Candidate[]; narrative: string; source: Source }

export interface SizingRequest {
  monthly_volume: number;
  baseline_conversion: number;
  avg_order_value: number;
  aov_cv: number;
  expected_lift: number;
  duration_days: number;
  alpha: number;
  power: number;
  kpi: string;
}

export interface SizingOption {
  holdout_pct: number;
  control_size: number;
  treatment_size: number;
  mde_relative: number;
  days_to_detect: number | null;
  opportunity_cost: number;
  detectable: boolean;
}

export type Verdict = 'fattibile' | 'al limite' | 'non fattibile';

export interface SizingResponse {
  recommended_pct: number | null;
  feasible: boolean;
  verdict: Verdict | string;
  explanation: string;
  options: SizingOption[];
  assumptions: Record<string, number | string>;
}

export interface NarrativeResponse { narrative: string; source: Source }

export interface DataSource { type: string; config: Record<string, string> }
export interface Guardrails { srm_alpha: number; alert_negative_lift: boolean }

export interface ControlGroupCreate {
  name: string;
  journey_id: string;
  scope_id: string;
  activity_key: string | null;
  holdout_pct: number;
  primary_kpi: string;
  kpis: string[];
  attribution_days: number;
  data_source: DataSource;
  guardrails: Guardrails;
  category?: string;
}

export interface InitiativeCreate extends Omit<ControlGroupCreate, 'journey_id'> {
  journey_ids: string[];
  category: string;
}

export interface DeField { name: string; type: string; pk?: boolean; [k: string]: unknown }
export interface DeDef { key: string; fields: DeField[]; [k: string]: unknown }

export interface Artifacts {
  assignment_de: DeDef;
  results_de: DeDef;
  assignment_sql: string;
  results_sql: string;
  journey_change: { description: string; target_journey: string; decision_split?: unknown; [k: string]: unknown };
  automation: { name: string; schedule: string; steps: string[]; [k: string]: unknown };
}

export type DeployStatus = 'ok' | 'simulato' | 'errore' | 'manuale' | string;
export interface DeployStep { step: string; status: DeployStatus; detail: string }

export interface ControlGroup extends ControlGroupCreate {
  id: string;
  journey_name: string;
  activity_name: string | null;
  salt: string;
  status: string;
  created_at: string;
  artifacts: Artifacts;
  deploy_log: DeployStep[];
  initiative_id: string;
  initiative_name: string;
  category: string;
}

export interface InitiativeJourney {
  cg_id: string;
  journey_id: string;
  journey_name: string;
  activity_name: string | null;
  status: string;
}

export interface Initiative {
  id: string;
  name: string;
  category: string;
  scope_id: string;
  holdout_pct: number;
  primary_kpi: string;
  kpis: string[];
  attribution_days: number;
  created_at: string;
  status: string;
  journeys: InitiativeJourney[];
  control_groups?: ControlGroup[];
}

export interface MemberResults extends InitiativeJourney {
  results: Results | null;
  error: string | null;
}

export interface InitiativeResults {
  total: Results | null;
  members: MemberResults[];
}

export interface Interval { estimate: number; ci_low: number; ci_high: number }

export interface OverviewRow {
  cg_id: string;
  initiative_id: string;
  initiative_name: string;
  category: string;
  journey_id: string;
  journey_name: string;
  activity_name: string | null;
  scope_id: string;
  holdout_pct: number;
  error: string | null;
  primary: KpiResult | null;
  groups: { control: GroupStats; treatment: GroupStats } | null;
  incremental_revenue: Interval | null;
  srm_ok: boolean | null;
  status: { level: string; message: string } | null;
  days_running: number;
}

export interface CategorySummary {
  category: string;
  initiatives: number;
  journeys: number;
  control_contacts: number;
  treatment_contacts: number;
  treatment_revenue: number;
  incremental_revenue: Interval;
  revenue_lift: number | null;
  revenue_lift_ci: [number, number] | null;
  positive: number;
  negative: number;
  inconclusive: number;
  no_data: number;
}

export interface Overview { categories: CategorySummary[]; rows: OverviewRow[] }

export interface GroupStats { contacts: number; converters: number; orders: number; revenue: number }

export interface KpiResult {
  id: string;
  name: string;
  unit: string;
  control: number;
  treatment: number;
  abs_diff: number;
  rel_lift: number;
  ci_low: number;
  ci_high: number;
  p_value: number;
  significant: boolean;
  primary: boolean;
}

export interface TimePoint {
  date: string;
  day: number;
  rel_lift: number;
  ci_low: number;
  ci_high: number;
  p_value: number;
  control_contacts: number;
  treatment_contacts: number;
}

export interface Results {
  as_of: string;
  days_running: number;
  source: string;
  groups: { control: GroupStats; treatment: GroupStats };
  kpis: KpiResult[];
  srm: { expected_pct: number; observed_pct: number; p_value: number; ok: boolean };
  incremental_revenue: { estimate: number; ci_low: number; ci_high: number };
  timeseries: TimePoint[];
  status: { level: 'ok' | 'warning' | 'error' | string; message: string };
}

export interface DataSourceField {
  name: string;
  label: string;
  kind: 'text' | 'password' | 'textarea' | 'file' | string;
  default?: string | null;
  [k: string]: unknown;
}
export interface DataSourceType {
  type: string;
  name: string;
  description: string;
  default?: boolean;
  fields: DataSourceField[];
}

export interface DataSourceTest { ok: boolean; message: string; columns: string[]; sample: Record<string, unknown>[] }
export interface UploadResponse { path: string; rows: number; columns: string[] }

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function detailToString(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (d && typeof d === 'object' && 'msg' in d) {
          const loc = Array.isArray((d as { loc?: unknown[] }).loc) ? (d as { loc: unknown[] }).loc.join('.') : '';
          return `${loc ? loc + ': ' : ''}${(d as { msg: string }).msg}`;
        }
        return JSON.stringify(d);
      })
      .join('; ');
  }
  return JSON.stringify(detail);
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) init.body = body as FormData;
    else {
      (init.headers as Record<string, string>)['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError('Impossibile contattare il server. Verifica che il backend sia avviato.', 0);
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in (data as object)
        ? detailToString((data as { detail: unknown }).detail)
        : typeof data === 'string' && data
          ? data.slice(0, 300)
          : `Errore HTTP ${res.status}`;
    throw new ApiError(detail, res.status);
  }
  return data as T;
}

export const api = {
  health: () => request<Health>('GET', '/health'),
  getSettings: () => request<Settings>('GET', '/settings'),
  putSettings: (s: SettingsUpdate) => request<Settings>('PUT', '/settings', s),
  scopes: () => request<Scope[]>('GET', '/scopes'),
  journeys: (q: JourneyQuery = {}) => {
    const p = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => v !== undefined && v !== '' && p.set(k, String(v)));
    return request<JourneyPage>('GET', `/journeys?${p.toString()}`);
  },
  categories: () => request<string[]>('GET', '/categories'),
  createInitiative: (b: InitiativeCreate) => request<Initiative>('POST', '/initiatives', b),
  initiatives: () => request<Initiative[]>('GET', '/initiatives'),
  initiative: (id: string) => request<Initiative>('GET', `/initiatives/${encodeURIComponent(id)}`),
  initiativeResults: (id: string) => request<InitiativeResults>('GET', `/initiatives/${encodeURIComponent(id)}/results`),
  initiativeRefresh: (id: string) => request<InitiativeResults>('POST', `/initiatives/${encodeURIComponent(id)}/refresh`),
  initiativeNarrative: (id: string) => request<NarrativeResponse>('POST', `/initiatives/${encodeURIComponent(id)}/narrative`),
  deleteInitiative: (id: string) => request<{ ok: boolean }>('DELETE', `/initiatives/${encodeURIComponent(id)}`),
  overview: () => request<Overview>('GET', '/overview'),
  journey: (id: string) => request<JourneyDetail>('GET', `/journeys/${encodeURIComponent(id)}`),
  interpret: (question: string, journey_id: string) =>
    request<InterpretResponse>('POST', '/advisor/interpret', { question, journey_id }),
  positions: (journey_id: string, scope_id: string, activity_key: string | null) =>
    request<PositionsResponse>('POST', '/advisor/positions', { journey_id, scope_id, activity_key }),
  sizing: (req: SizingRequest) => request<SizingResponse>('POST', '/stats/sizing', req),
  explainSizing: (journey_id: string, scope_id: string, sizing: SizingResponse, req: SizingRequest) =>
    request<NarrativeResponse>('POST', '/advisor/explain-sizing', { journey_id, scope_id, sizing, request: req }),
  createControlGroup: (cg: ControlGroupCreate) => request<ControlGroup>('POST', '/control-groups', cg),
  controlGroups: () => request<ControlGroup[]>('GET', '/control-groups'),
  controlGroup: (id: string) => request<ControlGroup>('GET', `/control-groups/${encodeURIComponent(id)}`),
  deleteControlGroup: (id: string) => request<{ ok: boolean }>('DELETE', `/control-groups/${encodeURIComponent(id)}`),
  results: (id: string) => request<Results>('GET', `/control-groups/${encodeURIComponent(id)}/results`),
  refresh: (id: string) => request<Results>('POST', `/control-groups/${encodeURIComponent(id)}/refresh`),
  narrative: (id: string) => request<NarrativeResponse>('POST', `/control-groups/${encodeURIComponent(id)}/narrative`),
  dataSourceTypes: () => request<DataSourceType[]>('GET', '/datasources/types'),
  testDataSource: (ds: DataSource) => request<DataSourceTest>('POST', '/datasources/test', ds),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return request<UploadResponse>('POST', '/datasources/upload', fd, true);
  },
};

export const SAMPLE_CSV_URL = '/api/samples/sales.csv';

export const KPI_LABELS: Record<string, string> = {
  revenue_per_contact: 'Ricavo per contatto',
  conversion_rate: 'Tasso di conversione',
  orders_per_contact: 'Ordini per contatto',
  avg_order_value: 'Scontrino medio',
};
export const KPI_IDS: KpiId[] = ['revenue_per_contact', 'conversion_rate', 'orders_per_contact', 'avg_order_value'];
