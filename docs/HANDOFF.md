# Passaggio di consegne — Control Group Facilitator

Riassunto completo del lavoro fatto finora, per riprendere il progetto da un altro account Claude (o da un'altra
persona) senza perdere contesto. Le istruzioni operative brevi sono in [../CLAUDE.md](../CLAUDE.md), il contratto API in
[API.md](API.md), l'uso della demo nel [README](../README.md).

## 1. Come portare il progetto su un altro account

Tutto il necessario è nel repository GitHub `carolagalloni/control-group-facilitator`, branch
**`claude/upbeat-darwin-tm2n58`**. Le conversazioni con Claude non si trasferiscono tra account: questo file serve a
sostituirle.

1. **Accesso al codice.** Dall'altro account serve accesso al repository: aggiungi l'account GitHub come collaboratore
   (GitHub → Settings → Collaborators), oppure fai un fork, oppure scarica lo ZIP del branch.
2. **Clone su Windows**, in un percorso corto:
   ```powershell
   git -c core.longpaths=true clone -b claude/upbeat-darwin-tm2n58 https://github.com/carolagalloni/control-group-facilitator C:\dev\control-group-facilitator
   ```
3. **Prerequisiti:** Python 3.11+, Node 18+, e facoltativamente Ollama con `ollama pull qwen2.5:7b-instruct` (~4,7 GB).
   Senza Ollama l'advisor usa le regole e la demo funziona lo stesso.
4. **Avvio:** `.\start.ps1` nella cartella del progetto, poi http://localhost:8000.
5. **Claude Code sull'altro account:** apri la cartella del progetto. `CLAUDE.md` viene letto in automatico. Come primo
   messaggio puoi incollare il prompt della sezione 2.
6. **Cosa non è nel repository e va ricreato o riportato a mano:**
   - `backend/data/` (stato della demo, campioni, upload, export): si rigenera da solo all'avvio in modalità mock;
   - impostazioni SFMC live (subdomain, MID, client id/secret): si inseriscono da **Impostazioni**, non sono mai state
     configurate su una BU reale;
   - il PDF delle linee guida «Brand Guidelines_Lutech IT.pdf»: è servito a estrarre colori, font e logo, già
     incorporati nel codice. Per modifiche al brand va ricaricato a mano;
   - le skill Claude dell'account originale (es. Lutech/MCC, SQL SFMC) non sono necessarie al progetto.

## 2. Prompt da incollare nella nuova sessione

> Stai riprendendo il progetto Control Group Facilitator (demo Lutech per control group in Salesforce Marketing
> Cloud). Leggi `CLAUDE.md` e `docs/HANDOFF.md` prima di tutto: lì ci sono storia, scelte di design, stato dei test e
> punti aperti. Il branch di lavoro è `claude/upbeat-darwin-tm2n58`. Avvia la demo con `.\start.ps1` e lancia i test del
> backend per verificare che tutto sia verde. Rispondi in italiano. Poi chiedimi da dove ripartire.

## 3. Storia del lavoro

| Commit | Cosa |
|---|---|
| `1daccbc` | Backend: motore statistico, SFMC mock e adapter live, advisor LLM locale, sorgenti dati |
| `0837fce`, `eb5d116` | Frontend React completo (wizard, dashboard, dettaglio) |
| `d01c4ab` | Prompt dell'advisor verificati con `qwen2.5:7b-instruct` su Ollama, fix encoding su Windows |
| `73ea5d7` | Iniziative su più journey, monitoraggio per categoria, ricerca journey scalabile, tema Lutech |
| `11bdc35` | Modalità SFMC senza API (journey inseriti a mano, risultati letti dagli export) |
| `ce3e987` | Passo «Collegamento SFMC» nel wizard (DE di ingresso, cartelle, colonne vendite) con verifica |

Ognuno di questi è stato sviluppato su un branch (`fix/advisor-prompts-ollama`, `feat/monitoraggio-iniziative-lutech`,
`feat/sfmc-senza-api`, `feat/collegamento-sfmc`) e poi portato in fast-forward su `claude/upbeat-darwin-tm2n58`.
`main` è rimasto a `eb5d116` e **non** contiene il lavoro recente.

Le richieste che hanno guidato le ultime versioni:
- **Monitoraggio** diviso per customer journey e per iniziativa (gruppo di CJ lanciati insieme), più una vista generica per
  categoria di control group.
- **Confronto** tra chi era nel control group e chi ha ricevuto la comunicazione, per singolo CJ e per iniziativa.
- **Scelta del journey** che regga migliaia di journey per BU: ricerca, filtri e paginazione invece delle card.
- **Layout Lutech** preso dal PDF delle linee guida del brand.
- **Chiarezza sulla configurazione SFMC:** dove va la query, qual è la DE di ingresso, da dove arrivano le vendite.
  Da qui è nato il passo «Collegamento SFMC».
- **Lettura dei dati SFMC senza API**, da cui è nata la modalità export su file.

## 4. Cosa fa oggi l'app

**Wizard in 6 passi** (`frontend/src/pages/Wizard.tsx`):

1. **Obiettivo.**
   - Si sceglie uno o più journey con la ricerca paginata (`JourneyPicker`).
   - La domanda di business si può scrivere a parole: l'LLM la traduce in uno scopo (`journey_incrementality` o
     `touchpoint_value`).
   - Holdout universale e frequenza sono visibili ma disabilitati.
2. **Posizione.** Diagramma del journey e posizioni candidate (all'ingresso, oppure prima di un'attività) con pro e contro.
3. **Dimensione.** Power analysis: % di holdout, MDE, giorni necessari, costo opportunità e verdetto
   (fattibile / al limite / non fattibile).
4. **Monitoraggio.** Nome, categoria, KPI (ricavo per contatto, conversione, ordini per contatto, scontrino medio),
   finestra di attribuzione, guardrail (SRM, allarme sul lift negativo).
5. **Collegamento SFMC.**
   - Per ogni journey: DE di ingresso, campo chiave del contatto, Event Definition Key.
   - Cartelle di DE, query e automation.
   - Sorgente vendite (DE SFMC con mappatura colonne, CSV o SQL).
   - Pulsante «Verifica su SFMC».
6. **Riepilogo e deploy.**
   - In mock: simulato, con 75 giorni di dati retro-simulati.
   - In live: DE e query create via API; journey e automation restano manuali.
   - In modalità file: checklist tutta manuale.

**Monitoraggio:**
- `/iniziativa/:id`: totale e tab per journey, confronto controllo e trattamento, forest plot, lift cumulato con banda di
  confidenza, SRM, ricavo incrementale, commento dell'advisor, «Aggiorna dati», «Carica export…» in modalità file.
- `/monitoraggio`: per categoria (somma delle stime journey per journey) e tabella di tutti i journey in test.
- Dashboard: elenco delle iniziative con le categorie. «Elimina» rimuove l'iniziativa dall'app; in SFMC non cancella
  nulla.

**Modalità SFMC** (in **Impostazioni**):
- **mock**:
  - ~2.400 journey (3 curati + sintetici in 8 cartelle);
  - vendite sintetiche con un **effetto reale nascosto** (Welcome +10%, Carrello +12%, SMS reminder +2%);
  - tre iniziative di esempio create all'avvio (Retention, Cross-sell, Loyalty).
- **live**: Installed Package server-to-server (REST + SOAP). Scritto sulla documentazione pubblica, **mai provato su una
  BU reale**.
- **file (senza API)**:
  - journey inseriti a mano;
  - l'automation generata include Data Extract e File Transfer di `CG_Results_xxx.csv`;
  - l'app legge il file più recente da una cartella (SFTP montato o cartella sincronizzata) oppure da un caricamento
    manuale.

## 5. Concetti chiave (già spiegati al cliente interno)

- **Come si crea il control group in SFMC.** Un'automation giornaliera, prima dell'ingresso nel journey, esegue tre
  Query Activity:
  - **Assign** scrive `CG_Assign_xxx` con hash MD5 + salt; sotto la soglia si è CONTROL;
  - **AssignFlag** propaga `CG_Group` sulla DE di ingresso;
  - **Results** scrive in `CG_Results_xxx` gli aggregati giornalieri per gruppo.

  Nel journey, in una nuova versione, un Decision Split su `CG_Group` manda il controllo all'uscita (o gli fa saltare
  l'attività). Per un touchpoint, un Update Contact scrive `ExposureDate` in entrambi i rami.
- **Perché non il Random Split.** Non lascia traccia interrogabile di chi è finito in quale ramo. L'hash invece è
  riproducibile e chi rientra nel journey non cambia gruppo.
- **Ricavo incrementale** = (ricavo per contatto del trattamento − ricavo per contatto del controllo) × contatti del
  trattamento, con il suo intervallo di confidenza.
- **SRM (Sample Ratio Mismatch).** Test chi-quadro tra la % di controllo attesa e quella osservata. Se fallisce,
  l'assegnazione o il tracciamento sono rotti e il lift non è affidabile.
- **«CJ che funziona»** = lift positivo e statisticamente significativo sul KPI primario. Gli altri casi sono «negativo»,
  «non conclusivo» o «senza dati».
- **Iniziativa** = lo stesso control group (obiettivo, % di holdout, KPI) applicato a N journey, con un holdout per
  journey. Il totale dell'iniziativa somma gli snapshot, cosa valida perché la % di holdout è la stessa. La categoria
  invece somma stime e varianze journey per journey, perché le % possono essere diverse.
- **La DE dei risultati contiene aggregati**: somme, somme dei quadrati, prodotti incrociati. Bastano per varianze e
  intervalli di confidenza; l'app legge poche righe al giorno.

## 6. Mappa del codice

| File | Responsabilità |
|---|---|
| `backend/app/main.py` | API FastAPI, seeding della demo, validazioni, servizio del frontend compilato, no-cache sull'HTML |
| `backend/app/service.py` | stato persistente, build e deploy del control group, collegamento SFMC (`resolve_link`, `check_link`), risultati di iniziative e panoramica |
| `backend/app/stats.py` | sizing, confronto tra gruppi, SRM: unica fonte dei numeri |
| `backend/app/engine.py` | snapshot giornalieri (equivalente Python della Query «Results») |
| `backend/app/sfmc_sql.py` | definizioni DE, SQL generato, modifica del journey, `bucket()` |
| `backend/app/sfmc_mock.py` | catalogo sintetico, ricerca, simulazione dei dati con effetto reale |
| `backend/app/sfmc_live.py` | adapter REST/SOAP (ricerca journey, DE, query, cartelle, campi DE) |
| `backend/app/sfmc_file.py` | modalità senza API (export CSV/TSV UTF-8 o UTF-16) |
| `backend/app/datasources.py` | sorgenti vendite (DE SFMC, CSV, SQL) e mappatura colonne |
| `backend/app/advisor.py`, `llm.py`, `scopes.py` | prompt, validazione e fallback a regole; client LLM; catalogo degli scopi |
| `backend/tests/` | 24 test (`test_core`, `test_api`, `test_file_mode`, `test_llm_path`) |
| `frontend/src/api.ts` | tipi e client API |
| `frontend/src/pages/` | `Dashboard`, `Wizard`, `Initiative`, `Monitoring`, `Detail`, `Settings` |
| `frontend/src/components/` | `JourneyPicker`, `JourneyDiagram`, `ResultsView`, `Comparison`, `Charts`, `ArtifactsView`, `ManualJourneyForm`, `ExportUpload`, `Header` |

## 7. Verificato e non verificato

**Verificato:**
- 24 test del backend verdi, tra cui:
  - il percorso completo che ritrova il lift nascosto;
  - le iniziative su più journey;
  - la ricerca paginata;
  - la modalità file end-to-end;
  - la verifica del collegamento.
- Nel browser:
  - dashboard, pagina iniziativa, monitoraggio per categoria;
  - wizard fino al collegamento SFMC, con verifica ok e verifica con errore;
  - impostazioni della modalità file e form del journey manuale.
- Prompt LLM provati con `qwen2.5:7b-instruct` su tutti i passi del wizard e sul commento dei risultati.

**Non verificato:**
- **Adapter live su una BU reale**: autenticazione, ricerca journey, creazione di DE e query in cartella, lettura dei
  campi DE via SOAP.
- Un export reale da Marketing Cloud in modalità file (il formato è stato riprodotto, non preso da una BU).
- Un deploy completo dal wizard dopo l'ultimo passo aggiunto: il backend è coperto da test, l'interfaccia è stata
  provata fino alla verifica.

## 8. Punti aperti e idee

- **Provare il live su una BU di test** prima di qualunque demo dal vivo:
  1. creare l'Installed Package (Journeys R/W, Data Extensions R/W, Automations R/W/Execute, List and Subscribers R);
  2. compilare Impostazioni → live.
- In live volumi e baseline del journey non arrivano dall'API: il wizard usa default modificabili. Si potrebbero stimare
  da `_JourneyActivity` / `_Sent`.
- Le cartelle si cercano per nome: con due cartelle omonime si prende la prima. Si potrebbe aggiungere la scelta da un
  elenco.
- Nessun client SFTP diretto in modalità file: l'app legge da una cartella.
- Holdout universale ed effetto frequenza sono previsti nell'interfaccia ma disabilitati.
- In questa fase non è stata aperta nessuna pull request: i branch sono stati portati avanti direttamente.

## 9. Trappole note

- **Browser con la versione vecchia:** ricaricare con Ctrl+F5. Il server ora manda `Cache-Control: no-cache` sull'HTML.
- **LLM lento senza GPU:** un 7B impiega 40-120 secondi per risposta (timeout 300 s); il passo «Posizione» aspetta la
  risposta.
- **Avvio:** il mock impiega ~15 s a generare i dati; i test ~2-3 minuti.
- **Windows, percorsi lunghi:** `git clone` e `npm install` falliscono oltre 260 caratteri (vedi sezione 1).
- **Stato sporco:** per ripartire puliti, fermare il server e cancellare `backend/data/`.
