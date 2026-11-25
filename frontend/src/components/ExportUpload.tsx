import { useState } from 'react';
import { api, Results } from '../api';
import { ErrorBox, Spinner } from './ui';

/** Modalità senza API: carica a mano l'export della DE (in alternativa al file che arriva da SFTP). */
export default function ExportUpload({ cgId, journeyName, fileName, folder, onLoaded }: {
  cgId: string;
  journeyName?: string;
  fileName?: string;
  folder?: string | null;
  onLoaded: (r: Results) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const upload = async (file: File) => {
    setBusy(true);
    setErr(null);
    try {
      onLoaded(await api.uploadExport(cgId, file));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="export-upload">
      <div className="row" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <strong>{journeyName ? `${journeyName}: ` : ''}export da Marketing Cloud</strong>
          <div className="small muted">
            L'app legge <span className="mono">{fileName ?? 'il file della DE'}</span>
            {folder ? <> dalla cartella <span className="mono">{folder}</span></> : null}. Lo produce la Data Extract dell'automation;
            puoi anche esportare la DE da Contact Builder e caricarla qui.
          </div>
        </div>
        <span className="btn sm primary file-btn" role="button" tabIndex={0}>
          {busy ? <Spinner /> : '⤒'} Carica export…
          <input type="file" accept=".csv,.txt,.tsv,text/csv" aria-label="Carica export CSV"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ''; }} />
        </span>
      </div>
      <ErrorBox error={err} />
    </div>
  );
}
