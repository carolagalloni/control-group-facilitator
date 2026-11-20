import { Fragment } from 'react';
import type { Activity, ActivityType, Candidate } from '../api';
import { fmtInt } from '../format';

const TYPE_META: Record<ActivityType, { color: string; soft: string; label: string }> = {
  ENTRY: { color: 'var(--green)', soft: 'var(--green-soft)', label: 'Ingresso' },
  EMAIL: { color: 'var(--primary)', soft: 'var(--primary-soft)', label: 'Email' },
  SMS: { color: 'var(--teal)', soft: 'var(--teal-soft)', label: 'SMS' },
  PUSH: { color: 'var(--violet)', soft: 'var(--violet-soft)', label: 'Push' },
  WAIT: { color: 'var(--muted)', soft: 'var(--grey-soft)', label: 'Attesa' },
  DECISION: { color: 'var(--amber)', soft: 'var(--amber-soft)', label: 'Decisione' },
  EXIT: { color: 'var(--red)', soft: 'var(--red-soft)', label: 'Uscita' },
};

export const MESSAGING: ActivityType[] = ['EMAIL', 'SMS', 'PUSH'];

function Icon({ type, x, y, color }: { type: ActivityType; x: number; y: number; color: string }) {
  const p = { fill: 'none', stroke: color, strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  const t = `translate(${x - 8},${y - 8})`;
  switch (type) {
    case 'ENTRY':
      return <path transform={t} d="M5 3l8 5-8 5z" {...p} fill={color} />;
    case 'EMAIL':
      return (
        <g transform={t} {...p}>
          <rect x="1.5" y="3.5" width="13" height="9" rx="1.5" />
          <path d="M2 4.5l6 4.5 6-4.5" />
        </g>
      );
    case 'SMS':
      return <path transform={t} d="M2.5 3.5h11a1 1 0 011 1v6a1 1 0 01-1 1H7l-3 2.5v-2.5H2.5a1 1 0 01-1-1v-6a1 1 0 011-1z" {...p} />;
    case 'PUSH':
      return (
        <g transform={t} {...p}>
          <path d="M4 11V7a4 4 0 018 0v4l1.2 1.5H2.8z" />
          <path d="M6.5 14a1.6 1.6 0 003 0" />
        </g>
      );
    case 'WAIT':
      return (
        <g transform={t} {...p}>
          <circle cx="8" cy="8" r="6" />
          <path d="M8 4.5V8l2.5 1.5" />
        </g>
      );
    case 'DECISION':
      return (
        <g transform={t} {...p}>
          <path d="M8 1.5l6.5 6.5L8 14.5 1.5 8z" />
          <path d="M8 5.5v2.5M8 10.5v.1" />
        </g>
      );
    case 'EXIT':
      return <rect transform={t} x="3.5" y="3.5" width="9" height="9" rx="1.5" {...p} fill={color} />;
    default:
      return <circle cx={x} cy={y} r={5} fill={color} />;
  }
}

const COL_W = 176;
const NODE_W = 136;
const NODE_H = 60;
const ROW_H = 96;
const PAD_X = 24;
const PAD_Y = 30;

interface Props {
  activities: Activity[];
  candidates?: Candidate[];
  selectedCandidateId?: string | null;
  onSelectCandidate?: (c: Candidate) => void;
  /** se valorizzato, le attività di messaggistica sono cliccabili */
  onPickActivity?: (a: Activity) => void;
  pickedActivityKey?: string | null;
  /** posizione fissa (dettaglio) */
  holdoutActivityKey?: string | null | undefined;
  showHoldout?: boolean;
}

export default function JourneyDiagram({ activities, candidates = [], selectedCandidateId, onSelectCandidate, onPickActivity, pickedActivityKey, holdoutActivityKey, showHoldout }: Props) {
  if (!activities.length) return <p className="muted">Nessuna attività nel journey.</p>;
  const minLane = Math.min(...activities.map((a) => a.lane));
  const maxLane = Math.max(...activities.map((a) => a.lane));
  const minStep = Math.min(...activities.map((a) => a.step));
  const maxStep = Math.max(...activities.map((a) => a.step));
  const byKey = new Map(activities.map((a) => [a.key, a]));
  const pos = (a: Activity) => ({
    x: PAD_X + (a.step - minStep) * COL_W,
    y: PAD_Y + (a.lane - minLane) * ROW_H,
  });
  const width = PAD_X * 2 + (maxStep - minStep) * COL_W + NODE_W;
  const height = PAD_Y * 2 + (maxLane - minLane) * ROW_H + NODE_H;
  const entry = activities.find((a) => a.type === 'ENTRY') ?? activities[0];

  // marker per ogni posizione candidata
  type Marker = { x: number; y: number; idx: number; cand?: Candidate; selected: boolean; recommended: boolean };
  const markers: Marker[] = [];
  const markerPoint = (key: string | null) => {
    if (key === null) {
      const p = pos(entry);
      return { x: p.x + NODE_W + (COL_W - NODE_W) / 2, y: p.y + NODE_H / 2 };
    }
    const a = byKey.get(key);
    if (!a) return null;
    const p = pos(a);
    return { x: p.x - (COL_W - NODE_W) / 2, y: p.y + NODE_H / 2 };
  };
  candidates.forEach((c, i) => {
    const pt = markerPoint(c.activity_key);
    if (!pt) return;
    const dup = markers.filter((m) => Math.abs(m.x - pt.x) < 1 && Math.abs(m.y - pt.y) < 1).length;
    markers.push({ x: pt.x, y: pt.y - dup * 24, idx: i + 1, cand: c, selected: c.id === selectedCandidateId, recommended: c.recommended });
  });
  if (showHoldout && holdoutActivityKey !== undefined) {
    const pt = markerPoint(holdoutActivityKey);
    if (pt) markers.push({ x: pt.x, y: pt.y, idx: 0, selected: true, recommended: false });
  }

  const edges: { from: Activity; to: Activity }[] = [];
  activities.forEach((a) => a.next.forEach((k) => { const t = byKey.get(k); if (t) edges.push({ from: a, to: t }); }));

  return (
    <div>
      <div className="diagram-wrap">
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', maxWidth: width, minWidth: Math.round(width * 0.78), height: 'auto' }} role="img" aria-label="Diagramma del journey">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0 0L10 5L0 10z" fill="var(--muted)" />
            </marker>
          </defs>
          {edges.map(({ from, to }, i) => {
            const a = pos(from);
            const b = pos(to);
            const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2;
            const x2 = b.x - 2, y2 = b.y + NODE_H / 2;
            let d: string;
            if (to.step > from.step) {
              const mx = x1 + Math.min(40, (x2 - x1) / 2);
              d = y1 === y2 ? `M${x1},${y1} L${x2},${y2}` : `M${x1},${y1} C${mx + 10},${y1} ${mx - 10},${y2} ${mx + 20},${y2} L${x2},${y2}`;
            } else {
              const low = Math.max(a.y, b.y) + NODE_H + 18;
              d = `M${a.x + NODE_W / 2},${a.y + NODE_H} C${a.x + NODE_W / 2},${low} ${b.x + NODE_W / 2},${low} ${b.x + NODE_W / 2},${b.y + NODE_H + 2}`;
            }
            const label = to.branch_label && from.type === 'DECISION' ? to.branch_label : null;
            return (
              <g key={i}>
                <path d={d} fill="none" stroke="var(--muted)" strokeOpacity={0.7} strokeWidth={1.5} markerEnd="url(#arrow)" />
                {label && (
                  <text x={b.x + 6} y={b.y - 7} fontSize={10.5} fill="var(--muted)" fontWeight={600}>
                    <title>{label}</title>
                    {label.length > 24 ? label.slice(0, 23) + '…' : label}
                  </text>
                )}
              </g>
            );
          })}
          {activities.map((a) => {
            const p = pos(a);
            const m = TYPE_META[a.type] ?? TYPE_META.WAIT;
            const clickable = !!onPickActivity && MESSAGING.includes(a.type);
            const picked = pickedActivityKey === a.key;
            const name = a.name.length > 15 ? a.name.slice(0, 14) + '…' : a.name;
            return (
              <g
                key={a.key}
                transform={`translate(${p.x},${p.y})`}
                style={{ cursor: clickable ? 'pointer' : 'default' }}
                onClick={clickable ? () => onPickActivity!(a) : undefined}
                tabIndex={clickable ? 0 : undefined}
                onKeyDown={clickable ? (e) => (e.key === 'Enter' || e.key === ' ') && onPickActivity!(a) : undefined}
                role={clickable ? 'button' : undefined}
                aria-label={clickable ? `Seleziona ${a.name}` : undefined}
              >
                <title>{`${a.name} (${m.label}${a.channel ? ' · ' + a.channel : ''}) — ${fmtInt(a.monthly_volume)} contatti/mese, raggiunge il ${Math.round(a.reach_rate * 100)}%`}</title>
                <rect
                  width={NODE_W}
                  height={NODE_H}
                  rx={9}
                  fill="var(--surface)"
                  stroke={picked ? 'var(--primary)' : clickable ? m.color : 'var(--border)'}
                  strokeWidth={picked ? 2.5 : clickable ? 1.5 : 1}
                  strokeDasharray={clickable && !picked ? '4 3' : undefined}
                />
                <rect x={0} y={0} width={4} height={NODE_H} rx={2} fill={m.color} />
                <circle cx={22} cy={NODE_H / 2} r={13} fill={m.soft} />
                <Icon type={a.type} x={22} y={NODE_H / 2} color={m.color} />
                <text x={42} y={25} fontSize={12.5} fontWeight={650} fill="var(--text)">
                  {name}
                </text>
                <text x={42} y={42} fontSize={11} fill="var(--muted)">
                  {a.type === 'EXIT' || a.type === 'WAIT' || a.type === 'DECISION' ? m.label : a.type === 'ENTRY' ? `${fmtInt(a.monthly_volume)}/mese` : `${m.label} · ${fmtInt(a.monthly_volume)}/m`}
                </text>
              </g>
            );
          })}
          {markers.map((mk, i) => {
            const fill = mk.selected ? 'var(--primary)' : 'var(--surface)';
            const stroke = mk.selected ? 'var(--primary)' : mk.recommended ? 'var(--green)' : 'var(--muted)';
            return (
              <g
                key={'m' + i}
                transform={`translate(${mk.x},${mk.y})`}
                style={{ cursor: mk.cand && onSelectCandidate ? 'pointer' : 'default' }}
                onClick={mk.cand && onSelectCandidate ? () => onSelectCandidate(mk.cand!) : undefined}
              >
                <title>{mk.cand ? `Posizione ${mk.idx}: ${mk.cand.label}` : 'Punto di holdout'}</title>
                {mk.selected && <circle r={17} fill="var(--primary)" opacity={0.18} />}
                <circle r={12} fill={fill} stroke={stroke} strokeWidth={2} />
                <text y={4} textAnchor="middle" fontSize={11} fontWeight={800} fill={mk.selected ? 'var(--on-primary)' : stroke}>
                  {mk.idx === 0 ? 'CG' : mk.idx}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="legend">
        {(['ENTRY', 'EMAIL', 'SMS', 'PUSH', 'WAIT', 'DECISION', 'EXIT'] as ActivityType[]).map((t) => (
          <span key={t}>
            <i style={{ background: TYPE_META[t].color }} /> {TYPE_META[t].label}
          </span>
        ))}
        {(candidates.length > 0 || showHoldout) && (
          <Fragment>
            <span>
              <svg width="16" height="16" aria-hidden>
                <circle cx="8" cy="8" r="6.5" fill="var(--primary)" />
              </svg>
              Punto di holdout {candidates.length > 0 && 'selezionato'}
            </span>
          </Fragment>
        )}
        {onPickActivity && <span className="muted">Clicca un messaggio (bordo tratteggiato) per valutarlo</span>}
      </div>
    </div>
  );
}
