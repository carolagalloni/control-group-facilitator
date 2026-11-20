const nf0 = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const eur0 = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });
const eur2 = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct1 = new Intl.NumberFormat('it-IT', { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });
const pct1s = new Intl.NumberFormat('it-IT', { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1, signDisplay: 'exceptZero' });

const ok = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v);

export const fmtInt = (v: number | null | undefined) => (ok(v) ? nf0.format(v) : '—');
export const fmtNum2 = (v: number | null | undefined) => (ok(v) ? nf2.format(v) : '—');
export const fmtEur = (v: number | null | undefined) => (ok(v) ? eur0.format(v) : '—');
export const fmtEur2 = (v: number | null | undefined) => (ok(v) ? eur2.format(v) : '—');
export const fmtPct = (v: number | null | undefined) => (ok(v) ? pct1.format(v) : '—');
export const fmtLift = (v: number | null | undefined) => (ok(v) ? pct1s.format(v) : '—');
/** p-value con operatore: "p = 0,032" / "p < 0,001" */
export const fmtPEq = (v: number | null | undefined) => (ok(v) && v < 0.001 ? 'p < 0,001' : `p = ${fmtP(v)}`);
export const fmtP = (v: number | null | undefined) => {
  if (!ok(v)) return '—';
  if (v < 0.001) return '< 0,001';
  return new Intl.NumberFormat('it-IT', { maximumFractionDigits: 3, minimumFractionDigits: 3 }).format(v);
};
export const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' });
};

/** Valore KPI con unità */
export function fmtKpi(v: number, unit: string, id?: string) {
  if (unit === '€') return fmtEur2(v);
  if (unit === '%' || id === 'conversion_rate') return new Intl.NumberFormat('it-IT', { style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);
  const digits = Math.abs(v) < 1 ? 3 : 2;
  const n = new Intl.NumberFormat('it-IT', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
  return n + (unit && !['#', 'n', 'num'].includes(unit) ? ` ${unit}` : '');
}
