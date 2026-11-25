import { useState } from 'react';
import { api, Journey } from '../api';
import { ErrorBox, Spinner } from './ui';

const num = (s: string) => parseFloat(s.replace(',', '.'));

/** Modalità senza API: il journey non si legge da Marketing Cloud, lo descrive l'utente. */
export default function ManualJourneyForm({ onAdded, onCancel }: { onAdded: (j: Journey) => void; onCancel?: () => void }) {
  const [f, setF] = useState({ name: '', key: '', entry_de: '', monthly_volume: '', conversion: '', aov: '', messages: '', folder: '' });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  const valid = f.name.trim() && f.entry_de.trim() && num(f.monthly_volume) > 0 && num(f.conversion) > 0 && num(f.conversion) < 100 && num(f.aov) > 0;

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      const j = await api.addManualJourney({
        name: f.name.trim(), key: f.key.trim(), entry_de: f.entry_de.trim(), monthly_volume: Math.round(num(f.monthly_volume)),
        conversion_rate: num(f.conversion) / 100, avg_order_value: num(f.aov),
        messages: f.messages.split('\n').map((m) => m.trim()).filter(Boolean), folder: f.folder.trim() || null,
      });
      onAdded(j);
      setF({ name: '', key: '', entry_de: '', monthly_volume: '', conversion: '', aov: '', messages: '', folder: '' });
    } catch (e) {
      setErr(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="manual-form">
      <h3 style={{ marginBottom: 4 }}>Inserisci il journey</h3>
      <p className="muted small">Senza API l'app non legge il catalogo di Marketing Cloud: copia questi dati da Journey Builder e Contact Builder.</p>
      <div className="form-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
        <label className="field">Nome del journey<input type="text" value={f.name} onChange={set('name')} placeholder="Carrello abbandonato IT" /></label>
        <label className="field">
          External Key della DE di ingresso
          <input type="text" value={f.entry_de} onChange={set('entry_de')} placeholder="Cart_Abandon_Entry" />
          <span className="hint">Journey Builder → ingresso del journey → Data Extension. Qui l'assegnazione scrive CG_Group.</span>
        </label>
        <label className="field">Chiave del journey (facoltativa)<input type="text" value={f.key} onChange={set('key')} placeholder="Abandoned_Cart" /></label>
        <label className="field">Cartella / categoria (facoltativa)<input type="text" value={f.folder} onChange={set('folder')} placeholder="Carrello e conversione" /></label>
        <label className="field">Ingressi al mese<input type="number" min={1} value={f.monthly_volume} onChange={set('monthly_volume')} placeholder="40000" /></label>
        <label className="field">Conversione attuale (%)<input type="number" min={0} step="0.1" value={f.conversion} onChange={set('conversion')} placeholder="8" /></label>
        <label className="field">Scontrino medio (€)<input type="number" min={0} value={f.aov} onChange={set('aov')} placeholder="120" /></label>
        <label className="field" style={{ gridColumn: '1 / -1' }}>
          Messaggi del journey, in ordine <span className="hint">uno per riga; «SMS» o «push» nel nome indicano il canale, altrimenti email</span>
          <textarea rows={3} value={f.messages} onChange={set('messages')} placeholder={'Email: hai dimenticato qualcosa?\nSMS codice sconto 5%'} />
        </label>
      </div>
      <ErrorBox error={err} />
      <div className="row" style={{ marginTop: '0.75rem' }}>
        <button className="btn primary" onClick={save} disabled={!valid || saving}>{saving && <Spinner />} Aggiungi journey</button>
        {onCancel && <button className="btn" onClick={onCancel}>Annulla</button>}
      </div>
    </div>
  );
}
