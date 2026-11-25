import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, CategorySummary, OverviewRow } from '../api';
import { ForestPlot } from '../components/Comparison';
import { ErrorBox, Loading, Tabs, useLoad } from '../components/ui';
import { fmtEur, fmtInt, fmtKpi, fmtLift, fmtPct } from '../format';
import { Outcome } from './Initiative';

type Tab = 'categorie' | 'journey';

/** Monitoraggio trasversale: per categoria di control group e per singolo customer journey. */
export default function Monitoring() {
  const ov = useLoad(() => api.overview());
  const [params, setParams] = useSearchParams();
  const tab = (params.get('vista') as Tab) || 'categorie';
  const category = params.get('categoria') ?? '';
  const setTab = (t: Tab) => setParams((p) => { p.set('vista', t); return p; });
  const openCategory = (c: string) => setParams({ vista: 'journey', categoria: c });

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">Monitoraggio</div>
          <h1>Risultati dei control group</h1>
          <p>Vista d'insieme per categoria e confronto, journey per journey, tra chi era nel control group e chi ha ricevuto le comunicazioni.</p>
        </div>
      </div>
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'categorie', label: 'Per categoria' },
          { id: 'journey', label: 'Per customer journey' },
        ]}
      />
      {ov.loading && <Loading text="Calcolo dei risultati di tutti i control group…" />}
      <ErrorBox error={ov.error} onRetry={ov.reload} />
      {ov.data && ov.data.rows.length === 0 && (
        <div className="card empty">
          <h2>Nessun control group attivo</h2>
          <p>Crea un control group per iniziare a misurare l'incrementalità.</p>
          <Link to="/nuovo" className="btn primary">+ Nuovo control group</Link>
        </div>
      )}
      {ov.data && ov.data.rows.length > 0 && tab === 'categorie' && (
        <ByCategory cats={ov.data.categories} onOpen={openCategory} />
      )}
      {ov.data && ov.data.rows.length > 0 && tab === 'journey' && (
        <ByJourney rows={ov.data.rows} category={category} setCategory={(c) => setParams({ vista: 'journey', ...(c ? { categoria: c } : {}) })} />
      )}
    </div>
  );
}

function ByCategory({ cats, onOpen }: { cats: CategorySummary[]; onOpen: (c: string) => void }) {
  const tot = cats.reduce(
    (a, c) => ({ inc: a.inc + c.incremental_revenue.estimate, j: a.j + c.journeys, i: a.i + c.initiatives, pos: a.pos + c.positive }),
    { inc: 0, j: 0, i: 0, pos: 0 },
  );
  const withLift = cats.filter((c) => c.revenue_lift !== null && c.revenue_lift_ci);
  return (
    <div className="stack">
      <div className="grid grid-4">
        <Stat label="Ricavo incrementale totale" value={fmtEur(tot.inc)} accent />
        <Stat label="Iniziative" value={fmtInt(tot.i)} />
        <Stat label="Customer journey in test" value={fmtInt(tot.j)} />
        <Stat label="Journey che funzionano" value={`${fmtInt(tot.pos)} su ${fmtInt(tot.j)}`} />
      </div>
      {withLift.length > 0 && (
        <div className="card">
          <div className="card-title"><h3>Lift sul ricavo per categoria</h3></div>
          <ForestPlot
            rows={withLift.map((c) => ({
              key: c.category, label: c.category, lift: c.revenue_lift!, lo: c.revenue_lift_ci![0], hi: c.revenue_lift_ci![1],
              significant: c.revenue_lift_ci![0] > 0 || c.revenue_lift_ci![1] < 0,
            }))}
          />
          <p className="small muted" style={{ margin: '0.6rem 0 0' }}>
            Ricavo incrementale della categoria diviso il ricavo che i trattati avrebbero fatto senza comunicazioni. Ogni journey è stimato con il suo control group, poi le stime si sommano.
          </p>
        </div>
      )}
      <div className="grid grid-3">
        {cats.map((c) => {
          const n = c.positive + c.negative + c.inconclusive + c.no_data || 1;
          return (
            <div className="card cat-card" key={c.category}>
              <div className="row between">
                <h3 style={{ margin: 0 }}>{c.category}</h3>
                <span className="muted small">{c.initiatives} iniziativ{c.initiatives === 1 ? 'a' : 'e'} · {c.journeys} journey</span>
              </div>
              <div>
                <div className="lbl">Ricavo incrementale</div>
                <div className={`big-number ${c.incremental_revenue.estimate >= 0 ? 'pos' : 'neg'}`}>{fmtEur(c.incremental_revenue.estimate)}</div>
                <div className="small muted">Intervallo: {fmtEur(c.incremental_revenue.ci_low)} – {fmtEur(c.incremental_revenue.ci_high)}</div>
              </div>
              <div className="cg-meta">
                <div><span className="lbl">Lift sul ricavo</span><span className="val">{fmtLift(c.revenue_lift)}</span></div>
                <div><span className="lbl">Contatti CG / trattati</span><span className="val">{fmtInt(c.control_contacts)} / {fmtInt(c.treatment_contacts)}</span></div>
              </div>
              <div>
                <div className="outcome-bar" aria-label="Esito dei journey">
                  <span className="o-pos" style={{ width: `${(c.positive / n) * 100}%` }} />
                  <span className="o-neg" style={{ width: `${(c.negative / n) * 100}%` }} />
                  <span className="o-ns" style={{ width: `${((c.inconclusive + c.no_data) / n) * 100}%` }} />
                </div>
                <div className="small muted" style={{ marginTop: 4 }}>
                  {c.positive} funzionano · {c.negative} peggiorano · {c.inconclusive + c.no_data} in raccolta
                </div>
              </div>
              <button className="btn sm" style={{ alignSelf: 'flex-start', marginTop: 'auto' }} onClick={() => onOpen(c.category)}>
                Vedi i journey della categoria →
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`card stat${accent ? ' accent' : ''}`}>
      <div className="lbl">{label}</div>
      <div className="stat-val">{value}</div>
    </div>
  );
}

function ByJourney({ rows, category, setCategory }: { rows: OverviewRow[]; category: string; setCategory: (c: string) => void }) {
  const [q, setQ] = useState('');
  const [initiative, setInitiative] = useState('');
  const cats = useMemo(() => [...new Set(rows.map((r) => r.category))].sort(), [rows]);
  const inits = useMemo(() => {
    const m = new Map<string, string>();
    rows.filter((r) => !category || r.category === category).forEach((r) => m.set(r.initiative_id, r.initiative_name));
    return [...m.entries()];
  }, [rows, category]);
  const shown = rows.filter((r) =>
    (!category || r.category === category) &&
    (!initiative || r.initiative_id === initiative) &&
    (!q || `${r.journey_name} ${r.initiative_name}`.toLowerCase().includes(q.toLowerCase())),
  );
  return (
    <div className="stack">
      <div className="picker-bar">
        <div className="search-box">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
          <input type="text" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cerca journey o iniziativa…" aria-label="Cerca" />
        </div>
        <select value={category} onChange={(e) => { setCategory(e.target.value); setInitiative(''); }} aria-label="Categoria">
          <option value="">Tutte le categorie</option>
          {cats.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={initiative} onChange={(e) => setInitiative(e.target.value)} aria-label="Iniziativa">
          <option value="">Tutte le iniziative</option>
          {inits.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      </div>
      <div className="card">
        <div className="card-title">
          <h3>Lift del KPI primario per customer journey</h3>
          <span className="muted small">{shown.length} journey</span>
        </div>
        <ForestPlot
          rows={shown.filter((r) => r.primary).map((r) => ({
            key: r.cg_id,
            label: <Link to={`/iniziativa/${r.initiative_id}`}>{r.journey_name}</Link>,
            lift: r.primary!.rel_lift, lo: r.primary!.ci_low, hi: r.primary!.ci_high, significant: r.primary!.significant,
          }))}
        />
      </div>
      <div className="card">
        <h3>Control group vs trattati per customer journey</h3>
        <div className="table-wrap">
          <table className="compact">
            <thead>
              <tr>
                <th>Customer journey</th>
                <th>Iniziativa</th>
                <th>Categoria</th>
                <th className="num">Holdout</th>
                <th className="num">Contatti CG / trattati</th>
                <th>KPI primario</th>
                <th className="num">Control group</th>
                <th className="num">Trattati</th>
                <th className="num">Lift</th>
                <th>Esito</th>
                <th className="num">Ricavo incr.</th>
                <th className="num">Giorni</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.cg_id}>
                  <td><Link to={`/cg/${r.cg_id}`}>{r.journey_name}</Link>{r.activity_name && <div className="small muted">prima di «{r.activity_name}»</div>}</td>
                  <td><Link to={`/iniziativa/${r.initiative_id}`}>{r.initiative_name}</Link></td>
                  <td>{r.category}</td>
                  <td className="num">{fmtPct(r.holdout_pct)}</td>
                  {r.primary && r.groups ? (
                    <>
                      <td className="num">{fmtInt(r.groups.control.contacts)} / {fmtInt(r.groups.treatment.contacts)}</td>
                      <td>{r.primary.name}</td>
                      <td className="num">{fmtKpi(r.primary.control, r.primary.unit, r.primary.id)}</td>
                      <td className="num">{fmtKpi(r.primary.treatment, r.primary.unit, r.primary.id)}</td>
                      <td className={`num ${r.primary.significant ? (r.primary.rel_lift >= 0 ? 'pos' : 'neg') : ''}`}><strong>{fmtLift(r.primary.rel_lift)}</strong></td>
                      <td><Outcome sig={r.primary.significant} lift={r.primary.rel_lift} />{r.srm_ok === false && <span className="badge red" style={{ marginLeft: 4 }}>SRM</span>}</td>
                      <td className="num">{fmtEur(r.incremental_revenue?.estimate)}</td>
                      <td className="num">{r.days_running}</td>
                    </>
                  ) : (
                    <td colSpan={8} className="muted">{r.error ?? r.status?.message ?? 'Nessun dato'}</td>
                  )}
                </tr>
              ))}
              {shown.length === 0 && <tr><td colSpan={12} className="muted">Nessun journey con questi filtri.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
