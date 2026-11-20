import { ReactNode, useEffect, useState } from 'react';
import type { Source } from '../api';

export function Spinner({ lg }: { lg?: boolean }) {
  return <span className={`spinner${lg ? ' lg' : ''}`} role="status" aria-label="Caricamento" />;
}

export function Loading({ text = 'Caricamento…' }: { text?: string }) {
  return (
    <div className="loading">
      <Spinner /> <span>{text}</span>
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="alert error" role="alert">
      <span className="alert-icon">!</span>
      <div className="alert-body" style={{ flex: 1 }}>
        <strong style={{ color: 'var(--red)' }}>Errore</strong> — {msg}
      </div>
      {onRetry && (
        <button className="btn sm" onClick={onRetry}>
          Riprova
        </button>
      )}
    </div>
  );
}

export function Alert({ kind, title, children }: { kind: 'error' | 'warning' | 'ok' | 'info'; title?: string; children: ReactNode }) {
  const icon = kind === 'ok' ? '✓' : kind === 'info' ? 'i' : '!';
  return (
    <div className={`alert ${kind}`}>
      <span className="alert-icon">{icon}</span>
      <div className="alert-body">
        {title && <strong>{title} </strong>}
        {children}
      </div>
    </div>
  );
}

/** Indicatore per chiamate LLM lunghe */
export function Thinking({ text = "L'advisor sta ragionando…" }: { text?: string }) {
  const [s, setS] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setS((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="thinking" role="status">
      <Spinner />
      <span>
        {text}
        {s >= 8 && <span className="small" style={{ opacity: 0.8 }}> il modello locale può richiedere fino a qualche decina di secondi</span>}
      </span>
      <span className="elapsed">{s} s</span>
    </div>
  );
}

export function SourceBadge({ source }: { source: Source | string }) {
  return source === 'llm' ? (
    <span className="badge violet" title="Risposta generata dal modello linguistico locale">LLM locale</span>
  ) : (
    <span className="badge teal" title="Risposta deterministica basata su regole (LLM non disponibile)">Regole</span>
  );
}

export function AdvisorBox({ title = 'Advisor', source, children, extra }: { title?: string; source?: Source | string; children: ReactNode; extra?: ReactNode }) {
  return (
    <div className="advisor">
      <div className="advisor-head">
        <AdvisorIcon />
        <span>{title}</span>
        {source && <SourceBadge source={source} />}
        {extra}
      </div>
      <div className="advisor-text">{children}</div>
    </div>
  );
}

export function AdvisorIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--violet)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z" />
      <path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" />
    </svg>
  );
}

export function Modal({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} className={value === t.id ? 'active' : ''} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

const STATUS_CLASS: Record<string, string> = { attivo: 'green', active: 'green', bozza: 'amber', draft: 'amber', errore: 'red', concluso: 'blue', terminato: 'blue', in_pausa: 'amber' };
export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${STATUS_CLASS[status?.toLowerCase()] ?? ''}`}>{status}</span>;
}

/** hook generico per caricamento dati */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fn()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, loading, reload: () => setN((x) => x + 1), setData };
}
