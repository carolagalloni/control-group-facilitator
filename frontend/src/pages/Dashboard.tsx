import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, KPI_LABELS, Scope } from '../api';
import { ErrorBox, Loading, StatusBadge, useLoad } from '../components/ui';
import { fmtDate, fmtPct } from '../format';

export default function Dashboard() {
  const inis = useLoad(() => api.initiatives());
  const scopes = useLoad(() => api.scopes().catch(() => [] as Scope[]));
  const [cat, setCat] = useState('');
  const scopeName = (id: string) => scopes.data?.find((s) => s.id === id)?.name ?? id;
  const cats = useMemo(() => {
    const m = new Map<string, number>();
    inis.data?.forEach((i) => m.set(i.category, (m.get(i.category) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [inis.data]);
  const shown = (inis.data ?? []).filter((i) => !cat || i.category === cat);

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">Control group</div>
          <h1>Iniziative in test</h1>
          <p>Ogni control group può coprire uno o più customer journey: apri un'iniziativa per vedere il totale e il dettaglio journey per journey.</p>
        </div>
        <div className="row">
          <Link to="/monitoraggio" className="btn">Monitoraggio per categoria</Link>
          <Link to="/nuovo" className="btn primary">+ Nuovo control group</Link>
        </div>
      </div>
      {inis.loading && <Loading />}
      <ErrorBox error={inis.error} onRetry={inis.reload} />
      {inis.data && inis.data.length === 0 && (
        <div className="card empty">
          <h2>Nessun control group ancora</h2>
          <p>Crea il primo gruppo di controllo: l'advisor ti aiuterà a scegliere l'obiettivo, la posizione nel journey e la dimensione corretta dell'holdout.</p>
          <Link to="/nuovo" className="btn primary lg">Crea il primo control group</Link>
        </div>
      )}
      {cats.length > 1 && (
        <div className="filter-chips" role="group" aria-label="Filtra per categoria">
          <button className={!cat ? 'active' : ''} onClick={() => setCat('')}>Tutte ({inis.data?.length})</button>
          {cats.map(([c, n]) => (
            <button key={c} className={cat === c ? 'active' : ''} onClick={() => setCat(c)}>{c} ({n})</button>
          ))}
        </div>
      )}
      {shown.length > 0 && (
        <div className="grid grid-3">
          {shown.map((i) => (
            <div className="card cg-card" key={i.id}>
              <div className="row between" style={{ alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                  <div className="eyebrow small-eyebrow">{i.category}</div>
                  <h3 style={{ marginBottom: 2 }}>{i.name}</h3>
                </div>
                <StatusBadge status={i.status} />
              </div>
              <ul className="journey-list">
                {i.journeys.slice(0, 4).map((j) => (
                  <li key={j.cg_id}>
                    <span className="jl-dot" />
                    <span className="jl-name">{j.journey_name}</span>
                    {j.activity_name && <span className="muted small"> · prima di «{j.activity_name}»</span>}
                  </li>
                ))}
                {i.journeys.length > 4 && <li className="muted small">+ altri {i.journeys.length - 4} journey</li>}
              </ul>
              <div className="cg-meta">
                <div>
                  <span className="lbl">Holdout</span>
                  <span className="cg-holdout">{fmtPct(i.holdout_pct)}</span>
                </div>
                <div>
                  <span className="lbl">Customer journey</span>
                  <span className="cg-holdout">{i.journeys.length}</span>
                </div>
                <div>
                  <span className="lbl">Obiettivo</span>
                  <span className="val">{scopeName(i.scope_id)}</span>
                </div>
                <div>
                  <span className="lbl">KPI primario</span>
                  <span className="val">{KPI_LABELS[i.primary_kpi] ?? i.primary_kpi}</span>
                </div>
              </div>
              <div className="row" style={{ marginTop: 'auto' }}>
                <Link to={`/iniziativa/${i.id}`} className="btn primary sm">Apri monitoraggio →</Link>
                <span className="spacer" />
                <span className="muted small">dal {fmtDate(i.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
