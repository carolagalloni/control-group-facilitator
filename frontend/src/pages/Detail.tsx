import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, KPI_LABELS, KpiResult, NarrativeResponse, Results } from '../api';
import ArtifactsView, { DeployLog } from '../components/ArtifactsView';
import JourneyDiagram from '../components/JourneyDiagram';
import { LiftChart } from '../components/Charts';
import { AdvisorBox, ErrorBox, Loading, Modal, Spinner, StatusBadge, Tabs, Thinking, useLoad } from '../components/ui';
import { fmtDate, fmtEur, fmtInt, fmtKpi, fmtLift, fmtP, fmtPEq, fmtPct } from '../format';

type Tab = 'risultati' | 'artefatti' | 'configurazione';

function KpiCard({ k }: { k: KpiResult }) {
  const cls = k.significant ? (k.rel_lift >= 0 ? 'pos' : 'neg') : '';
  return (
    <div className={`card kpi-card${k.primary ? ' primary' : ''}`}>
      <div className="row between" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
        <span className="kpi-name">{k.name || KPI_LABELS[k.id] || k.id}</span>
        {k.primary && <span className="badge blue">primario</span>}
      </div>
      <div className={`kpi-lift ${cls}`}>{fmtLift(k.rel_lift)}</div>
      <div className="small muted">IC 95%: {fmtLift(k.ci_low)} / {fmtLift(k.ci_high)}</div>
      <div className="row small" style={{ marginTop: 6 }}>
        {k.significant ? (
          <span className={`badge ${k.rel_lift >= 0 ? 'green' : 'red'}`}>{k.rel_lift >= 0 ? '✓ ' : '! '}Significativo</span>
        ) : (
          <span className="badge">Non significativo</span>
        )}
        <span className="muted">{fmtPEq(k.p_value)}</span>
      </div>
      <div className="kpi-compare">
        <div>
          <div className="lbl">Controllo</div>
          <div className="val">{fmtKpi(k.control, k.unit, k.id)}</div>
        </div>
        <div>
          <div className="lbl">Trattati</div>
          <div className="val">{fmtKpi(k.treatment, k.unit, k.id)}</div>
        </div>
      </div>
    </div>
  );
}

export default function Detail() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const cg = useLoad(() => api.controlGroup(id), [id]);
  const res = useLoad(() => api.results(id), [id]);
  const journey = useLoad(() => (cg.data ? api.journey(cg.data.journey_id) : Promise.resolve(null)), [cg.data?.journey_id]);
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
  const kpis = r ? [...r.kpis].sort((a, b) => Number(b.primary) - Number(a.primary)) : [];
  const primary = kpis.find((k) => k.primary);

  return (
    <div>
      <div style={{ marginBottom: '0.75rem' }}>
        <Link to="/" className="small">← Dashboard</Link>
      </div>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
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
          {r && (
            <>
              <div className={`banner ${r.status.level}`}>
                <span className="alert-icon">{r.status.level === 'ok' ? '✓' : '!'}</span>
                <span className="banner-text">{r.status.message}</span>
                <span className="spacer" />
                <span className="small muted" style={{ whiteSpace: 'nowrap' }}>
                  al {fmtDate(r.as_of)} · giorno {r.days_running} · {r.source}
                </span>
              </div>

              <div className="grid grid-4">
                {kpis.map((k) => <KpiCard key={k.id} k={k} />)}
              </div>

              <div className="grid grid-2">
                <div className="card">
                  <div className="card-title">
                    <h3>Ricavo incrementale</h3>
                    <span className="badge">stima</span>
                  </div>
                  <div className={`big-number ${r.incremental_revenue.estimate >= 0 ? 'pos' : 'neg'}`}>{fmtEur(r.incremental_revenue.estimate)}</div>
                  <div className="muted small">Intervallo: {fmtEur(r.incremental_revenue.ci_low)} – {fmtEur(r.incremental_revenue.ci_high)}</div>
                  <div className="kpi-compare">
                    <div>
                      <div className="lbl">Ricavo controllo</div>
                      <div className="val">{fmtEur(r.groups.control.revenue)}</div>
                    </div>
                    <div>
                      <div className="lbl">Ricavo trattati</div>
                      <div className="val">{fmtEur(r.groups.treatment.revenue)}</div>
                    </div>
                  </div>
                </div>
                <div className="card">
                  <div className="card-title">
                    <h3>Bilanciamento dei gruppi (SRM)</h3>
                    {r.srm.ok ? <span className="badge green">✓ OK</span> : <span className="badge red">! Sbilanciato</span>}
                  </div>
                  <dl className="dl">
                    <dt>Quota attesa</dt><dd>{fmtPct(r.srm.expected_pct)}</dd>
                    <dt>Quota osservata</dt><dd>{fmtPct(r.srm.observed_pct)}</dd>
                    <dt>p-value</dt><dd>{fmtP(r.srm.p_value)}</dd>
                  </dl>
                  <p className="small muted" style={{ marginTop: 8, marginBottom: 0 }}>
                    {r.srm.ok
                      ? "La ripartizione osservata è coerente con quella prevista: l'assegnazione funziona correttamente."
                      : "La ripartizione osservata si discosta da quella prevista: verifica l'assegnazione prima di leggere i risultati."}
                  </p>
                </div>
              </div>

              <div className="card">
                <div className="card-title">
                  <h3>Lift relativo cumulato — {primary?.name ?? KPI_LABELS[c.primary_kpi]}</h3>
                </div>
                <LiftChart data={r.timeseries} />
              </div>

              <div className="card">
                <h3>Gruppi</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Gruppo</th>
                        <th className="num">Contatti</th>
                        <th className="num">Acquirenti</th>
                        <th className="num">Ordini</th>
                        <th className="num">Ricavo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(['control', 'treatment'] as const).map((g) => (
                        <tr key={g}>
                          <td><strong>{g === 'control' ? 'Controllo (holdout)' : 'Trattati'}</strong></td>
                          <td className="num">{fmtInt(r.groups[g].contacts)}</td>
                          <td className="num">{fmtInt(r.groups[g].converters)}</td>
                          <td className="num">{fmtInt(r.groups[g].orders)}</td>
                          <td className="num">{fmtEur(r.groups[g].revenue)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
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
