import { useEffect, useRef, useState } from 'react';
import { api, Journey, JourneyPage, JourneyQuery } from '../api';
import { fmtDate, fmtInt, fmtPct } from '../format';
import ManualJourneyForm from './ManualJourneyForm';
import { ErrorBox, Spinner } from './ui';

const STATUS_LABEL: Record<string, string> = {
  Running: 'Attivo', Paused: 'In pausa', Draft: 'Bozza', Stopped: 'Fermato', Finishing: 'In chiusura',
  Published: 'Pubblicato', Unpublished: 'Non pubblicato', ScheduledToPublish: 'Programmato',
};
const CHANNELS: Record<string, string> = { email: 'Email', sms: 'SMS', push: 'Push' };
const PAGE_SIZE = 12;

export const statusLabel = (s: string) => STATUS_LABEL[s] ?? s;

/**
 * Selettore journey per cataloghi grandi: ricerca lato server, filtri, ordinamento e paginazione.
 * In modalità multipla si possono scegliere più journey (un'iniziativa); il primo selezionato è quello
 * di riferimento per advisor, posizione e dimensionamento.
 */
export default function JourneyPicker({ selected, onChange, multi, manual }: {
  selected: Journey[];
  onChange: (j: Journey[]) => void;
  multi: boolean;
  /** modalità senza API: i journey si inseriscono a mano */
  manual?: boolean;
}) {
  const [showForm, setShowForm] = useState(false);
  const [bump, setBump] = useState(0);
  const [q, setQ] = useState('');
  const [debounced, setDebounced] = useState('');
  const [filters, setFilters] = useState<JourneyQuery>({ status: 'Running', folder: '', channel: '', sort: 'name' });
  const [page, setPage] = useState(1);
  const [data, setData] = useState<JourneyPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const seq = useRef(0);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => setPage(1), [debounced, filters]);
  useEffect(() => {
    const s = ++seq.current;
    setLoading(true);
    setErr(null);
    api
      .journeys({ ...filters, q: debounced, page, page_size: PAGE_SIZE })
      .then((r) => s === seq.current && setData(r))
      .catch((e) => s === seq.current && setErr(e))
      .finally(() => s === seq.current && setLoading(false));
  }, [debounced, filters, page, bump]);

  const isSel = (j: Journey) => selected.some((x) => x.id === j.id);
  const toggle = (j: Journey) => {
    if (!multi) return onChange([j]);
    onChange(isSel(j) ? selected.filter((x) => x.id !== j.id) : [...selected, j]);
  };
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const set = (k: keyof JourneyQuery, v: string) => setFilters((f) => ({ ...f, [k]: v }));
  const facet = (name: 'status' | 'folder') => data?.facets?.[name] ?? {};

  return (
    <div className="picker">
      {manual && (
        <div style={{ marginBottom: '0.75rem' }}>
          {showForm ? (
            <ManualJourneyForm
              onCancel={() => setShowForm(false)}
              onAdded={(j) => {
                onChange(multi ? [...selected, j] : [j]);
                setShowForm(false);
                setBump((b) => b + 1);
              }}
            />
          ) : (
            <div className="row">
              <button className="btn" onClick={() => setShowForm(true)}>+ Inserisci un journey</button>
              <span className="muted small">Modalità senza API: l'elenco contiene solo i journey inseriti a mano.</span>
            </div>
          )}
        </div>
      )}
      {selected.length > 0 && (
        <div className="picker-selected">
          <span className="small muted" style={{ fontWeight: 600 }}>
            {multi ? `Selezionati (${selected.length})` : 'Selezionato'}:
          </span>
          {selected.map((j, i) => (
            <span key={j.id} className="chip">
              {i === 0 && multi && selected.length > 1 && <span className="chip-tag" title="Journey di riferimento per advisor e dimensionamento">rif.</span>}
              {j.name}
              <button aria-label={`Rimuovi ${j.name}`} onClick={() => onChange(selected.filter((x) => x.id !== j.id))}>×</button>
            </span>
          ))}
        </div>
      )}

      <div className="picker-bar">
        <div className="search-box">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" />
          </svg>
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Cerca per nome, chiave o cartella (es. carrello IT, LOY_00012)…"
            aria-label="Cerca journey"
          />
          {loading && <Spinner />}
        </div>
        <select value={filters.status} onChange={(e) => set('status', e.target.value)} aria-label="Stato">
          <option value="">Tutti gli stati</option>
          {Object.entries(facet('status')).map(([s, n]) => <option key={s} value={s}>{statusLabel(s)} ({fmtInt(n)})</option>)}
          {filters.status && !(filters.status in facet('status')) && <option value={filters.status}>{statusLabel(filters.status)}</option>}
        </select>
        <select value={filters.folder} onChange={(e) => set('folder', e.target.value)} aria-label="Cartella">
          <option value="">Tutte le cartelle</option>
          {Object.entries(facet('folder')).map(([f, n]) => <option key={f} value={f}>{f} ({fmtInt(n)})</option>)}
          {filters.folder && !(filters.folder in facet('folder')) && <option value={filters.folder}>{filters.folder}</option>}
        </select>
        <select value={filters.channel} onChange={(e) => set('channel', e.target.value)} aria-label="Canale">
          <option value="">Tutti i canali</option>
          {Object.entries(CHANNELS).map(([c, l]) => <option key={c} value={c}>con {l}</option>)}
        </select>
        <select value={filters.sort} onChange={(e) => set('sort', e.target.value)} aria-label="Ordina per">
          <option value="name">Nome A–Z</option>
          <option value="volume">Volume più alto</option>
          <option value="modified">Modificati di recente</option>
        </select>
      </div>

      <ErrorBox error={err} />
      {data && (
        <>
          <div className="small muted" style={{ margin: '0.5rem 0' }}>
            {fmtInt(data.total)} journey trovati{data.total > 0 && ` · pagina ${data.page} di ${fmtInt(pages)}`}
          </div>
          <div className="picker-list" style={{ opacity: loading ? 0.6 : 1 }}>
            {data.items.map((j) => {
              const sel = isSel(j);
              const busy = !!j.active_control_groups?.length;
              return (
                <button key={j.id} className={`picker-row${sel ? ' selected' : ''}`} onClick={() => toggle(j)} aria-pressed={sel}>
                  <span className={multi ? `check-mark${sel ? ' on' : ''}` : 'radio-mark'} aria-hidden />
                  <span className="picker-main">
                    <span className="picker-name">{j.name}</span>
                    <span className="picker-sub">
                      <span className="mono">{j.key}</span>
                      {j.folder && <> · {j.folder}</>}
                      {j.last_modified && <> · modificato {fmtDate(j.last_modified)}</>}
                    </span>
                  </span>
                  <span className="picker-meta">
                    <span><strong>{fmtInt(j.monthly_volume)}</strong> <span className="muted">/mese</span></span>
                    <span className="muted">conv. {fmtPct(j.baseline.conversion_rate)}</span>
                  </span>
                  <span className="picker-badges">
                    {(j.channels ?? []).map((c) => <span key={c} className="badge">{CHANNELS[c] ?? c}</span>)}
                    <span className={`badge ${j.status === 'Running' ? 'green' : j.status === 'Draft' ? '' : 'amber'}`}>{statusLabel(j.status)}</span>
                    {busy && <span className="badge red" title={`Già in test: ${j.active_control_groups!.join(', ')}`}>già in test</span>}
                  </span>
                </button>
              );
            })}
            {data.items.length === 0 && (
              <p className="muted" style={{ padding: '1rem' }}>
                {manual && !debounced ? 'Nessun journey inserito: usa «+ Inserisci un journey».' : 'Nessun journey corrisponde alla ricerca.'}
              </p>
            )}
          </div>
          {pages > 1 && (
            <div className="pager">
              <button className="btn sm" disabled={page <= 1} onClick={() => setPage(1)}>«</button>
              <button className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹ Precedente</button>
              <span className="small muted">Pagina {page} di {fmtInt(pages)}</span>
              <button className="btn sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Successiva ›</button>
              <button className="btn sm" disabled={page >= pages} onClick={() => setPage(pages)}>»</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
