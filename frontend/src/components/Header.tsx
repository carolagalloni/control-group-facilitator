import { NavLink, Link } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { api, Health } from '../api';

export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="var(--primary)" />
      <circle cx="12.5" cy="16" r="5.5" fill="none" stroke="var(--on-primary)" strokeWidth="2.4" />
      <circle cx="20.5" cy="16" r="5.5" fill="var(--on-primary)" opacity="0.92" />
    </svg>
  );
}

export default function Header() {
  const [health, setHealth] = useState<Health | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .health()
        .then((h) => {
          if (!alive) return;
          setHealth(h);
          setErr(false);
        })
        .catch(() => alive && setErr(true));
    load();
    const t = setInterval(load, 20000);
    const onChange = () => load();
    window.addEventListener('settings-changed', onChange);
    return () => {
      alive = false;
      clearInterval(t);
      window.removeEventListener('settings-changed', onChange);
    };
  }, []);

  const llmOnline = !!health && health.llm.enabled && health.llm.reachable;
  const llmText = !health
    ? 'LLM: …'
    : !health.llm.enabled
      ? 'LLM: disattivato (fallback regole)'
      : `LLM: ${health.llm.model} · ${llmOnline ? 'online' : 'offline (fallback regole)'}`;

  return (
    <header className="app-header">
      <div className="header-inner">
        <Link to="/" className="brand">
          <BrandMark />
          <span>Control Group Facilitator</span>
        </Link>
        <nav className="nav">
          <NavLink to="/" end>
            Dashboard
          </NavLink>
          <NavLink to="/nuovo">Nuovo control group</NavLink>
          <NavLink to="/impostazioni">Impostazioni</NavLink>
        </nav>
        <div className="status-pills">
          {err ? (
            <span className="pill" title="Il backend non risponde">
              <span className="dot red" /> Backend non raggiungibile
            </span>
          ) : (
            <>
              <span className="pill" title={health?.sfmc_error ? `Errore SFMC: ${health.sfmc_error}` : 'Modalità di connessione a Salesforce Marketing Cloud'}>
                <span className={`dot ${health?.sfmc_error ? 'red' : health?.sfmc_mode === 'live' ? 'green' : 'amber'}`} />
                SFMC: {health?.sfmc_mode ?? '…'}
                {health?.sfmc_error && <strong style={{ color: 'var(--red)' }}>· errore</strong>}
              </span>
              <span className="pill" title={health?.llm.base_url}>
                <span className={`dot ${llmOnline ? 'green' : health ? 'amber' : ''}`} />
                {llmText}
              </span>
            </>
          )}
        </div>
      </div>
      {health?.sfmc_error && (
        <div className="header-warning" role="alert">
          <strong>Attenzione SFMC:</strong> {health.sfmc_error}
        </div>
      )}
    </header>
  );
}
