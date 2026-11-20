import { useState } from 'react';
import type { SizingOption, TimePoint } from '../api';
import { fmtDate, fmtInt, fmtLift, fmtP, fmtPct } from '../format';
import { useWidth } from './useWidth';

function niceTicks(min: number, max: number, count = 5) {
  const span = max - min || 1;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

const pctTick = (v: number) => new Intl.NumberFormat('it-IT', { style: 'percent', maximumFractionDigits: 1 }).format(v);

function Tooltip({ x, y, w, children }: { x: number; y: number; w: number; children: React.ReactNode }) {
  const left = x > w - 190 ? x - 180 : x + 12;
  return (
    <div
      style={{
        position: 'absolute', left, top: Math.max(0, y - 10), pointerEvents: 'none', background: 'var(--surface)',
        border: '1px solid var(--border)', borderRadius: 6, padding: '6px 9px', fontSize: 12, boxShadow: 'var(--shadow-lg)', minWidth: 160, zIndex: 5,
      }}
    >
      {children}
    </div>
  );
}

export function MdeChart({ options, expectedLift, selectedPct, recommendedPct, onSelect }: {
  options: SizingOption[];
  expectedLift: number;
  selectedPct: number | null;
  recommendedPct: number | null;
  onSelect?: (pct: number) => void;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const H = 260;
  const m = { l: 52, r: 16, t: 16, b: 40 };
  const pts = [...options].sort((a, b) => a.holdout_pct - b.holdout_pct);
  if (!pts.length) return null;
  const xMin = pts[0].holdout_pct, xMax = pts[pts.length - 1].holdout_pct;
  const yMaxRaw = Math.min(1, Math.max(expectedLift * 1.4, ...pts.map((p) => p.mde_relative)));
  const yTicks = niceTicks(0, yMaxRaw, 5);
  const yMax = yTicks[yTicks.length - 1];
  const sx = (v: number) => m.l + ((v - xMin) / (xMax - xMin || 1)) * (W - m.l - m.r);
  const sy = (v: number) => m.t + (1 - Math.min(v, yMax) / yMax) * (H - m.t - m.b);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p.holdout_pct)},${sy(p.mde_relative)}`).join(' ');
  const hp = hover !== null ? pts[hover] : null;

  return (
    <div className="chart" ref={ref} style={{ position: 'relative' }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="MDE rilevabile in funzione della percentuale di holdout">
        {/* zona rilevabile */}
        <rect x={m.l} y={sy(expectedLift)} width={W - m.l - m.r} height={H - m.b - sy(expectedLift)} fill="var(--green-soft)" opacity={0.55} />
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={W - m.r} y1={sy(t)} y2={sy(t)} stroke="var(--border)" strokeWidth={1} />
            <text x={m.l - 8} y={sy(t) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{pctTick(t)}</text>
          </g>
        ))}
        {pts.map((p) => (
          <text key={p.holdout_pct} x={sx(p.holdout_pct)} y={H - m.b + 17} textAnchor="middle" fontSize={11} fill="var(--muted)">{pctTick(p.holdout_pct)}</text>
        ))}
        <text x={(m.l + W - m.r) / 2} y={H - 4} textAnchor="middle" fontSize={11} fill="var(--muted)">% holdout (gruppo di controllo)</text>
        <text x={12} y={(m.t + H - m.b) / 2} textAnchor="middle" fontSize={11} fill="var(--muted)" transform={`rotate(-90 12 ${(m.t + H - m.b) / 2})`}>MDE relativo</text>
        <line x1={m.l} x2={W - m.r} y1={sy(expectedLift)} y2={sy(expectedLift)} stroke="var(--green)" strokeWidth={2} strokeDasharray="6 4" />
        <text x={m.l + 6} y={sy(expectedLift) + 15} textAnchor="start" fontSize={11} fontWeight={600} fill="var(--text)">Lift atteso {fmtLift(expectedLift)}</text>
        <path d={line} fill="none" stroke="var(--primary)" strokeWidth={2} strokeLinejoin="round" />
        {pts.map((p, i) => {
          const sel = selectedPct !== null && Math.abs(p.holdout_pct - selectedPct) < 1e-9;
          const rec = recommendedPct !== null && Math.abs(p.holdout_pct - recommendedPct) < 1e-9;
          const cx = sx(p.holdout_pct), cy = sy(p.mde_relative);
          return (
            <g key={p.holdout_pct} style={{ cursor: onSelect ? 'pointer' : 'default' }} onClick={() => onSelect?.(p.holdout_pct)} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <circle cx={cx} cy={cy} r={14} fill="transparent" />
              {sel && <circle cx={cx} cy={cy} r={9} fill="var(--primary)" opacity={0.2} />}
              <circle cx={cx} cy={cy} r={sel ? 5.5 : 4.5} fill={p.detectable ? 'var(--primary)' : 'var(--surface)'} stroke={p.mde_relative > yMax ? 'var(--red)' : 'var(--primary)'} strokeWidth={2} />
              {rec && <text x={cx} y={cy + 20} textAnchor="middle" fontSize={10.5} fontWeight={700} fill="var(--text)">consigliato</text>}
            </g>
          );
        })}
      </svg>
      {hp && (
        <Tooltip x={sx(hp.holdout_pct)} y={sy(hp.mde_relative)} w={W}>
          <div style={{ fontWeight: 700 }}>Holdout {fmtPct(hp.holdout_pct)}</div>
          <div>MDE: {fmtPct(hp.mde_relative)}</div>
          <div>Controllo: {fmtInt(hp.control_size)} contatti</div>
          <div>{hp.detectable ? 'Lift atteso rilevabile' : 'Lift atteso non rilevabile'}</div>
        </Tooltip>
      )}
      <div className="chart-legend">
        <span><i style={{ background: 'var(--primary)' }} /> MDE (effetto minimo rilevabile)</span>
        <span><i style={{ background: 'var(--green)' }} /> Lift atteso — sotto la linea è rilevabile</span>
        <span>
          <svg width="12" height="12" aria-hidden><circle cx="6" cy="6" r="4" fill="var(--surface)" stroke="var(--primary)" strokeWidth="2" /></svg>
          non rilevabile
        </span>
      </div>
    </div>
  );
}

export function LiftChart({ data }: { data: TimePoint[] }) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const H = 280;
  const m = { l: 52, r: 16, t: 16, b: 38 };
  if (!data.length) return <p className="muted">Nessun dato temporale disponibile.</p>;
  const pts = [...data].sort((a, b) => a.day - b.day);
  // escludiamo i primissimi giorni estremi dall'autoscala per leggibilità
  const skip = Math.min(Math.max(5, Math.floor(pts.length * 0.12)), Math.floor(pts.length / 2));
  const tail = pts.slice(skip);
  let lo = Math.min(0, ...tail.map((p) => p.ci_low));
  let hi = Math.max(0, ...tail.map((p) => p.ci_high));
  lo = Math.max(lo, -0.8);
  hi = Math.min(hi, 1);
  const yTicks = niceTicks(lo, hi, 6);
  const yMin = Math.min(yTicks[0], lo), yMax = Math.max(yTicks[yTicks.length - 1], hi);
  const xMin = pts[0].day, xMax = pts[pts.length - 1].day;
  const clamp = (v: number) => Math.max(yMin - (yMax - yMin) * 0.2, Math.min(yMax + (yMax - yMin) * 0.2, v));
  const sx = (v: number) => m.l + ((v - xMin) / (xMax - xMin || 1)) * (W - m.l - m.r);
  const sy = (v: number) => m.t + (1 - (clamp(v) - yMin) / (yMax - yMin || 1)) * (H - m.t - m.b);
  const band =
    pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p.day)},${sy(p.ci_high)}`).join(' ') +
    ' ' + [...pts].reverse().map((p) => `L${sx(p.day)},${sy(p.ci_low)}`).join(' ') + ' Z';
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p.day)},${sy(p.rel_lift)}`).join(' ');
  const xTicks = niceTicks(xMin, xMax, Math.max(3, Math.min(8, Math.floor(W / 90)))).filter((t) => t >= xMin && t <= xMax);
  const hp = hover !== null ? pts[hover] : null;

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const r = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const x = e.clientX - r.left;
    const day = xMin + ((x - m.l) / (W - m.l - m.r)) * (xMax - xMin);
    let best = 0;
    pts.forEach((p, i) => { if (Math.abs(p.day - day) < Math.abs(pts[best].day - day)) best = i; });
    setHover(best);
  };

  return (
    <div className="chart" ref={ref} style={{ position: 'relative' }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Lift relativo cumulato nel tempo con intervallo di confidenza">
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={W - m.r} y1={sy(t)} y2={sy(t)} stroke="var(--border)" strokeWidth={1} />
            <text x={m.l - 8} y={sy(t) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{pctTick(t)}</text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text key={t} x={sx(t)} y={H - m.b + 17} textAnchor="middle" fontSize={11} fill="var(--muted)">{t}</text>
        ))}
        <text x={(m.l + W - m.r) / 2} y={H - 3} textAnchor="middle" fontSize={11} fill="var(--muted)">Giorno di test</text>
        <defs>
          <clipPath id="lift-clip"><rect x={m.l} y={m.t} width={W - m.l - m.r} height={H - m.t - m.b} /></clipPath>
        </defs>
        <g clipPath="url(#lift-clip)">
          <path d={band} fill="var(--primary)" opacity={0.16} />
        <line x1={m.l} x2={W - m.r} y1={sy(0)} y2={sy(0)} stroke="var(--text)" strokeOpacity={0.55} strokeWidth={1.3} />
          <path d={line} fill="none" stroke="var(--primary)" strokeWidth={2} strokeLinejoin="round" />
        </g>
        {hp && (
          <g>
            <line x1={sx(hp.day)} x2={sx(hp.day)} y1={m.t} y2={H - m.b} stroke="var(--muted)" strokeDasharray="3 3" />
            <circle cx={sx(hp.day)} cy={sy(hp.rel_lift)} r={4.5} fill="var(--primary)" stroke="var(--surface)" strokeWidth={2} />
          </g>
        )}
        <rect x={m.l} y={m.t} width={W - m.l - m.r} height={H - m.t - m.b} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
      </svg>
      {hp && (
        <Tooltip x={sx(hp.day)} y={sy(hp.rel_lift)} w={W}>
          <div style={{ fontWeight: 700 }}>Giorno {hp.day} · {fmtDate(hp.date)}</div>
          <div>Lift cumulato: {fmtLift(hp.rel_lift)}</div>
          <div>IC 95%: {fmtLift(hp.ci_low)} / {fmtLift(hp.ci_high)}</div>
          <div>p-value: {fmtP(hp.p_value)}</div>
          <div className="muted">Controllo {fmtInt(hp.control_contacts)} · Trattati {fmtInt(hp.treatment_contacts)}</div>
        </Tooltip>
      )}
      <div className="chart-legend">
        <span><i style={{ background: 'var(--primary)' }} /> Lift relativo cumulato (KPI primario)</span>
        <span><i style={{ background: 'var(--primary)', opacity: 0.25, height: 10 }} /> Intervallo di confidenza 95%</span>
        <span><i style={{ background: 'var(--text)', opacity: 0.55 }} /> Nessun effetto (0%)</span>
      </div>
    </div>
  );
}
