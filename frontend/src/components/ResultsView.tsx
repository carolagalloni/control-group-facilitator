import { KPI_LABELS, KpiResult, Results } from '../api';
import { fmtDate, fmtEur, fmtInt, fmtKpi, fmtLift, fmtP, fmtPEq, fmtPct } from '../format';
import { LiftChart } from './Charts';

export function KpiCard({ k }: { k: KpiResult }) {
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
          <div className="lbl"><i className="sw control" /> Controllo</div>
          <div className="val">{fmtKpi(k.control, k.unit, k.id)}</div>
        </div>
        <div>
          <div className="lbl"><i className="sw treated" /> Trattati</div>
          <div className="val">{fmtKpi(k.treatment, k.unit, k.id)}</div>
        </div>
      </div>
    </div>
  );
}

/** Blocco risultati di un control group (singolo journey o totale di un'iniziativa). */
export default function ResultsView({ r, primaryLabel }: { r: Results; primaryLabel?: string }) {
  const kpis = [...r.kpis].sort((a, b) => Number(b.primary) - Number(a.primary));
  const primary = kpis.find((k) => k.primary);
  return (
    <>
      <div className={`banner ${r.status.level}`}>
        <span className="alert-icon">{r.status.level === 'ok' ? '✓' : '!'}</span>
        <span className="banner-text">{r.status.message}</span>
        <span className="small muted banner-meta">al {fmtDate(r.as_of)} · giorno {r.days_running} · {r.source}</span>
      </div>
      {kpis.length > 0 && (
        <>
          <div className="grid grid-4">{kpis.map((k) => <KpiCard key={k.id} k={k} />)}</div>
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
                  <div className="lbl"><i className="sw control" /> Ricavo controllo</div>
                  <div className="val">{fmtEur(r.groups.control.revenue)}</div>
                </div>
                <div>
                  <div className="lbl"><i className="sw treated" /> Ricavo trattati</div>
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
              <h3>Lift relativo cumulato — {primary?.name ?? primaryLabel}</h3>
            </div>
            <LiftChart data={r.timeseries} />
          </div>
          <div className="card">
            <h3>Chi era nel control group vs chi ha ricevuto le comunicazioni</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Gruppo</th>
                    <th className="num">Contatti</th>
                    <th className="num">Acquirenti</th>
                    <th className="num">Conversione</th>
                    <th className="num">Ordini</th>
                    <th className="num">Ricavo</th>
                    <th className="num">Ricavo / contatto</th>
                  </tr>
                </thead>
                <tbody>
                  {(['control', 'treatment'] as const).map((g) => {
                    const s = r.groups[g];
                    return (
                      <tr key={g}>
                        <td><i className={`sw ${g === 'control' ? 'control' : 'treated'}`} /> <strong>{g === 'control' ? 'Control group (non ha ricevuto)' : 'Trattati (hanno ricevuto)'}</strong></td>
                        <td className="num">{fmtInt(s.contacts)}</td>
                        <td className="num">{fmtInt(s.converters)}</td>
                        <td className="num">{fmtPct(s.contacts ? s.converters / s.contacts : null)}</td>
                        <td className="num">{fmtInt(s.orders)}</td>
                        <td className="num">{fmtEur(s.revenue)}</td>
                        <td className="num">{fmtKpi(s.contacts ? s.revenue / s.contacts : 0, '€')}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  );
}
