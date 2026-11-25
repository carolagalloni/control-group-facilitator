import { ReactNode } from 'react';
import { fmtLift } from '../format';

export interface ForestRow {
  key: string;
  label: ReactNode;
  lift: number;
  lo: number;
  hi: number;
  significant: boolean;
  total?: boolean;
}

/** Lift con intervallo di confidenza, una riga per journey (e il totale): si legge a colpo d'occhio
 *  quali journey funzionano, quali no e quali sono ancora incerti. */
export function ForestPlot({ rows, caption }: { rows: ForestRow[]; caption?: string }) {
  if (!rows.length) return null;
  let lo = Math.min(0, ...rows.map((r) => r.lo));
  let hi = Math.max(0, ...rows.map((r) => r.hi));
  lo = Math.max(lo, -1);
  hi = Math.min(hi, 1.5);
  const pad = (hi - lo) * 0.08 || 0.05;
  lo -= pad;
  hi += pad;
  const x = (v: number) => `${((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="forest">
      {rows.map((r) => {
        const cls = r.significant ? (r.lift >= 0 ? 'pos' : 'neg') : 'ns';
        return (
          <div key={r.key} className={`forest-row${r.total ? ' total' : ''}`}>
            <div className="forest-label">{r.label}</div>
            <div className="forest-track" aria-label={`Lift ${fmtLift(r.lift)}, IC ${fmtLift(r.lo)} / ${fmtLift(r.hi)}`}>
              <span className="forest-zero" style={{ left: x(0) }} />
              <span className={`forest-ci ${cls}`} style={{ left: x(r.lo), width: `calc(${x(r.hi)} - ${x(r.lo)})` }} />
              <span className={`forest-dot ${cls}${r.total ? ' diamond' : ''}`} style={{ left: x(r.lift) }} />
            </div>
            <div className={`forest-val ${cls === 'ns' ? '' : cls}`}>
              <strong>{fmtLift(r.lift)}</strong>
              <span className="muted small"> [{fmtLift(r.lo)}; {fmtLift(r.hi)}]</span>
            </div>
          </div>
        );
      })}
      <div className="forest-legend small muted">
        <span><i className="dot-l pos" /> migliore del control group (significativo)</span>
        <span><i className="dot-l neg" /> peggiore (significativo)</span>
        <span><i className="dot-l ns" /> non ancora significativo</span>
        {caption && <span>{caption}</span>}
      </div>
    </div>
  );
}

export interface BarRow {
  key: string;
  label: ReactNode;
  control: number;
  treatment: number;
  total?: boolean;
}

/** Valore del KPI per chi era nel control group (grigio) e chi ha ricevuto le comunicazioni (rosso). */
export function CompareBars({ rows, fmt }: { rows: BarRow[]; fmt: (v: number) => string }) {
  if (!rows.length) return null;
  const max = Math.max(...rows.flatMap((r) => [r.control, r.treatment]), 1e-9);
  return (
    <div className="bars">
      {rows.map((r) => (
        <div key={r.key} className={`bars-row${r.total ? ' total' : ''}`}>
          <div className="bars-label">{r.label}</div>
          <div className="bars-pair">
            <div className="bar-line">
              <span className="bar control" style={{ width: `${(r.control / max) * 100}%` }} />
              <span className="bar-val">{fmt(r.control)}</span>
            </div>
            <div className="bar-line">
              <span className="bar treated" style={{ width: `${(r.treatment / max) * 100}%` }} />
              <span className="bar-val">{fmt(r.treatment)}</span>
            </div>
          </div>
        </div>
      ))}
      <div className="forest-legend small muted">
        <span><i className="sw control" /> Control group: non ha ricevuto le comunicazioni</span>
        <span><i className="sw treated" /> Trattati: hanno ricevuto le comunicazioni</span>
      </div>
    </div>
  );
}
