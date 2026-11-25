import { NavLink, Link } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { api, Health } from '../api';

/** Logo Lutech (pittogramma + logotipo), vettoriale estratto dalle brand guidelines. */
export function LutechLogo() {
  return (
    <svg className="lutech-logo" viewBox="0 0 367 63.5" role="img" aria-label="Lutech">
      <path className="logo-mark" d="M54.14 53.21L86.16 53.21C88.43 37.59 93.82 22.96 101.68 9.99L91.09 9.99C75.46 21.08 62.71 35.94 54.14 53.21" />
      <path className="logo-mark" d="M97.66 0.34C57.41 7.24 22.69 30.34 0.47 62.7L40.19 62.7C50.81 35.41 71.46 13.1 97.66 0.34" />
      <path className="logo-word" d="M141.54 48.51L141.54 53.21L117.63 53.21L117.63 9.97L122.58 9.97L122.58 48.51L141.54 48.51" />
      <path className="logo-word" d="M183.14 48.67C179.92 51.86 175.49 53.45 169.84 53.45C164.15 53.45 159.69 51.86 156.47 48.67C153.24 45.49 151.63 41.07 151.63 35.42L151.63 9.97L156.57 9.97L156.57 35.42C156.57 39.58 157.76 42.83 160.13 45.17C162.5 47.52 165.74 48.69 169.84 48.69C173.96 48.69 177.19 47.53 179.52 45.2C181.85 42.88 183.02 39.62 183.02 35.42L183.02 9.97L187.96 9.97L187.96 35.42C187.96 41.07 186.35 45.49 183.14 48.67" />
      <path className="logo-word" d="M216.26 14.73L216.26 53.21L211.31 53.21L211.31 14.73L197.26 14.73L197.26 9.97L230.4 9.97L230.4 14.73L216.26 14.73" />
      <path className="logo-word" d="M240.64 48.51h30.16v4.7h-30.16Z" />
      <path className="logo-word" d="M240.64 28.94h26.75v4.76h-26.75Z" />
      <path className="logo-word" d="M240.64 9.97h29.34v4.77h-29.34Z" />
      <path className="logo-word" d="M310.91 11.52C313.66 12.64 316.09 14.18 318.2 16.15L315.22 19.92C313.53 18.23 311.57 16.9 309.32 15.94C307.08 14.98 304.79 14.49 302.43 14.49C299.22 14.49 296.26 15.25 293.57 16.77C290.87 18.29 288.75 20.35 287.19 22.95C285.63 25.55 284.85 28.41 284.85 31.53C284.85 34.63 285.63 37.48 287.19 40.09C288.75 42.71 290.88 44.77 293.58 46.29C296.29 47.81 299.24 48.57 302.43 48.57C304.79 48.57 307.07 48.11 309.29 47.21C311.52 46.31 313.49 45.03 315.22 43.38L318.26 46.79C316.07 48.84 313.58 50.46 310.79 51.66C307.99 52.85 305.13 53.45 302.19 53.45C298.11 53.45 294.37 52.48 290.96 50.53C287.55 48.58 284.85 45.92 282.85 42.57C280.85 39.21 279.85 35.53 279.85 31.53C279.85 27.57 280.86 23.94 282.88 20.63C284.9 17.32 287.63 14.7 291.07 12.76C294.5 10.82 298.27 9.85 302.37 9.85C305.31 9.85 308.15 10.41 310.91 11.52" />
      <path className="logo-word" d="M361.22 53.21L361.22 34.18L335.16 34.18L335.16 53.21L330.22 53.21L330.22 9.97L335.16 9.97L335.16 29.51L361.22 29.51L361.22 9.97L366.16 9.97L366.16 53.21L361.22 53.21" />
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
        <Link to="/" className="brand" aria-label="Control Group Facilitator — dashboard">
          <LutechLogo />
          <span className="brand-sep" aria-hidden />
          <span className="brand-name">Control Group<br />Facilitator</span>
        </Link>
        <nav className="nav">
          <NavLink to="/" end>
            Dashboard
          </NavLink>
          <NavLink to="/monitoraggio">Monitoraggio</NavLink>
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
                SFMC: {health ? ({ mock: 'demo', file: 'senza API (export)', live: 'API' } as Record<string, string>)[health.sfmc_mode] ?? health.sfmc_mode : '…'}
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
