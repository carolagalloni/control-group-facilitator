import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  api,
  ApiError,
  Activity,
  Candidate,
  DataSourceTest,
  DataSourceType,
  Initiative,
  InitiativeCreate,
  InterpretResponse,
  Journey,
  JourneyDetail,
  KPI_IDS,
  KPI_LABELS,
  NarrativeResponse,
  PositionsResponse,
  Scope,
  SizingRequest,
  SizingResponse,
  SAMPLE_CSV_URL,
} from '../api';
import JourneyDiagram, { MESSAGING } from '../components/JourneyDiagram';
import { MdeChart } from '../components/Charts';
import JourneyPicker from '../components/JourneyPicker';
import ArtifactsView, { DeployLog } from '../components/ArtifactsView';
import { AdvisorBox, Alert, ErrorBox, Loading, SourceBadge, Spinner, Thinking } from '../components/ui';
import { fmtEur, fmtEur2, fmtInt, fmtLift, fmtPct } from '../format';

const STEPS = ['Obiettivo', 'Posizione', 'Dimensione', 'Monitoraggio', 'Riepilogo e deploy'];

/** form di sizing in unità "utente" (percentuali come numeri 0–100) */
interface SizingForm {
  monthly_volume: string;
  baseline_conversion_pct: string;
  avg_order_value: string;
  expected_lift_pct: string;
  duration_days: string;
  kpi: string;
  aov_cv: string;
  alpha: string;
  power_pct: string;
}

const num = (s: string) => {
  const v = parseFloat(String(s).replace(',', '.'));
  return Number.isFinite(v) ? v : NaN;
};
const toStr = (v: number, digits = 2) => String(+v.toFixed(digits));

function formToRequest(f: SizingForm): SizingRequest | null {
  const r: SizingRequest = {
    monthly_volume: Math.round(num(f.monthly_volume)),
    baseline_conversion: num(f.baseline_conversion_pct) / 100,
    avg_order_value: num(f.avg_order_value),
    aov_cv: num(f.aov_cv),
    expected_lift: num(f.expected_lift_pct) / 100,
    duration_days: Math.round(num(f.duration_days)),
    alpha: num(f.alpha),
    power: num(f.power_pct) / 100,
    kpi: f.kpi,
  };
  const ok =
    r.monthly_volume > 0 &&
    r.baseline_conversion > 0 && r.baseline_conversion < 1 &&
    r.avg_order_value > 0 &&
    r.aov_cv >= 0 &&
    r.expected_lift > 0 &&
    r.duration_days > 0 &&
    r.alpha > 0 && r.alpha < 1 &&
    r.power > 0 && r.power < 1;
  return ok ? r : null;
}

/** recommended_pct può arrivare null quando il test non è fattibile: scegliamo l'opzione più vicina al 20% */
function defaultPct(r: SizingResponse): number | null {
  if (typeof r.recommended_pct === 'number') return r.recommended_pct;
  if (!r.options.length) return null;
  return [...r.options].sort((a, b) => Math.abs(a.holdout_pct - 0.2) - Math.abs(b.holdout_pct - 0.2))[0].holdout_pct;
}

const VERDICT: Record<string, 'green' | 'amber' | 'red'> = { fattibile: 'green', 'al limite': 'amber', 'non fattibile': 'red' };

export default function Wizard() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [maxStep, setMaxStep] = useState(0);

  // catalogo
  const [scopes, setScopes] = useState<Scope[] | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [catalogErr, setCatalogErr] = useState<unknown>(null);

  // step 1 — uno o più journey (iniziativa); il primo è il riferimento per advisor e dimensionamento
  const [selected, setSelected] = useState<Journey[]>([]);
  const journeyId = selected[0]?.id ?? '';
  const multi = selected.length > 1;
  const [journey, setJourney] = useState<JourneyDetail | null>(null);
  const [journeyErr, setJourneyErr] = useState<unknown>(null);
  const [question, setQuestion] = useState('');
  const [interp, setInterp] = useState<InterpretResponse | null>(null);
  const [interpLoading, setInterpLoading] = useState(false);
  const [interpErr, setInterpErr] = useState<unknown>(null);
  const [scopeId, setScopeId] = useState('');
  const [activityKey, setActivityKey] = useState<string | null>(null);

  // step 2
  const [positions, setPositions] = useState<PositionsResponse | null>(null);
  const [positionsKey, setPositionsKey] = useState('');
  const [posLoading, setPosLoading] = useState(false);
  const [posErr, setPosErr] = useState<unknown>(null);
  const [candidateId, setCandidateId] = useState<string | null>(null);

  // step 3
  const [form, setForm] = useState<SizingForm | null>(null);
  const [prefillKey, setPrefillKey] = useState('');
  const [sizing, setSizing] = useState<SizingResponse | null>(null);
  const [sizingReq, setSizingReq] = useState<SizingRequest | null>(null);
  const [sizingLoading, setSizingLoading] = useState(false);
  const [sizingErr, setSizingErr] = useState<unknown>(null);
  const [holdoutPct, setHoldoutPct] = useState<number | null>(null);
  const [userPicked, setUserPicked] = useState(false);
  const [explain, setExplain] = useState<NarrativeResponse | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [explainErr, setExplainErr] = useState<unknown>(null);

  // step 4
  const [name, setName] = useState('');
  const [nameEdited, setNameEdited] = useState(false);
  const [category, setCategory] = useState('');
  const [categoryEdited, setCategoryEdited] = useState(false);
  const [newCategory, setNewCategory] = useState(false);
  const [primaryKpi, setPrimaryKpi] = useState('revenue_per_contact');
  const [kpis, setKpis] = useState<string[]>(['revenue_per_contact', 'conversion_rate', 'orders_per_contact']);
  const [attributionDays, setAttributionDays] = useState('30');
  const [dsTypes, setDsTypes] = useState<DataSourceType[] | null>(null);
  const [dsType, setDsType] = useState('');
  const [dsConfig, setDsConfig] = useState<Record<string, string>>({});
  const [uploading, setUploading] = useState<string | null>(null);
  const [uploadInfo, setUploadInfo] = useState<Record<string, string>>({});
  const [dsTest, setDsTest] = useState<DataSourceTest | null>(null);
  const [dsTestLoading, setDsTestLoading] = useState(false);
  const [dsErr, setDsErr] = useState<unknown>(null);
  const [srmAlpha, setSrmAlpha] = useState('0.001');
  const [alertNeg, setAlertNeg] = useState(true);

  // step 5
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState<unknown>(null);
  const [created, setCreated] = useState<Initiative | null>(null);

  // --- caricamento catalogo
  useEffect(() => {
    Promise.all([api.scopes(), api.categories().catch(() => [] as string[])])
      .then(([s, c]) => {
        setScopes(s);
        setCategories(c);
        const def = s.find((x) => x.enabled);
        if (def && !scopeId) setScopeId(def.id);
      })
      .catch(setCatalogErr);
    api
      .dataSourceTypes()
      .then((t) => {
        setDsTypes(t);
        const d = t.find((x) => x.default) ?? t[0];
        if (d) selectDsType(d);
      })
      .catch(setDsErr);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- dettaglio journey
  useEffect(() => {
    setActivityKey(null);
    if (!journeyId) {
      setJourney(null);
      return;
    }
    setJourney(null);
    setJourneyErr(null);
    api.journey(journeyId).then(setJourney).catch(setJourneyErr);
  }, [journeyId]);

  // più journey: l'unico obiettivo sensato è l'incrementalità del journey (un touchpoint è di un solo journey)
  useEffect(() => {
    if (multi && scopeId === 'touchpoint_value') setScopeId('journey_incrementality');
  }, [multi, scopeId]);

  // categoria proposta dalla cartella SFMC del journey di riferimento
  useEffect(() => {
    if (!categoryEdited) setCategory(selected[0]?.folder || '');
  }, [selected, categoryEdited]);

  const scope = scopes?.find((s) => s.id === scopeId);
  const journeySummary = selected[0];
  const totalVolume = selected.reduce((a, j) => a + j.monthly_volume, 0);
  const busyJourneys = selected.filter((j) => j.active_control_groups?.length);
  const isTouchpoint = scopeId === 'touchpoint_value';
  const effectiveActivityKey = isTouchpoint ? activityKey : null;

  // --- posizioni
  const posKey = `${journeyId}|${scopeId}|${effectiveActivityKey ?? ''}|${multi}`;
  const loadPositions = () => {
    if (!journeyId || !scopeId) return;
    setPosLoading(true);
    setPosErr(null);
    const k = posKey;
    api
      .positions(journeyId, scopeId, effectiveActivityKey)
      .then((r0) => {
        // su più journey le attività sono diverse: l'holdout va all'ingresso di ognuno
        const r = multi ? { ...r0, candidates: r0.candidates.filter((c) => !c.activity_key) } : r0;
        setPositions(r);
        setPositionsKey(k);
        const match = r.candidates.find((c) => effectiveActivityKey && c.activity_key === effectiveActivityKey);
        const rec = match ?? r.candidates.find((c) => c.recommended) ?? r.candidates[0];
        setCandidateId(rec?.id ?? null);
      })
      .catch(setPosErr)
      .finally(() => setPosLoading(false));
  };
  useEffect(() => {
    if (step === 1 && positionsKey !== posKey && !posLoading) loadPositions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, posKey]);

  const candidate: Candidate | undefined = positions?.candidates.find((c) => c.id === candidateId);

  // --- prefill sizing
  useEffect(() => {
    if (step !== 2 || !journey || !candidate) return;
    // iniziativa su più journey: il totale somma i volumi di tutti i journey selezionati
    const volume = multi ? totalVolume : candidate.monthly_volume;
    const k = `${journey.id}|${candidate.id}|${volume}`;
    if (k === prefillKey && form) return;
    const sameJourney = prefillKey.startsWith(journey.id + '|') && form;
    const kpiSugg = interp?.kpi_suggestion === 'conversion_rate' ? 'conversion_rate' : 'revenue_per_contact';
    setForm({
      monthly_volume: String(volume),
      baseline_conversion_pct: sameJourney ? form!.baseline_conversion_pct : toStr(journey.baseline.conversion_rate * 100, 3),
      avg_order_value: sameJourney ? form!.avg_order_value : toStr(journey.baseline.avg_order_value, 2),
      expected_lift_pct: toStr((candidate.expected_lift ?? journey.baseline.expected_lift ?? 0.06) * 100, 2),
      duration_days: sameJourney ? form!.duration_days : '60',
      kpi: sameJourney ? form!.kpi : kpiSugg,
      aov_cv: sameJourney ? form!.aov_cv : '1',
      alpha: sameJourney ? form!.alpha : '0.05',
      power_pct: sameJourney ? form!.power_pct : '80',
    });
    setPrefillKey(k);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, journey, candidate, multi, totalVolume]);

  // --- sizing debounced
  const reqObj = useMemo(() => (form ? formToRequest(form) : null), [form]);
  const reqJson = reqObj ? JSON.stringify(reqObj) : '';
  const sizingSeq = useRef(0);
  useEffect(() => {
    if (!reqObj || step < 2) return;
    if (sizingReq && JSON.stringify(sizingReq) === reqJson) return;
    const seq = ++sizingSeq.current;
    const t = setTimeout(() => {
      setSizingLoading(true);
      setSizingErr(null);
      api
        .sizing(reqObj)
        .then((r) => {
          if (seq !== sizingSeq.current) return;
          setSizing(r);
          setSizingReq(reqObj);
          setExplain(null);
          setHoldoutPct((prev) => {
            if (userPicked && prev !== null && r.options.some((o) => Math.abs(o.holdout_pct - prev) < 1e-9)) return prev;
            return defaultPct(r);
          });
        })
        .catch((e) => seq === sizingSeq.current && setSizingErr(e))
        .finally(() => seq === sizingSeq.current && setSizingLoading(false));
    }, 450);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reqJson, step]);

  // --- nome e KPI predefiniti
  useEffect(() => {
    if (nameEdited || !journeySummary || holdoutPct === null) return;
    const where = candidate?.activity_key ? ` (${candidate.label})` : '';
    const pct = `holdout ${Math.round(holdoutPct * 1000) / 10}%`;
    setName(multi ? `${category || 'Iniziativa'} – ${selected.length} journey – ${pct}`
      : `${journeySummary.name} – ${pct}${isTouchpoint ? where : ''}`);
  }, [journeySummary, holdoutPct, nameEdited, candidate, isTouchpoint, multi, selected.length, category]);

  useEffect(() => {
    const k = form?.kpi ?? interp?.kpi_suggestion;
    if (k && KPI_IDS.includes(k as never)) {
      setPrimaryKpi(k);
      setKpis((prev) => (prev.includes(k) ? prev : [...prev, k]));
    }
  }, [form?.kpi, interp?.kpi_suggestion]);

  // --- azioni
  const askAdvisor = async () => {
    if (!question.trim() || !journeyId) return;
    setInterpLoading(true);
    setInterpErr(null);
    try {
      const r = await api.interpret(question.trim(), journeyId);
      setInterp(r);
      const sc = scopes?.find((s) => s.id === r.scope_id);
      if (sc && sc.enabled) setScopeId(r.scope_id);
      if (r.activity_key) setActivityKey(r.activity_key);
    } catch (e) {
      setInterpErr(e);
    } finally {
      setInterpLoading(false);
    }
  };

  const pickActivity = (a: Activity) => {
    if (!MESSAGING.includes(a.type)) return;
    setActivityKey(a.key);
  };

  const runExplain = async () => {
    if (!sizing || !sizingReq) return;
    setExplainLoading(true);
    setExplainErr(null);
    try {
      setExplain(await api.explainSizing(journeyId, scopeId, sizing, sizingReq));
    } catch (e) {
      setExplainErr(e);
    } finally {
      setExplainLoading(false);
    }
  };

  function selectDsType(t: DataSourceType) {
    setDsType(t.type);
    const cfg: Record<string, string> = {};
    t.fields.forEach((f) => (cfg[f.name] = f.default ?? ''));
    setDsConfig(cfg);
    setDsTest(null);
    setUploadInfo({});
    setDsErr(null);
  }

  const uploadFile = async (field: string, file: File) => {
    setUploading(field);
    setDsErr(null);
    try {
      const r = await api.upload(file);
      setDsConfig((c) => ({ ...c, [field]: r.path }));
      setUploadInfo((u) => ({ ...u, [field]: `${file.name} · ${fmtInt(r.rows)} righe · colonne: ${r.columns.join(', ')}` }));
      setDsTest(null);
    } catch (e) {
      setDsErr(e);
    } finally {
      setUploading(null);
    }
  };

  const testDs = async () => {
    setDsTestLoading(true);
    setDsErr(null);
    setDsTest(null);
    try {
      setDsTest(await api.testDataSource({ type: dsType, config: dsConfig }));
    } catch (e) {
      setDsErr(e);
    } finally {
      setDsTestLoading(false);
    }
  };

  const payload: InitiativeCreate | null =
    journeyId && scopeId && candidate && holdoutPct !== null
      ? {
          name: name.trim(),
          journey_ids: selected.map((j) => j.id),
          category: category.trim() || 'Senza categoria',
          scope_id: scopeId,
          activity_key: candidate.activity_key,
          holdout_pct: holdoutPct,
          primary_kpi: primaryKpi,
          kpis: Array.from(new Set([primaryKpi, ...kpis])),
          attribution_days: Math.round(num(attributionDays)) || 30,
          data_source: { type: dsType, config: dsConfig },
          guardrails: { srm_alpha: num(srmAlpha) || 0.001, alert_negative_lift: alertNeg },
        }
      : null;

  const create = async () => {
    if (!payload) return;
    setCreating(true);
    setCreateErr(null);
    try {
      setCreated(await api.createInitiative(payload));
    } catch (e) {
      setCreateErr(e);
    } finally {
      setCreating(false);
    }
  };

  // --- validazione step
  const canNext = [
    !!journeyId && !!scope && scope.enabled,
    !!candidate && (!isTouchpoint || !!candidate.activity_key),
    holdoutPct !== null && !!sizing,
    !!name.trim() && !!category.trim() && kpis.length > 0 && !!dsType && num(attributionDays) > 0,
    true,
  ];
  const go = (s: number) => {
    if (created && s < 4) return;
    setStep(s);
    setMaxStep((m) => Math.max(m, s));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  if (catalogErr) return <ErrorBox error={catalogErr} onRetry={() => window.location.reload()} />;
  if (!scopes) return <Loading text="Caricamento obiettivi…" />;

  const selectedOpt = sizing?.options.find((o) => holdoutPct !== null && Math.abs(o.holdout_pct - holdoutPct) < 1e-9);
  const dsDef = dsTypes?.find((t) => t.type === dsType);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Nuovo control group</h1>
          <p>Cinque passaggi guidati: dall'obiettivo di business al deploy in Marketing Cloud.</p>
        </div>
      </div>

      <div className="stepper">
        {STEPS.map((s, i) => (
          <button
            key={s}
            className={i === step ? 'current' : i < step || i <= maxStep ? (i < step || created ? 'done' : '') : ''}
            disabled={i > maxStep || (!!created && i < 4)}
            onClick={() => go(i)}
            aria-current={i === step ? 'step' : undefined}
          >
            <span className="num">{i < step || (created && i <= 4 && i !== step) ? '✓' : i + 1}</span>
            <span className="lbl">{s}</span>
          </button>
        ))}
      </div>

      {/* STEP 1 */}
      {step === 0 && (
        <div className="stack">
          <div className="card">
            <div className="card-title">
              <h2 style={{ margin: 0 }}>1. Scegli i customer journey</h2>
              {multi && <span className="badge blue">Iniziativa su {selected.length} journey · {fmtInt(totalVolume)} ingressi/mese</span>}
            </div>
            <p className="muted small">
              Cerca nel catalogo della Business Unit. Puoi selezionarne più di uno per misurare un'iniziativa (es. la stessa campagna su più mercati o segmenti):
              ogni journey avrà il suo holdout e il monitoraggio mostrerà il dettaglio per journey e il totale.
            </p>
            <JourneyPicker selected={selected} onChange={setSelected} multi />
            {busyJourneys.length > 0 && (
              <div style={{ marginTop: '0.75rem' }}>
                <Alert kind="warning" title="Già in test:">
                  {busyJourneys.map((j) => `«${j.name}» (${j.active_control_groups!.join(', ')})`).join('; ')}. Un secondo holdout si sovrapporrebbe: il deploy verrà rifiutato.
                </Alert>
              </div>
            )}
            {selected[0] && (
              <div className="row small" style={{ marginTop: '0.75rem', gap: '0.35rem 1rem' }}>
                <span className="muted">Riferimento per advisor e dimensionamento:</span>
                <strong>{selected[0].name}</strong>
                <span><strong>{fmtPct(selected[0].baseline.conversion_rate)}</strong> <span className="muted">conv.</span></span>
                <span><strong>{fmtEur(selected[0].baseline.avg_order_value)}</strong> <span className="muted">scontrino</span></span>
                <span className="muted">{selected[0].activity_count} attività · {selected[0].entry_source}</span>
              </div>
            )}
          </div>

          <div className="card">
            <h2>2. Qual è la domanda di business?</h2>
            <p className="muted small">Descrivi a parole cosa vuoi capire. L'advisor suggerirà l'obiettivo del test più adatto.</p>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Es. L'SMS di reminder serve davvero o possiamo risparmiare? / Il welcome journey porta vendite in più?"
              rows={3}
            />
            <div className="row" style={{ marginTop: '0.6rem' }}>
              <button className="btn primary" onClick={askAdvisor} disabled={!question.trim() || interpLoading || !journeyId}>
                {interpLoading ? <Spinner /> : null} Chiedi all'advisor
              </button>
              <span className="muted small">Facoltativo: puoi anche scegliere direttamente l'obiettivo qui sotto.</span>
            </div>
            {interpLoading && <div style={{ marginTop: '0.75rem' }}><Thinking /></div>}
            {!!interpErr && <div style={{ marginTop: '0.75rem' }}><ErrorBox error={interpErr} /></div>}
            {interp && !interpLoading && (
              <div style={{ marginTop: '0.9rem' }}>
                <AdvisorBox
                  title="Interpretazione dell'advisor"
                  source={interp.source}
                  extra={<span className={`badge ${interp.confidence === 'alta' ? 'green' : interp.confidence === 'media' ? 'amber' : 'red'}`}>confidenza {interp.confidence}</span>}
                >
                  <div style={{ marginBottom: 6 }}>
                    Obiettivo suggerito: <strong>{scopes.find((s) => s.id === interp.scope_id)?.name ?? interp.scope_id}</strong>
                    {interp.activity_key && (
                      <> · attività: <strong>{journey?.activities.find((a) => a.key === interp.activity_key)?.name ?? interp.activity_key}</strong></>
                    )}
                    {' · '}KPI: <strong>{KPI_LABELS[interp.kpi_suggestion] ?? interp.kpi_suggestion}</strong>
                  </div>
                  {interp.rationale}
                </AdvisorBox>
              </div>
            )}
          </div>

          <div className="card">
            <h2>3. Obiettivo del test</h2>
            <div className="grid grid-2" style={{ marginTop: '0.75rem' }}>
              {scopes.map((s) => (
                <button key={s.id} className={`selectable${s.id === scopeId ? ' selected' : ''}`} disabled={!s.enabled || (multi && s.id === 'touchpoint_value')} onClick={() => setScopeId(s.id)}>
                  <div className="sel-head">
                    <h3>{s.name}</h3>
                    <div className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
                      {interp?.scope_id === s.id && s.enabled && <span className="badge violet">Suggerito</span>}
                      {!s.enabled && <span className="badge">Prossimamente</span>}
                      {s.enabled && <span className="radio-mark" />}
                    </div>
                  </div>
                  <p style={{ fontStyle: 'italic', marginBottom: 6, color: 'var(--text)' }}>«{s.question}»</p>
                  <p>{s.description}</p>
                  <div className="row small" style={{ marginTop: 8 }}>
                    <span className="badge">Posizione: {s.position_rule}</span>
                    <span className="badge">Volume richiesto: {s.volume_need}</span>
                  </div>
                  {!s.enabled && s.disabled_reason && <p className="small" style={{ marginTop: 6 }}>{s.disabled_reason}</p>}
                  {s.enabled && multi && s.id === 'touchpoint_value' && (
                    <p className="small" style={{ marginTop: 6 }}>Non disponibile con più journey: un touchpoint è un messaggio di un journey specifico.</p>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* STEP 2 */}
      {step === 1 && (
        <div className="stack">
          <div className="card">
            <div className="card-title">
              <h2>{journey?.name ?? 'Journey'} — dove inserire l'holdout</h2>
              <span className="badge blue">{scope?.name}</span>
            </div>
            {multi && (
              <div style={{ marginBottom: '0.75rem' }}>
                <Alert kind="info">
                  Iniziativa su {selected.length} journey: l'holdout viene inserito <strong>all'ingresso di ciascun journey</strong>, con la stessa percentuale.
                  Il diagramma mostra il journey di riferimento.
                </Alert>
              </div>
            )}
            {isTouchpoint && (
              <Alert kind="info">
                Obiettivo «valore del touchpoint»: clicca sul diagramma il messaggio (email, SMS o push) da valutare.
                {activityKey && journey && <> Selezionato: <strong>{journey.activities.find((a) => a.key === activityKey)?.name ?? activityKey}</strong>.</>}
              </Alert>
            )}
            <div style={{ marginTop: '0.9rem' }}>
              {!journey && !journeyErr && <Loading />}
              <ErrorBox error={journeyErr} />
              {journey && (
                <JourneyDiagram
                  activities={journey.activities}
                  candidates={positions && positionsKey === posKey ? positions.candidates : []}
                  selectedCandidateId={candidateId}
                  onSelectCandidate={(c) => setCandidateId(c.id)}
                  onPickActivity={isTouchpoint ? pickActivity : undefined}
                  pickedActivityKey={isTouchpoint ? activityKey : null}
                />
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-title">
              <h2>Posizioni candidate</h2>
              {positions && <SourceBadge source={positions.source} />}
            </div>
            {isTouchpoint && !activityKey && !posLoading && (
              <p className="muted">Seleziona un'attività di messaggistica sul diagramma per ottenere le posizioni consigliate.</p>
            )}
            {posLoading && <Thinking />}
            {!!posErr && <ErrorBox error={posErr} onRetry={loadPositions} />}
            {positions && !posLoading && (
              <>
                {positions.narrative && (
                  <div style={{ marginBottom: '1rem' }}>
                    <AdvisorBox title="Il parere dell'advisor" source={positions.source}>{positions.narrative}</AdvisorBox>
                  </div>
                )}
                <div className="grid grid-2">
                  {positions.candidates.map((c, i) => (
                    <button key={c.id} className={`selectable${c.id === candidateId ? ' selected' : ''}`} onClick={() => setCandidateId(c.id)}>
                      <div className="sel-head">
                        <h3>
                          <span className="badge blue" style={{ marginRight: 6 }}>{i + 1}</span>
                          {c.label}
                        </h3>
                        <div className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
                          {c.recommended && <span className="badge green">Consigliata</span>}
                          <span className="radio-mark" />
                        </div>
                      </div>
                      <p style={{ marginBottom: 8 }}>{c.description}</p>
                      <div className="small" style={{ marginBottom: 8 }}>
                        Volume: <strong>{fmtInt(c.monthly_volume)}</strong> <span className="muted">contatti/mese</span>
                      </div>
                      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                        <div>
                          <div className="small pos" style={{ fontWeight: 700 }}>Pro</div>
                          <ul className="small" style={{ margin: 0, paddingLeft: '1.1rem' }}>
                            {c.pros.map((p, k) => <li key={k}>{p}</li>)}
                          </ul>
                        </div>
                        <div>
                          <div className="small neg" style={{ fontWeight: 700 }}>Contro</div>
                          <ul className="small" style={{ margin: 0, paddingLeft: '1.1rem' }}>
                            {c.cons.map((p, k) => <li key={k}>{p}</li>)}
                          </ul>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
                {positions.candidates.length === 0 && <p className="muted">Nessuna posizione candidata.</p>}
              </>
            )}
          </div>
        </div>
      )}

      {/* STEP 3 */}
      {step === 2 && form && (
        <div className="stack">
          <div className="card">
            <div className="card-title">
              <h2>Parametri di dimensionamento</h2>
              {candidate && <span className="muted small">Posizione: <strong>{candidate.label}</strong></span>}
            </div>
            <div className="form-grid">
              <NumField label="Volume mensile" hint="contatti/mese nel punto di holdout" value={form.monthly_volume} onChange={(v) => setForm({ ...form, monthly_volume: v })} step="100" />
              <NumField label="Conversione baseline" suffix="%" value={form.baseline_conversion_pct} onChange={(v) => setForm({ ...form, baseline_conversion_pct: v })} step="0.1" />
              <NumField label="Scontrino medio" suffix="€" value={form.avg_order_value} onChange={(v) => setForm({ ...form, avg_order_value: v })} step="1" />
              <NumField label="Lift atteso" hint="incremento relativo atteso" suffix="%" value={form.expected_lift_pct} onChange={(v) => setForm({ ...form, expected_lift_pct: v })} step="0.5" />
              <NumField label="Durata del test" suffix="gg" value={form.duration_days} onChange={(v) => setForm({ ...form, duration_days: v })} step="5" />
              <label className="field">
                KPI di dimensionamento
                <select value={form.kpi} onChange={(e) => setForm({ ...form, kpi: e.target.value })}>
                  <option value="revenue_per_contact">{KPI_LABELS.revenue_per_contact}</option>
                  <option value="conversion_rate">{KPI_LABELS.conversion_rate}</option>
                </select>
              </label>
            </div>
            <details className="adv">
              <summary>Avanzate</summary>
              <div className="form-grid">
                <NumField label="CV scontrino" hint="variabilità del valore ordine" value={form.aov_cv} onChange={(v) => setForm({ ...form, aov_cv: v })} step="0.1" />
                <NumField label="Alpha (significatività)" value={form.alpha} onChange={(v) => setForm({ ...form, alpha: v })} step="0.01" />
                <NumField label="Potenza statistica" suffix="%" value={form.power_pct} onChange={(v) => setForm({ ...form, power_pct: v })} step="5" />
              </div>
            </details>
            {!reqObj && <div style={{ marginTop: '0.75rem' }}><Alert kind="warning">Controlla i parametri: alcuni valori non sono validi.</Alert></div>}
          </div>

          {sizingLoading && !sizing && <Loading text="Calcolo in corso…" />}
          {!!sizingErr && <ErrorBox error={sizingErr} />}
          {sizing && (
            <>
              <div className="card">
                <div className="verdict" style={{ opacity: sizingLoading ? 0.6 : 1 }}>
                  <div className="traffic" aria-hidden>
                    <span className={VERDICT[sizing.verdict] === 'red' ? 'on red' : ''} />
                    <span className={VERDICT[sizing.verdict] === 'amber' ? 'on amber' : ''} />
                    <span className={VERDICT[sizing.verdict] === 'green' ? 'on green' : ''} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="row">
                      <span className="verdict-title">{sizing.verdict}</span>
                      {sizing.recommended_pct != null && <span className="badge blue">Consigliato: holdout {fmtPct(sizing.recommended_pct)}</span>}
                      {sizingLoading && <Spinner />}
                    </div>
                    <p style={{ margin: '0.3rem 0 0' }}>{sizing.explanation}</p>
                  </div>
                </div>
                {!sizing.feasible && (
                  <div style={{ marginTop: '0.9rem' }}>
                    <Alert kind="warning" title="Attenzione:">
                      con questi volumi il test difficilmente rileverà il lift atteso. Puoi proseguire comunque, ma valuta di aumentare la durata, l'holdout o il volume.
                      {isTouchpoint && (
                        <div style={{ marginTop: 8 }}>
                          Suggerimento: un touchpoint singolo ha meno volume e un effetto più piccolo. Misurare l'<strong>incrementalità dell'intero journey</strong> richiede meno campione.
                          <div style={{ marginTop: 8 }}>
                            <button className="btn sm" onClick={() => { setScopeId('journey_incrementality'); go(1); }}>
                              Passa a «Incrementalità del journey»
                            </button>
                          </div>
                        </div>
                      )}
                    </Alert>
                  </div>
                )}
                <div className="row" style={{ marginTop: '1rem' }}>
                  <button className="btn" onClick={runExplain} disabled={explainLoading || sizingLoading}>
                    {explainLoading && <Spinner />} Spiegazione advisor
                  </button>
                </div>
                {explainLoading && <div style={{ marginTop: '0.75rem' }}><Thinking /></div>}
                {!!explainErr && <div style={{ marginTop: '0.75rem' }}><ErrorBox error={explainErr} /></div>}
                {explain && !explainLoading && (
                  <div style={{ marginTop: '0.75rem' }}>
                    <AdvisorBox title="Spiegazione dell'advisor" source={explain.source}>{explain.narrative}</AdvisorBox>
                  </div>
                )}
              </div>

              <div className="grid sizing-grid">
                <div className="card">
                  <h3>Opzioni di holdout</h3>
                  <p className="muted small">Clicca una riga per scegliere la percentuale.</p>
                  <div className="table-wrap">
                    <table className="compact">
                      <thead>
                        <tr>
                          <th className="num">Holdout</th>
                          <th className="num">Controllo</th>
                          <th className="num">MDE</th>
                          <th className="num" title="Giorni necessari per rilevare il lift atteso">Giorni necessari</th>
                          <th className="num" title="Vendite attese perse nel periodo tenendo fuori il gruppo">Costo opport.</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sizing.options.map((o) => {
                          const sel = holdoutPct !== null && Math.abs(o.holdout_pct - holdoutPct) < 1e-9;
                          const rec = sizing.recommended_pct != null && Math.abs(o.holdout_pct - sizing.recommended_pct) < 1e-9;
                          return (
                            <tr
                              key={o.holdout_pct}
                              className={`clickable${sel ? ' selected-row' : rec ? ' recommended' : ''}`}
                              onClick={() => { setHoldoutPct(o.holdout_pct); setUserPicked(true); }}
                            >
                              <td className="num">
                                <strong>{fmtPct(o.holdout_pct)}</strong>
                                {rec && <span className="badge green" style={{ marginLeft: 6 }}>consigliato</span>}
                              </td>
                              <td className="num">{fmtInt(o.control_size)}</td>
                              <td className="num">
                                <span className={o.detectable ? 'pos' : 'neg'}>{fmtPct(o.mde_relative)}</span>
                              </td>
                              <td className="num">{o.days_to_detect === null ? <span className="muted">&gt; 365</span> : fmtInt(o.days_to_detect)}</td>
                              <td className="num">{fmtEur(o.opportunity_cost)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {sizing.assumptions && (
                    <p className="muted small" style={{ marginTop: '0.6rem', marginBottom: 0 }}>
                      Ipotesi: {Object.entries(sizing.assumptions).filter(([k]) => k in ASSUMPTION_LABELS).map(([k, v]) => `${ASSUMPTION_LABELS[k] ?? k}: ${typeof v === 'number' ? (k.includes('revenue') ? fmtEur2(v) : fmtInt(v)) : v}`).join(' · ')}
                    </p>
                  )}
                </div>
                <div className="card">
                  <h3>MDE rilevabile vs % holdout</h3>
                  <p className="muted small">Più grande il gruppo di controllo, più piccolo l'effetto che il test può rilevare.</p>
                  <MdeChart
                    options={sizing.options}
                    expectedLift={sizingReq?.expected_lift ?? 0.06}
                    selectedPct={holdoutPct}
                    recommendedPct={sizing.recommended_pct ?? null}
                    onSelect={(p) => { setHoldoutPct(p); setUserPicked(true); }}
                  />
                </div>
              </div>
              {selectedOpt && (
                <Alert kind="info" title={`Holdout selezionato: ${fmtPct(selectedOpt.holdout_pct)}`}>
                  — {fmtInt(selectedOpt.control_size)} contatti nel gruppo di controllo, effetto minimo rilevabile {fmtPct(selectedOpt.mde_relative)}, costo opportunità stimato {fmtEur(selectedOpt.opportunity_cost)}.
                </Alert>
              )}
            </>
          )}
        </div>
      )}
      {step === 2 && !form && <Loading />}

      {/* STEP 4 */}
      {step === 3 && (
        <div className="stack">
          <div className="card">
            <h2>Nome, categoria e KPI</h2>
            <div className="form-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
              <label className="field" style={{ gridColumn: '1 / -1' }}>
                {multi ? "Nome dell'iniziativa" : 'Nome del control group'}
                <input type="text" value={name} onChange={(e) => { setName(e.target.value); setNameEdited(true); }} />
                {multi && <span className="hint">Ogni journey avrà un holdout chiamato «{name || '…'} · nome del journey».</span>}
              </label>
              <label className="field">
                Categoria
                {!newCategory ? (
                  <select
                    value={category}
                    onChange={(e) => {
                      if (e.target.value === '__new__') { setNewCategory(true); setCategory(''); } else setCategory(e.target.value);
                      setCategoryEdited(true);
                    }}
                  >
                    <option value="" disabled>Scegli una categoria…</option>
                    {[...new Set([...categories, ...(category ? [category] : [])])].map((c) => <option key={c} value={c}>{c}</option>)}
                    <option value="__new__">+ Nuova categoria…</option>
                  </select>
                ) : (
                  <div className="row" style={{ flexWrap: 'nowrap' }}>
                    <input type="text" autoFocus value={category} placeholder="Es. Black Friday" onChange={(e) => { setCategory(e.target.value); setCategoryEdited(true); }} />
                    <button className="btn sm" onClick={() => setNewCategory(false)}>Elenco</button>
                  </div>
                )}
                <span className="hint">Serve a raggruppare i control group nel monitoraggio per categoria.</span>
              </label>
              <label className="field">
                KPI primario
                <select
                  value={primaryKpi}
                  onChange={(e) => {
                    setPrimaryKpi(e.target.value);
                    setKpis((k) => (k.includes(e.target.value) ? k : [...k, e.target.value]));
                  }}
                >
                  {KPI_IDS.map((k) => <option key={k} value={k}>{KPI_LABELS[k]}</option>)}
                </select>
              </label>
              <NumField label="Finestra di attribuzione" hint="giorni dopo l'ingresso in cui un acquisto viene attribuito" suffix="gg" value={attributionDays} onChange={setAttributionDays} step="1" />
            </div>
            <div style={{ marginTop: '1rem' }}>
              <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>KPI monitorati</div>
              <div className="row" style={{ gap: '0.5rem 1.5rem' }}>
                {KPI_IDS.map((k) => (
                  <label key={k} className="check">
                    <input
                      type="checkbox"
                      checked={kpis.includes(k)}
                      disabled={k === primaryKpi}
                      onChange={(e) => setKpis((prev) => (e.target.checked ? [...prev, k] : prev.filter((x) => x !== k)))}
                    />
                    {KPI_LABELS[k]} {k === primaryKpi && <span className="badge blue">primario</span>}
                  </label>
                ))}
              </div>
            </div>
          </div>

          <div className="card">
            <h2>Sorgente dati vendite</h2>
            {!dsTypes && !dsErr && <Loading />}
            {dsTypes && (
              <>
                <div className="grid grid-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
                  {dsTypes.map((t) => (
                    <button key={t.type} className={`selectable${t.type === dsType ? ' selected' : ''}`} onClick={() => selectDsType(t)}>
                      <div className="sel-head">
                        <h3>{t.name}</h3>
                        <span className="radio-mark" />
                      </div>
                      <p>{t.description}</p>
                    </button>
                  ))}
                </div>
                {dsDef && (
                  <div className="form-grid" style={{ marginTop: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
                    {dsDef.fields.map((f) => (
                      <FieldWrap key={f.name} isFile={f.kind === 'file'} wide={f.kind === 'textarea' || f.kind === 'file'}>
                        {f.label}
                        {f.kind === 'textarea' ? (
                          <textarea className="mono" value={dsConfig[f.name] ?? ''} onChange={(e) => setDsConfig({ ...dsConfig, [f.name]: e.target.value })} rows={5} />
                        ) : f.kind === 'file' ? (
                          <>
                            <div className="row" style={{ flexWrap: 'nowrap', gap: '0.5rem' }}>
                              <input type="text" value={dsConfig[f.name] ?? ''} onChange={(e) => { setDsConfig({ ...dsConfig, [f.name]: e.target.value }); setDsTest(null); }} placeholder="percorso del file sul server" />
                              <span className="btn sm file-btn" role="button" tabIndex={0}>
                                {uploading === f.name ? <Spinner /> : '⤒'} Carica…
                                <input
                                  type="file"
                                  accept=".csv,text/csv"
                                  aria-label="Carica file CSV"
                                  onChange={(e) => { const file = e.target.files?.[0]; if (file) uploadFile(f.name, file); e.target.value = ''; }}
                                />
                              </span>
                            </div>
                            {uploadInfo[f.name] && <span className="hint">Caricato: {uploadInfo[f.name]}</span>}
                            <span className="hint">
                              Lascia il percorso predefinito per usare i dati di esempio, oppure carica un tuo export.{' '}
                              <a href={SAMPLE_CSV_URL} download="sales.csv">⤓ Scarica CSV di esempio</a>
                            </span>
                          </>
                        ) : (
                          <input
                            type={f.kind === 'password' ? 'password' : 'text'}
                            value={dsConfig[f.name] ?? ''}
                            onChange={(e) => setDsConfig({ ...dsConfig, [f.name]: e.target.value })}
                            autoComplete={f.kind === 'password' ? 'new-password' : 'off'}
                          />
                        )}
                      </FieldWrap>
                    ))}
                  </div>
                )}
                <div className="row" style={{ marginTop: '1rem' }}>
                  <button className="btn" onClick={testDs} disabled={dsTestLoading || !dsType}>
                    {dsTestLoading && <Spinner />} Testa connessione
                  </button>
                </div>
              </>
            )}
            {!!dsErr && <div style={{ marginTop: '0.75rem' }}><ErrorBox error={dsErr} /></div>}
            {dsTest && (
              <div style={{ marginTop: '0.9rem' }} className="stack">
                <Alert kind={dsTest.ok ? 'ok' : 'error'} title={dsTest.ok ? 'Connessione riuscita.' : 'Connessione fallita.'}>{dsTest.message}</Alert>
                {dsTest.columns?.length > 0 && (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>{dsTest.columns.map((c) => <th key={c}>{c}</th>)}</tr>
                      </thead>
                      <tbody>
                        {dsTest.sample?.map((r, i) => (
                          <tr key={i}>{dsTest.columns.map((c) => <td key={c}>{r[c] === null || r[c] === undefined ? '' : String(r[c])}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="card">
            <h2>Guardrail</h2>
            <div className="form-grid" style={{ alignItems: 'end' }}>
              <NumField label="Soglia SRM (alpha)" hint="test chi-quadro sullo sbilanciamento dei gruppi" value={srmAlpha} onChange={setSrmAlpha} step="0.001" />
              <label className="check" style={{ paddingBottom: '0.55rem' }}>
                <input type="checkbox" checked={alertNeg} onChange={(e) => setAlertNeg(e.target.checked)} />
                Avvisa in caso di lift negativo significativo
              </label>
            </div>
          </div>
        </div>
      )}

      {/* STEP 5 */}
      {step === 4 && (
        <div className="stack">
          {!created && (
            <div className="card">
              <h2>Riepilogo</h2>
              <div className="summary-grid" style={{ marginTop: '0.75rem' }}>
                <div>
                  <h3>Obiettivo</h3>
                  <dl className="dl">
                    <dt>{multi ? `Journey (${selected.length})` : 'Journey'}</dt>
                    <dd>{multi ? <ul className="plain-list">{selected.map((j) => <li key={j.id}>{j.name}</li>)}</ul> : journeySummary?.name}</dd>
                    <dt>Categoria</dt><dd>{category}</dd>
                    <dt>Obiettivo</dt><dd>{scope?.name}</dd>
                    <dt>Posizione</dt><dd>{candidate?.label}</dd>
                    <dt>Volume</dt><dd>{fmtInt(multi ? totalVolume : candidate?.monthly_volume)} /mese</dd>
                  </dl>
                </div>
                <div>
                  <h3>Dimensione</h3>
                  <dl className="dl">
                    <dt>Holdout</dt><dd><strong>{fmtPct(holdoutPct)}</strong></dd>
                    <dt>Esito</dt><dd>{sizing?.verdict}</dd>
                    <dt>MDE</dt><dd>{fmtPct(selectedOpt?.mde_relative)}</dd>
                    <dt>Lift atteso</dt><dd>{fmtLift(sizingReq?.expected_lift)}</dd>
                    <dt>Costo opp.</dt><dd>{fmtEur(selectedOpt?.opportunity_cost)}</dd>
                  </dl>
                </div>
                <div>
                  <h3>Monitoraggio</h3>
                  <dl className="dl">
                    <dt>Nome</dt><dd>{name}</dd>
                    <dt>KPI primario</dt><dd>{KPI_LABELS[primaryKpi]}</dd>
                    <dt>Altri KPI</dt><dd>{kpis.filter((k) => k !== primaryKpi).map((k) => KPI_LABELS[k]).join(', ') || '—'}</dd>
                    <dt>Attribuzione</dt><dd>{attributionDays} giorni</dd>
                    <dt>Sorgente</dt><dd>{dsDef?.name ?? dsType}</dd>
                    <dt>Guardrail</dt><dd>SRM α {srmAlpha}{alertNeg ? ' · alert lift negativo' : ''}</dd>
                  </dl>
                </div>
              </div>
              {sizing && !sizing.feasible && (
                <div style={{ marginTop: '1rem' }}>
                  <Alert kind="warning" title="Nota:">il dimensionamento è risultato «{sizing.verdict}». Il test potrebbe non essere conclusivo.</Alert>
                </div>
              )}
              {busyJourneys.length > 0 && (
                <div style={{ marginTop: '1rem' }}>
                  <Alert kind="warning" title="Journey già in test:">
                    {busyJourneys.map((j) => `su «${j.name}» è già attivo «${j.active_control_groups!.join('», «')}»`).join('; ')}. Un secondo holdout si sovrapporrebbe e il deploy verrà rifiutato.
                  </Alert>
                </div>
              )}
              {!payload && <div style={{ marginTop: '1rem' }}><Alert kind="error">Configurazione incompleta: torna ai passaggi precedenti.</Alert></div>}
              <div className="row" style={{ marginTop: '1.25rem' }}>
                <button className="btn primary lg" onClick={create} disabled={!payload || creating || !name.trim()}>
                  {creating && <Spinner />} Crea in SFMC{multi ? ` (${selected.length} journey)` : ''}
                </button>
                {creating && <span className="muted">Creazione di Data Extension, query e automation{multi ? ' per ogni journey' : ''}…</span>}
              </div>
              {!!createErr && (
                <div style={{ marginTop: '0.75rem' }}>
                  {createErr instanceof ApiError && createErr.status === 409 ? (
                    <Alert kind="error" title="Deploy non consentito:">{createErr.message}</Alert>
                  ) : (
                    <ErrorBox error={createErr} />
                  )}
                </div>
              )}
            </div>
          )}
          {created && (
            <>
              <div className="card">
                <div className="card-title">
                  <div>
                    <h2>{created.journeys.length > 1 ? 'Iniziativa creata' : 'Control group creato'}</h2>
                    <div className="muted small">{created.name} · {created.category} · {created.journeys.length} journey</div>
                  </div>
                  <button className="btn primary" onClick={() => navigate(`/iniziativa/${created.id}`)}>Vai al monitoraggio →</button>
                </div>
              </div>
              {(created.control_groups ?? []).map((cg) => (
                <div className="card" key={cg.id}>
                  <div className="card-title">
                    <h3 style={{ margin: 0 }}>{cg.journey_name}</h3>
                    <span className="muted small"><span className="mono">{cg.id}</span> · salt <span className="mono">{cg.salt}</span></span>
                  </div>
                  <h3>Esito del deploy</h3>
                  <DeployLog log={cg.deploy_log} />
                  <details className="adv">
                    <summary>Artefatti SFMC di questo journey</summary>
                    <ArtifactsView artifacts={cg.artifacts} />
                  </details>
                </div>
              ))}
              <div className="row">
                <button className="btn primary" onClick={() => navigate(`/iniziativa/${created.id}`)}>Vai al monitoraggio →</button>
                <Link to="/" className="btn">Torna alla dashboard</Link>
              </div>
            </>
          )}
        </div>
      )}

      {!created && (
        <div className="wizard-nav">
          <button className="btn" onClick={() => go(step - 1)} disabled={step === 0}>
            ← Indietro
          </button>
          {step < 4 && (
            <button className="btn primary" onClick={() => go(step + 1)} disabled={!canNext[step]}>
              Avanti: {STEPS[step + 1]} →
            </button>
          )}
        </div>
      )}
      {(step === 1 && isTouchpoint && candidate && !candidate.activity_key && !posLoading) && (
        <p className="muted small" style={{ textAlign: 'right' }}>Seleziona un messaggio sul diagramma per proseguire.</p>
      )}
    </div>
  );
}

const ASSUMPTION_LABELS: Record<string, string> = {
  entrants_in_period: 'ingressi nel periodo',
  revenue_per_contact: 'ricavo per contatto',
};

function NumField({ label, hint, suffix, value, onChange, step }: { label: string; hint?: string; suffix?: string; value: string; onChange: (v: string) => void; step?: string }) {
  return (
    <label className="field">
      {label}
      <div className={suffix ? 'input-suffix' : undefined}>
        <input type="number" inputMode="decimal" value={value} step={step} min={0} onChange={(e) => onChange(e.target.value)} />
        {suffix && <span>{suffix}</span>}
      </div>
      {hint && <span className="hint">{hint}</span>}
    </label>
  );
}

function FieldWrap({ isFile, wide, children }: { isFile: boolean; wide: boolean; children: React.ReactNode }) {
  const style = wide ? { gridColumn: '1 / -1' } : undefined;
  return isFile ? <div className="field label-like" style={style}>{children}</div> : <label className="field" style={style}>{children}</label>;
}
