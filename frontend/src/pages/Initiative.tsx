import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, InitiativeResults, KPI_LABELS, MemberResults, NarrativeResponse, Scope } from '../api';
import ResultsView from '../components/ResultsView';
import { CompareBars, ForestPlot } from '../components/Comparison';
import { AdvisorBox, ErrorBox, Loading, Modal, Spinner, StatusBadge, Thinking, useLoad } from '../components/ui';
import { fmtDate, fmtEur, fmtInt, fmtKpi, fmtLift, fmtPct, shortLabels } from '../format';

const TOTAL = '__totale__';

/** Monitoraggio di un control group/iniziativa: totale + un monitoraggio per ogni customer journey. */
export default function Initiative() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const ini = useLoad(() => api.initiative(id), [id]);
  const res = useLoad(() => api.initiativeResults(id), [id]);
  const scopes = useLoad(() => api.scopes().catch(() => [] as Scope[]));
  const [view, setView] = useState(TOTAL);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshErr, setRefreshErr] = useState<unknown>(null);
  const [narr, setNarr] = useState<{ key: string; r: NarrativeResponse } | null>(null);
  const [narrLoading, setNarrLoading] = useState(false);
  const [narrErr, setNarrErr] = useState<unknown>(null);
  const [confirmDel, setConfirmDel] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [delErr, setDelErr] = useState<unknown>(null);

  if (ini.loading) return <Loading />;
  if (ini.error || !ini.data) return (
    <div className="stack">
      <ErrorBox error={ini.error} onRetry={ini.reload} />
      <Link to="/">← Torna alla dashboard</Link>
    </div>
  );
  const i = ini.data;
  const r: InitiativeResults | null = res.data;
  const multi = i.journeys.length > 1;
  const member = r?.members.find((m) => m.cg_id === view) ?? null;
  const current = view === TOTAL ? r?.total ?? null : member?.results ?? null;
  const scopeName = scopes.data?.find((s) => s.id === i.scope_id)?.name ?? i.scope_id;

  const refresh = async () => {
    setRefreshing(true);
    setRefreshErr(null);
    try {
      res.setData(await api.initiativeRefresh(id));
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
      const out = view === TOTAL ? await api.initiativeNarrative(id) : await api.narrative(view);
      setNarr({ key: view, r: out });
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
      await api.deleteInitiative(id);
      navigate('/');
    } catch (e) {
      setDelErr(e);
      setDeleting(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: '0.75rem' }}>
        <Link to="/" className="small">← Dashboard</Link>
      </div>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <div className="eyebrow">{i.category} · {multi ? `iniziativa su ${i.journeys.length} customer journey` : 'control group'}</div>
          <div className="row" style={{ marginBottom: 4 }}>
            <h1 style={{ margin: 0 }}>{i.name}</h1>
            <StatusBadge status={i.status} />
          </div>
          <p>
            {scopeName} · <strong>{fmtPct(i.holdout_pct)}</strong> nel control group · KPI primario {KPI_LABELS[i.primary_kpi] ?? i.primary_kpi} · creato il {fmtDate(i.created_at)}
          </p>
        </div>
        <div className="row">
          <button className="btn" onClick={refresh} disabled={refreshing}>{refreshing ? <Spinner /> : '↻'} Aggiorna dati</button>
          <button className="btn" onClick={loadNarr} disabled={narrLoading || !current?.kpis.length}>
            {narrLoading && <Spinner />} Commento advisor
          </button>
          <button className="btn danger" onClick={() => setConfirmDel(true)}>Elimina</button>
        </div>
      </div>

      {multi && (
        <div className="segmented" role="tablist" aria-label="Vista del monitoraggio">
          <button role="tab" aria-selected={view === TOTAL} className={view === TOTAL ? 'active' : ''} onClick={() => setView(TOTAL)}>
            Totale iniziativa
          </button>
          {i.journeys.map((j, k) => (
            <button key={j.cg_id} role="tab" title={j.journey_name} aria-selected={view === j.cg_id} className={view === j.cg_id ? 'active' : ''} onClick={() => setView(j.cg_id)}>
              {shortLabels(i.journeys.map((x) => x.journey_name))[k]}
            </button>
          ))}
        </div>
      )}

      <div className="stack">
        {!!refreshErr && <ErrorBox error={refreshErr} />}
        {narrLoading && <Thinking />}
        {!!narrErr && <ErrorBox error={narrErr} />}
        {narr && narr.key === view && !narrLoading && (
          <AdvisorBox title={`Commento dell'advisor — ${view === TOTAL ? (multi ? 'totale iniziativa' : i.name) : member?.journey_name}`} source={narr.r.source}>
            {narr.r.narrative}
          </AdvisorBox>
        )}
        {res.loading && !r && <Loading text="Caricamento risultati…" />}
        <ErrorBox error={res.error} onRetry={res.reload} />

        {r && view === TOTAL && multi && <JourneyComparison r={r} primaryKpi={i.primary_kpi} />}

        {member && (
          <div className="row small">
            <span className="muted">Journey:</span> <strong>{member.journey_name}</strong>
            {member.activity_name && <span className="muted">· holdout prima di «{member.activity_name}»</span>}
            <span className="spacer" />
            <Link to={`/cg/${member.cg_id}`}>Artefatti SFMC e configurazione di questo journey →</Link>
          </div>
        )}
        {member?.error && <ErrorBox error={member.error} />}
        {current && <ResultsView r={current} primaryLabel={KPI_LABELS[i.primary_kpi]} />}
        {r && view === TOTAL && !multi && (
          <p className="small"><Link to={`/cg/${i.journeys[0].cg_id}`}>Artefatti SFMC e configurazione →</Link></p>
        )}
      </div>

      {confirmDel && (
        <Modal onClose={() => !deleting && setConfirmDel(false)}>
          <h2>Eliminare {multi ? "l'iniziativa" : 'il control group'}?</h2>
          <p className="muted">
            «{i.name}» verrà rimosso dall'applicazione{multi ? ` con i suoi ${i.journeys.length} holdout` : ''}. Gli artefatti già creati in Marketing Cloud non vengono cancellati automaticamente.
          </p>
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

/** Confronto control group vs trattati, journey per journey, più il totale dell'iniziativa. */
function JourneyComparison({ r, primaryKpi }: { r: InitiativeResults; primaryKpi: string }) {
  const ok = r.members.filter((m): m is MemberResults & { results: NonNullable<MemberResults['results']> } => !!m.results?.kpis.length);
  const prim = (res: NonNullable<MemberResults['results']>) => res.kpis.find((k) => k.primary) ?? res.kpis[0];
  const total = r.total && r.total.kpis.length ? r.total : null;
  const tp = total ? prim(total) : null;
  const unit = tp?.unit ?? (ok[0] ? prim(ok[0].results).unit : '€');
  const fmt = (v: number) => fmtKpi(v, unit, primaryKpi);
  const label = KPI_LABELS[primaryKpi] ?? primaryKpi;
  const shortAll = shortLabels(r.members.map((m) => m.journey_name));
  const short = (m: MemberResults) => <span title={m.journey_name}>{shortAll[r.members.indexOf(m)]}</span>;

  return (
    <>
      <div className="grid grid-2">
        <div className="card">
          <div className="card-title"><h3>Lift per customer journey — {label}</h3></div>
          <ForestPlot
            rows={[
              ...ok.map((m) => {
                const k = prim(m.results);
                return { key: m.cg_id, label: short(m), lift: k.rel_lift, lo: k.ci_low, hi: k.ci_high, significant: k.significant };
              }),
              ...(tp ? [{ key: 'tot', label: <strong>Totale iniziativa</strong>, lift: tp.rel_lift, lo: tp.ci_low, hi: tp.ci_high, significant: tp.significant, total: true }] : []),
            ]}
          />
        </div>
        <div className="card">
          <div className="card-title"><h3>Control group vs trattati — {label}</h3></div>
          <CompareBars
            fmt={fmt}
            rows={[
              ...ok.map((m) => {
                const k = prim(m.results);
                return { key: m.cg_id, label: short(m), control: k.control, treatment: k.treatment };
              }),
              ...(tp ? [{ key: 'tot', label: <strong>Totale</strong>, control: tp.control, treatment: tp.treatment, total: true }] : []),
            ]}
          />
        </div>
      </div>
      <div className="card">
        <h3>Confronto per customer journey</h3>
        <div className="table-wrap">
          <table className="compact">
            <thead>
              <tr>
                <th>Customer journey</th>
                <th className="num">Control group</th>
                <th className="num">Trattati</th>
                <th className="num">{label} CG</th>
                <th className="num">{label} trattati</th>
                <th className="num">Lift</th>
                <th>Esito</th>
                <th className="num">Ricavo incrementale</th>
                <th>SRM</th>
              </tr>
            </thead>
            <tbody>
              {r.members.map((m) => {
                const res = m.results;
                const k = res?.kpis.length ? prim(res) : null;
                return (
                  <tr key={m.cg_id}>
                    <td><Link to={`/cg/${m.cg_id}`}>{m.journey_name}</Link></td>
                    {k && res ? (
                      <>
                        <td className="num">{fmtInt(res.groups.control.contacts)}</td>
                        <td className="num">{fmtInt(res.groups.treatment.contacts)}</td>
                        <td className="num">{fmt(k.control)}</td>
                        <td className="num">{fmt(k.treatment)}</td>
                        <td className={`num ${k.significant ? (k.rel_lift >= 0 ? 'pos' : 'neg') : ''}`}><strong>{fmtLift(k.rel_lift)}</strong></td>
                        <td><Outcome sig={k.significant} lift={k.rel_lift} /></td>
                        <td className="num">{fmtEur(res.incremental_revenue.estimate)}</td>
                        <td>{res.srm.ok ? <span className="badge green">OK</span> : <span className="badge red">Sbilanciato</span>}</td>
                      </>
                    ) : (
                      <td colSpan={8} className="muted">{m.error ?? res?.status.message ?? 'Nessun dato'}</td>
                    )}
                  </tr>
                );
              })}
              {total && tp && (
                <tr className="total-row">
                  <td><strong>Totale iniziativa</strong></td>
                  <td className="num">{fmtInt(total.groups.control.contacts)}</td>
                  <td className="num">{fmtInt(total.groups.treatment.contacts)}</td>
                  <td className="num">{fmt(tp.control)}</td>
                  <td className="num">{fmt(tp.treatment)}</td>
                  <td className={`num ${tp.significant ? (tp.rel_lift >= 0 ? 'pos' : 'neg') : ''}`}><strong>{fmtLift(tp.rel_lift)}</strong></td>
                  <td><Outcome sig={tp.significant} lift={tp.rel_lift} /></td>
                  <td className="num"><strong>{fmtEur(total.incremental_revenue.estimate)}</strong></td>
                  <td>{total.srm.ok ? <span className="badge green">OK</span> : <span className="badge red">Sbilanciato</span>}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="small muted" style={{ margin: '0.6rem 0 0' }}>
          Il totale somma contatti, ordini e ricavi dei journey (stessa % di holdout): ha più campione di ogni singolo journey, quindi diventa significativo prima.
        </p>
      </div>
      <h2 style={{ marginTop: '0.5rem' }}>Totale iniziativa</h2>
    </>
  );
}

export function Outcome({ sig, lift }: { sig: boolean; lift: number }) {
  if (!sig) return <span className="badge">In raccolta</span>;
  return lift >= 0 ? <span className="badge green">Funziona</span> : <span className="badge red">Peggiora</span>;
}
