# CLAUDE.md — Control Group Facilitator

Istruzioni per Claude (Claude Code o un altro account) che riprende questo progetto. La storia completa, le scelte
fatte e i punti aperti sono in [docs/HANDOFF.md](docs/HANDOFF.md): leggilo prima di cambiare qualcosa.

## Cos'è

Demo web (Lutech, Marketing Competence Center) che aiuta a creare **control group / holdout in Salesforce Marketing
Cloud** e a misurarne l'incrementalità: obiettivo → posizione dell'holdout → dimensionamento statistico → monitoraggio
→ collegamento SFMC → deploy, poi monitoraggio per iniziativa, per journey e per categoria.

- Backend: Python 3.11+, FastAPI (`backend/app`). Contratto API: [docs/API.md](docs/API.md).
- Frontend: React + Vite + TypeScript, HashRouter, grafici SVG senza librerie (`frontend/src`).
- LLM locale compatibile OpenAI (default Ollama `qwen2.5:7b-instruct`), con fallback a regole.
- Lingua del prodotto, dei testi UI, dei commenti e dei commit: **italiano**.

## Regole che contano

- **I numeri li fa solo il motore statistico** (`stats.py`, `engine.py`). L'LLM interpreta e spiega, non decide
  percentuali, posizioni o verdetti. Ogni testo mostra la fonte («LLM locale» / «Regole»).
- **Assegnazione deterministica** (MD5(SubscriberKey + salt) % 100), identica in SQL (`sfmc_sql.py`) e in Python
  (`sfmc_sql.bucket`, coperta da test). Non sostituirla con il Random Split di Journey Builder.
- **Un solo holdout per journey alla volta** (409 se si sovrappongono).
- **La modifica dei journey attivi resta manuale**: l'app non pubblica versioni di journey in produzione.
- Tre modalità SFMC con la stessa interfaccia: `MockSFMC` (`sfmc_mock.py`), `LiveSFMC` (`sfmc_live.py`, **mai testato
  su una BU reale**), `FileSFMC` (`sfmc_file.py`, senza API, legge export CSV). Un metodo nuovo va aggiunto a tutte.
- Prima di creare qualunque cosa il backend esegue `service.check_link` (DE, campi, cartelle, colonne vendite): con un
  errore risponde 400 e non crea nulla.
- Tema Lutech: Montserrat, Crimson `#BE0036` (hover `#8C0031`), Jet `#333333`, bordi `#E1E3EA`, viola `#7F4073`,
  teal `#335A66`. Token in `frontend/src/styles.css`, logo SVG in `components/Header.tsx`.

## Comandi

```powershell
.\start.ps1            # crea .venv, installa, compila il frontend se manca, avvia su http://localhost:8000
.\start.ps1 -Rebuild   # ricompila il frontend
```

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest -q     # 24 test, ~2-3 minuti (il mock genera i dati)
```

```powershell
cd frontend; npm install; npm run build                  # tsc -b + vite build → frontend/dist (non versionato)
```

Sviluppo con hot reload: `uvicorn app.main:app --reload --port 8000` in `backend` e `npm run dev` in `frontend`
(porta 5173, proxy `/api` → 8000). All'avvio il mock impiega ~15 s a generare i dati.

`backend/data/` (stato, campioni, upload, export) è generato e non versionato: cancellarlo riporta la demo allo stato
iniziale.

## Git

- Branch aggiornato: **`claude/upbeat-darwin-tm2n58`** (default del repo). `main` è fermo a un commit vecchio (eb5d116).
- Si lavora su un branch `feat/...` o `fix/...` e poi si porta il branch principale avanti in fast-forward.
- Windows: con percorsi lunghi `git clone` e `npm install` falliscono. Usa `git -c core.longpaths=true clone ...` e un
  percorso corto (es. `C:\dev\`).
