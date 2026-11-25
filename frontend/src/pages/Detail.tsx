import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, KPI_LABELS, NarrativeResponse, Results } from '../api';
import ArtifactsView, { DeployLog } from '../components/ArtifactsView';
import JourneyDiagram from '../components/JourneyDiagram';
import ResultsView from '../components/ResultsView';
import ExportUpload from '../components/ExportUpload';
import { AdvisorBox, ErrorBox, Loading, Modal, Spinner, StatusBadge, Tabs, Thinking, useLoad } from '../components/ui';
import { fmtDate, fmtPct } from '../format';

type Tab = 'risultati' | 'artefatti' | 'configurazione';

export default function Detail() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const cg = useLoad(() => api.controlGroup(id), [id]);
  const res = useLoad(() => api.results(id), [id]);
  const journey = useLoad(() => (cg.data ? api.journey(cg.data.journey_id) : Promise.resolve(null)), [cg.data?.journey_id]);
  const health = useLoad(() => api.health());
  const [tab, setTab] = useState<Tab>('risultati');
  const [refreshing, setRefreshing] = useState(false);
  const [refreshErr, setRefreshErr] = useState<unknown>(null);
  const [narr, setNarr] = useState<NarrativeResponse | null>(null);
  const [narrLoading, setNarrLoading] = useState(false);
  const [narrErr, setNarrErr] = useState<unknown>(null);
  const [confirmDel, setConfirmDel] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [delErr, setDelErr] = useState<unknown>(null);

  const refresh = async () => {
    setRefreshing(true);
    setRefreshErr(null);
    try {
      const r: Results = await api.refresh(id);
      res.setData(r);
    } catch (e) {
      setRefreshErr(e);
    } finally {
      setRefreshing(false);
    }
  };
  const loadNarr = async () => {
    setNarrLoading(true);
    setNarrErr(null);
    try {
      setNarr(await api.narrative(id));
    } catch (e) {
      setNarrErr(e);
    } finally {
      setNarrLoading(false);
    }
  };
  const del = async () => {
    setDeleting(true);
    setDelErr(null);
    try {
      await api.deleteControlGroup(id);
      navigate('/');
    } catch (e) {
      setDelErr(e);
      setDeleting(false);
    }
  };

  if (cg.loading) return <Loading />;
  if (cg.error) return (
    <div className="stack">
      <ErrorBox error={cg.error} onRetry={cg.reload} />
      <Link to="/">← Torna alla dashboard</Link>
    </div>
  );
  const c = cg.data!;
  const r = res.data;

  return (
    <div>
      <div style={{ marginBottom: '0.75rem' }} className="small">
        <Link to="/">Dashboard</Link> / <Link to={`/iniziativa/${c.initiative_id}`}>{c.initiative_name}</Link> / {c.journey_name}
      </div>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <div className="eyebrow">{c.category} · customer journey</div>
          <div className="row" style={{ marginBottom: 4 }}>
            <h1 style={{ margin: 0 }}>{c.name}</h1>
            <StatusBadge status={c.status} />
          </div>
          <p>
            {c.journey_name} · {c.activity_name ? `holdout prima di «${c.activity_name}»` : "holdout all'ingresso"} · <strong>{fmtPct(c.holdout_pct)}</strong> nel gruppo di controllo · KPI primario {KPI_LABELS[c.primary_kpi] ?? c.primary_kpi} · creato il {fmtDate(c.created_at)}
          </p>
        </div>
        <div className="row">
          <button className="btn" onClick={refresh} disabled={refreshing}>
            {refreshing ? <Spinner /> : '↻'} Aggiorna dati
          </button>
          <button className="btn" onClick={loadNarr} disabled={narrLoading || !r}>
            {narrLoading && <Spinner />} Commento advisor
          </button>
          <button className="btn danger" onClick={() => setConfirmDel(true)}>Elimina</button>
        </div>
      </div>

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'risultati', label: 'Risultati' },
          { id: 'artefatti', label: 'Artefatti SFMC' },
          { id: 'configurazione', label: 'Configurazione' },
        ]}
      />

      {tab === 'risultati' && (
        <div className="stack">
          {!!refreshErr && <ErrorBox error={refreshErr} />}
          {narrLoading && <Thinking />}
          {!!narrErr && <ErrorBox error={narrErr} />}
          {narr && !narrLoading && <AdvisorBox title="Commento dell'advisor" source={narr.source}>{narr.narrative}</AdvisorBox>}
          {res.loading && !r && <Loading text="Caricamento risultati…" />}
          {!!res.error && <ErrorBox error={res.error} onRetry={res.reload} />}
          {health.data?.sfmc_mode === 'file' && (
            <ExportUpload cgId={c.id} fileName={c.artifacts.export_file} folder={health.data.sfmc_export_dir} onLoaded={(x) => res.setData(x)} />
          )}
          {r && <ResultsView r={r} primaryLabel={KPI_LABELS[c.primary_kpi]} />}
        </div>
      )}

      {tab === 'artefatti' && (
        <div className="stack">
          <div className="card">
            <ArtifactsView artifacts={c.artifacts} />
          </div>
          <div className="card">
            <h3>Esito del deploy</h3>
            <DeployLog log={c.deploy_log} />
          </div>
        </div>
      )}

      {tab === 'configurazione' && (
        <div className="stack">
          <div className="card">
            <dl className="dl">
              <dt>ID</dt><dd className="mono">{c.id}</dd>
              <dt>Iniziativa</dt><dd><Link to={`/iniziativa/${c.initiative_id}`}>{c.initiative_name}</Link></dd>
              <dt>Categoria</dt><dd>{c.category}</dd>
              <dt>Journey</dt><dd>{c.journey_name} <span className="mono muted">({c.journey_id})</span></dd>
              <dt>Obiettivo</dt><dd>{c.scope_id}</dd>
              <dt>Posizione</dt><dd>{c.activity_name ? `Prima di «${c.activity_name}»` : "Subito dopo l'ingresso"}</dd>
              <dt>Holdout</dt><dd>{fmtPct(c.holdout_pct)}</dd>
              <dt>KPI</dt><dd>{c.kpis.map((k) => KPI_LABELS[k] ?? k).join(', ')}</dd>
              <dt>Attribuzione</dt><dd>{c.attribution_days} giorni</dd>
              <dt>Sorgente dati</dt><dd>{c.data_source.type} <span className="mono muted">{Object.entries(c.data_source.config ?? {}).filter(([k]) => !/pass|secret/i.test(k)).map(([k, v]) => `${k}=${v}`).join(' · ')}</span></dd>
              <dt>Guardrail</dt><dd>SRM α {c.guardrails.srm_alpha}{c.guardrails.alert_negative_lift ? ' · alert su lift negativo' : ''}</dd>
              <dt>Salt</dt><dd className="mono">{c.salt}</dd>
            </dl>
          </div>
          {journey.data && (
            <div className="card">
              <h3>Punto di holdout nel journey</h3>
              <JourneyDiagram activities={journey.data.activities} holdoutActivityKey={c.activity_key} showHoldout />
            </div>
          )}
        </div>
      )}

      {confirmDel && (
        <Modal onClose={() => !deleting && setConfirmDel(false)}>
          <h2>Eliminare il control group?</h2>
          <p className="muted">«{c.name}» verrà rimosso dall'applicazione. Gli artefatti già creati in Marketing Cloud non vengono cancellati automaticamente.</p>
          {!!delErr && <ErrorBox error={delErr} />}
          <div className="row" style={{ justifyContent: 'flex-end', marginTop: '1rem' }}>
            <button className="btn" onClick={() => setConfirmDel(false)} disabled={deleting}>Annulla</button>
            <button className="btn danger" onClick={del} disabled={deleting}>{deleting && <Spinner />} Elimina</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
