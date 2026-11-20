import { useEffect, useState } from 'react';
import { api, Settings, SettingsUpdate } from '../api';
import { Alert, ErrorBox, Loading, Spinner, useLoad } from '../components/ui';

export default function SettingsPage() {
  const s = useLoad(() => api.getSettings());
  const [form, setForm] = useState<Settings | null>(null);
  const [secret, setSecret] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  useEffect(() => {
    if (s.data) setForm(s.data);
  }, [s.data]);

  if (s.loading && !form) return <Loading />;
  if (s.error && !form) return <ErrorBox error={s.error} onRetry={s.reload} />;
  if (!form) return null;

  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => {
    setForm({ ...form, [k]: v });
    setSaved(false);
  };

  const save = async () => {
    setSaving(true);
    setErr(null);
    setSaved(false);
    try {
      const { sfmc_client_secret_set: _ignored, ...rest } = form;
      void _ignored;
      const body: SettingsUpdate = { ...rest };
      if (secret) body.sfmc_client_secret = secret;
      const res = await api.putSettings(body);
      setForm(res);
      setSecret('');
      setSaved(true);
      window.dispatchEvent(new Event('settings-changed'));
    } catch (e) {
      setErr(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: 860 }}>
      <div className="page-head">
        <div>
          <h1>Impostazioni</h1>
          <p>Configurazione dell'advisor (modello linguistico locale) e della connessione a Marketing Cloud.</p>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h2>Advisor LLM</h2>
          <label className="check">
            <input type="checkbox" checked={form.llm_enabled} onChange={(e) => set('llm_enabled', e.target.checked)} />
            Abilitato
          </label>
        </div>
        <p className="muted small">Compatibile OpenAI: Ollama, LM Studio, vLLM. Se il modello non è raggiungibile l'advisor usa regole deterministiche.</p>
        <div className="form-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
          <label className="field">
            Base URL
            <input type="text" value={form.llm_base_url} onChange={(e) => set('llm_base_url', e.target.value)} placeholder="http://localhost:11434/v1" disabled={!form.llm_enabled} />
          </label>
          <label className="field">
            Modello
            <input type="text" value={form.llm_model} onChange={(e) => set('llm_model', e.target.value)} placeholder="qwen2.5:7b-instruct" disabled={!form.llm_enabled} />
          </label>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <h2>Salesforce Marketing Cloud</h2>
        </div>
        <div className="row" style={{ marginBottom: '1rem', alignItems: 'stretch' }}>
          {(['mock', 'live'] as const).map((m) => (
            <button key={m} type="button" className={`selectable${form.sfmc_mode === m ? ' selected' : ''}`} style={{ flex: '1 1 220px', width: 'auto' }} onClick={() => set('sfmc_mode', m)}>
              <div className="sel-head">
                <h3>{m === 'mock' ? 'Mock (demo)' : 'Live'}</h3>
                <span className="radio-mark" />
              </div>
              <p>{m === 'mock' ? 'Dati e deploy simulati, nessuna chiamata a SFMC.' : 'Chiamate reali alle API REST/SOAP del Business Unit configurato.'}</p>
            </button>
          ))}
        </div>
        <div className="form-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
          <label className="field">
            Subdomain
            <input type="text" value={form.sfmc_subdomain} onChange={(e) => set('sfmc_subdomain', e.target.value)} placeholder="mcxxxxxxxxxxxxxxxx" />
          </label>
          <label className="field">
            MID (Business Unit)
            <input type="text" value={form.sfmc_mid} onChange={(e) => set('sfmc_mid', e.target.value)} placeholder="510000000" />
          </label>
          <label className="field">
            Client ID
            <input type="text" value={form.sfmc_client_id} onChange={(e) => set('sfmc_client_id', e.target.value)} />
          </label>
          <label className="field">
            Client secret
            <input type="password" value={secret} onChange={(e) => { setSecret(e.target.value); setSaved(false); }} placeholder={form.sfmc_client_secret_set ? 'già impostato' : 'non impostato'} autoComplete="new-password" />
            {form.sfmc_client_secret_set && <span className="hint">Già impostato — lascia vuoto per mantenerlo.</span>}
          </label>
        </div>
      </div>

      <div className="row" style={{ marginTop: '1.25rem' }}>
        <button className="btn primary" onClick={save} disabled={saving}>
          {saving && <Spinner />} Salva impostazioni
        </button>
        {saved && <Alert kind="ok">Impostazioni salvate.</Alert>}
      </div>
      {!!err && <div style={{ marginTop: '1rem' }}><ErrorBox error={err} /></div>}
    </div>
  );
}
