import { Link } from 'react-router-dom';
import { api, KPI_LABELS, Scope } from '../api';
import { ErrorBox, Loading, StatusBadge, useLoad } from '../components/ui';
import { fmtDate, fmtPct } from '../format';

export default function Dashboard() {
  const cgs = useLoad(() => api.controlGroups());
  const scopes = useLoad(() => api.scopes().catch(() => [] as Scope[]));
  const scopeName = (id: string) => scopes.data?.find((s) => s.id === id)?.name ?? id;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Control group</h1>
          <p>Gruppi di controllo attivi nei journey di Marketing Cloud e relativo monitoraggio dell'incrementalità.</p>
        </div>
        <Link to="/nuovo" className="btn primary">+ Nuovo control group</Link>
      </div>
      {cgs.loading && <Loading />}
      <ErrorBox error={cgs.error} onRetry={cgs.reload} />
      {cgs.data && cgs.data.length === 0 && (
        <div className="card empty">
          <svg width="88" height="64" viewBox="0 0 88 64" aria-hidden>
            <circle cx="32" cy="32" r="22" fill="none" stroke="var(--border)" strokeWidth="4" />
            <circle cx="56" cy="32" r="22" fill="var(--primary-soft)" stroke="var(--primary)" strokeWidth="3" />
          </svg>
          <h2>Nessun control group ancora</h2>
          <p>Crea il primo gruppo di controllo: l'advisor ti aiuterà a scegliere l'obiettivo, la posizione nel journey e la dimensione corretta dell'holdout.</p>
          <Link to="/nuovo" className="btn primary lg">Crea il primo control group</Link>
        </div>
      )}
      {cgs.data && cgs.data.length > 0 && (
        <div className="grid grid-3">
          {cgs.data.map((cg) => (
            <div className="card cg-card" key={cg.id}>
              <div className="row between" style={{ alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                  <h3 style={{ marginBottom: 2 }}>{cg.name}</h3>
                  <div className="muted small">{cg.journey_name}{cg.activity_name ? ` · prima di "${cg.activity_name}"` : ''}</div>
                </div>
                <StatusBadge status={cg.status} />
              </div>
              <div className="cg-meta">
                <div>
                  <span className="lbl">Holdout</span>
                  <span className="cg-holdout">{fmtPct(cg.holdout_pct)}</span>
                </div>
                <div>
                  <span className="lbl">Obiettivo</span>
                  <span className="val">{scopeName(cg.scope_id)}</span>
                </div>
                <div>
                  <span className="lbl">KPI primario</span>
                  <span className="val">{KPI_LABELS[cg.primary_kpi] ?? cg.primary_kpi}</span>
                </div>
                <div>
                  <span className="lbl">Creato il</span>
                  <span className="val">{fmtDate(cg.created_at)}</span>
                </div>
              </div>
              <div className="row" style={{ marginTop: 'auto' }}>
                <Link to={`/cg/${cg.id}`} className="btn primary sm">Apri monitoraggio →</Link>
                <span className="spacer" />
                <span className="muted small mono">{cg.id}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
