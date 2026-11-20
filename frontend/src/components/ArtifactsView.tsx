import { useState } from 'react';
import type { Artifacts, DeDef } from '../api';
import { Tabs } from './ui';

export function CodeBlock({ code, lang, wrap }: { code: string; lang?: string; wrap?: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = code;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className={`code-block${wrap ? ' wrap' : ''}`}>
      <pre aria-label={lang}>
        <code>{code}</code>
      </pre>
      <button className="btn sm copy" onClick={copy}>
        {copied ? 'Copiato ✓' : 'Copia'}
      </button>
    </div>
  );
}

function DeTable({ title, de }: { title: string; de: DeDef }) {
  const extraCols = Array.from(new Set(de.fields.flatMap((f) => Object.keys(f)))).filter((k) => !['name', 'type', 'pk'].includes(k));
  return (
    <div>
      <h3>
        {title} <span className="mono muted">{de.key}</span>
      </h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Campo</th>
              <th>Tipo</th>
              <th>Chiave primaria</th>
              {extraCols.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {de.fields.map((f) => (
              <tr key={f.name}>
                <td className="mono">{f.name}</td>
                <td>{f.type}</td>
                <td>{f.pk ? <span className="badge blue">PK</span> : ''}</td>
                {extraCols.map((c) => (
                  <td key={c}>{f[c] === undefined || f[c] === null ? '' : String(f[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type Tab = 'sql_a' | 'sql_r' | 'de' | 'journey' | 'automation';

export default function ArtifactsView({ artifacts }: { artifacts: Artifacts }) {
  const [tab, setTab] = useState<Tab>('sql_a');
  const { journey_change: jc, automation } = artifacts;
  const { description, ...jcRest } = jc ?? { description: '' };
  return (
    <div>
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'sql_a', label: 'SQL assegnazione' },
          { id: 'sql_r', label: 'SQL risultati' },
          { id: 'de', label: 'Data Extension' },
          { id: 'journey', label: 'Modifica journey' },
          { id: 'automation', label: 'Automation' },
        ]}
      />
      {tab === 'sql_a' && (
        <div className="stack">
          <p className="muted small">Query Activity che assegna in modo deterministico (hash di SubscriberKey + salt) ciascun contatto al gruppo di controllo o di trattamento.</p>
          <CodeBlock code={artifacts.assignment_sql} lang="SQL" />
        </div>
      )}
      {tab === 'sql_r' && (
        <div className="stack">
          <p className="muted small">Query Activity che unisce assegnazioni e vendite nella finestra di attribuzione, alimentando la DE dei risultati.</p>
          <CodeBlock code={artifacts.results_sql} lang="SQL" />
        </div>
      )}
      {tab === 'de' && (
        <div className="stack">
          <DeTable title="DE di assegnazione" de={artifacts.assignment_de} />
          <DeTable title="DE dei risultati" de={artifacts.results_de} />
        </div>
      )}
      {tab === 'journey' && (
        <div className="stack">
          <p className="pre-wrap">{description}</p>
          <CodeBlock code={JSON.stringify(jcRest, null, 2)} lang="JSON" wrap />
        </div>
      )}
      {tab === 'automation' && automation && (
        <div className="stack">
          <dl className="dl">
            <dt>Nome</dt>
            <dd className="mono">{automation.name}</dd>
            <dt>Pianificazione</dt>
            <dd>{automation.schedule}</dd>
          </dl>
          <ol style={{ margin: 0, paddingLeft: '1.25rem' }}>
            {automation.steps?.map((s, i) => (
              <li key={i} style={{ padding: '0.2rem 0' }}>
                {s}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

const STATUS_META: Record<string, { cls: string; icon: string; badge: string }> = {
  ok: { cls: 'ok', icon: '✓', badge: 'green' },
  simulato: { cls: 'simulato', icon: '◇', badge: 'blue' },
  manuale: { cls: 'manuale', icon: '✎', badge: 'amber' },
  errore: { cls: 'errore', icon: '✕', badge: 'red' },
};

export function DeployLog({ log }: { log: { step: string; status: string; detail: string }[] }) {
  return (
    <ul className="checklist">
      {log.map((s, i) => {
        const m = STATUS_META[s.status] ?? STATUS_META.simulato;
        return (
          <li key={i}>
            <span className={`check-icon ${m.cls}`}>{m.icon}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="step-name">{s.step}</div>
              {s.detail && <div className="step-detail">{s.detail}</div>}
            </div>
            <span className={`badge ${m.badge}`}>{s.status}</span>
          </li>
        );
      })}
    </ul>
  );
}
