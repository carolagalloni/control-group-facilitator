# Control Group Facilitator — demo

Web app che aiuta a creare **control group (holdout) in Salesforce Marketing Cloud**:

1. **Scopo**: il cliente sceglie (o descrive a parole) cosa vuole misurare; l'LLM locale lo traduce in uno scopo.
2. **Posizione**: l'app legge il journey e propone dove mettere l'holdout (all'ingresso o prima di un'attività).
3. **Dimensione**: un motore statistico (non l'LLM) calcola la % di holdout, il tempo necessario e il costo opportunità, e dice onestamente se il test è fattibile.
4. **Deploy in SFMC**: Data Extension, Query Activity con assegnazione deterministica, Decision Split, automation.
5. **Monitoraggio**: lift, intervalli di confidenza, p-value, controllo SRM, ricavo incrementale e commento dell'advisor, su KPI configurabili.

L'LLM **interpreta, argomenta e spiega**. Tutti i numeri vengono dal motore statistico. Ogni risposta dell'LLM è validata e, se il modello è spento, irraggiungibile o risponde male, l'app usa regole deterministiche. Ogni testo mostra la sua fonte: «LLM locale» o «Regole».

## Avvio rapido

Prerequisiti: Python 3.11+, Node 18+. Opzionale ma consigliato: [Ollama](https://ollama.com).

```bash
ollama pull qwen2.5:7b-instruct    # una tantum, ~4.7 GB; gira su laptop con 16 GB di RAM
./start.sh                          # Windows: .\start.ps1
```

Apri http://localhost:8000. Senza Ollama la demo funziona lo stesso, con l'advisor a regole.

Sviluppo, con hot reload su due terminali:

```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev        # http://localhost:5173 (proxy /api → :8000)
```

Test del backend:

```bash
cd backend && python -m pytest -q
```

### LLM locale

Qualsiasi server con API **compatibile OpenAI** (`/v1/chat/completions`) funziona: Ollama, LM Studio, vLLM, llama.cpp server. URL e modello si configurano da **Impostazioni**. Modelli consigliati: `qwen2.5:7b-instruct` (miglior rapporto qualità/italiano/JSON) o `llama3.1:8b-instruct`. Sotto i 3B le risposte JSON diventano inaffidabili: in quel caso l'app ricade sulle regole.

## Modalità SFMC

| | **mock** (default) | **live** |
|---|---|---|
| Journey | catalogo di ~2.400 journey (3 curati + sintetici in 8 cartelle), ricerca paginata | ricerca paginata via REST (`GET /interaction/v1/interactions`, `nameOrDescription`, `$page`) |
| Data Extension | in memoria | create via SOAP, lette via REST |
| Query Activity | eseguite in Python con la stessa logica della SQL | create via REST e lanciate da «Aggiorna dati» |
| Decision Split / automation | simulati | **manuali**: l'app genera JSON e passi da seguire |
| Dati | 75 giorni di test retro-simulati, con un **effetto reale nascosto** | quelli della BU |

Nel mock le vendite sintetiche contengono un lift vero (Welcome +10%, Carrello +12%; SMS reminder solo +2%). La demo mostra che il motore lo **scopre** con il suo intervallo di confidenza, non che lo inventa.

Al primo avvio il mock crea anche tre iniziative di esempio su più journey sintetici (Retention, Cross-sell, Loyalty), così il monitoraggio per categoria non è vuoto. I tre journey curati restano liberi per la demo dal vivo.

### Iniziative, categorie e monitoraggio

- **Iniziativa**: lo stesso control group (obiettivo, % di holdout, KPI) applicato a uno o più customer journey. Nel wizard si selezionano più journey; ognuno riceve il suo holdout (DE, query e automation propri).
- **Monitoraggio dell'iniziativa** (`/iniziativa/:id`): totale e dettaglio journey per journey, con il confronto tra chi era nel control group e chi ha ricevuto le comunicazioni. Il totale somma gli snapshot dei journey (stessa % di holdout).
- **Categoria** (Onboarding, Retention, …, proposta dalla cartella SFMC del journey): la pagina **Monitoraggio** riassume ricavo incrementale e lift per categoria. Le % di holdout possono differire tra journey, quindi qui si sommano le stime journey per journey e le loro varianze, non gli snapshot.

### Collegare una BU reale

1. In SFMC: Setup → Installed Packages → nuovo package → componente **API Integration, Server-to-Server**.
2. Permessi: Journeys (Read, Write), Data Extensions (Read, Write), Automations (Read, Write, Execute), List and Subscribers (Read).
3. In **Impostazioni**: modalità `live`, subdomain (la parte prima di `.auth.marketingcloudapis.com`), MID della BU, client id e secret.

> ⚠️ L'adapter live (`backend/app/sfmc_live.py`) è scritto sulla documentazione pubblica delle API ma **non è stato testato su una BU reale**. Provalo su una BU di test prima di una demo dal vivo. La modifica dei journey attivi resta volutamente manuale: l'app non pubblica versioni di journey in produzione.

## Come funziona in SFMC

```
Automation giornaliera (prima dell'ingresso nel journey)
 ├─ 1. import DE di ingresso (esistente)
 ├─ 2. Query «Assign»  → CG_Assign_xxx   hash MD5(SubscriberKey + salt) % 100 < soglia ⇒ CONTROL
 ├─ 3. Query «Flag»    → DE di ingresso  propaga CG_Group
 └─ 4. Query «Results» → CG_Results_xxx  snapshot giornaliero degli aggregati per gruppo
Journey (nuova versione)
 └─ Decision Split su Event.CG_Group: CONTROL → uscita (o salta l'attività), TREATMENT → flusso normale
```

Scelte di design:

- **Assegnazione deterministica a monte, non Random Split.** Il Random Split di Journey Builder non lascia traccia interrogabile di chi è finito in quale ramo. Con l'hash ogni contatto ha sempre lo stesso gruppo: il risultato è riproducibile e verificabile, e chi rientra nel journey non cambia gruppo. La stessa funzione esiste in Python (`sfmc_sql.bucket`) ed è coperta da test.
- **Holdout su un touchpoint**: in entrambi i rami un'attività Update Contact scrive `ExposureDate`. È l'unico modo di sapere quali contatti di controllo sono arrivati a quel punto, perché il controllo non genera invii e quindi non compare nelle Data View.
- **La DE dei risultati contiene aggregati, non righe.** Somme, somme dei quadrati e prodotti incrociati bastano per calcolare varianze e intervalli di confidenza. L'app legge poche righe al giorno invece di paginare milioni di record via REST.
- **Un solo holdout per journey alla volta.** Due holdout sovrapposti si contaminano e gonfiano il lift (verificato nel mock), quindi l'API restituisce 409.

## Dati di ritorno: SFMC o altrove

| Sorgente | Dove si calcolano i KPI | Uso |
|---|---|---|
| `sfmc_de` (default) | **in SFMC** (Query «Results») | vendite caricate in una DE via import/SFTP/API |
| `csv` | nell'app | export da e-commerce/ERP |
| `sql` | nell'app | SQLite incluso; Postgres/BigQuery/Snowflake via SQLAlchemy |

Per le sorgenti esterne l'app legge da SFMC **solo la DE di assegnazione** e incrocia le vendite localmente, con lo stesso motore usato dal mock (`engine.compute_snapshots`). Per aggiungere una sorgente (Data Cloud, API e-commerce, data warehouse) basta implementare `load_sales()` in `backend/app/datasources.py`: deve restituire `OrderID, SubscriberKey, OrderDate, Amount`.

In modalità mock, `backend/data/samples/` contiene `sales_export.csv` e `sales.db`, allineati ai dati simulati, per provare le sorgenti CSV e SQL.

## Copione demo (10 minuti)

1. **Dashboard**: esiste già «Carrello abbandonato – holdout 15%» con un risultato significativo.
2. **Nuovo control group → Welcome Journey**, domanda: *«L'SMS di reminder serve davvero?»*. L'advisor propone «valore di un touchpoint» prima dell'SMS. Il passo Dimensione risponde **non fattibile**: è il momento di valore, perché l'app dice la verità scomoda e propone di misurare l'intero journey.
3. Torna indietro e chiedi: *«Il journey di benvenuto porta vendite in più?»*. Holdout all'ingresso, verdetto **fattibile** intorno al 20%.
4. **Monitoraggio**: KPI, attribuzione a 30 giorni, sorgente DE SFMC (oppure CSV/SQL per mostrare l'alternativa).
5. **Deploy**: mostra la SQL generata, le DE, il Decision Split e l'automation.
6. **Dettaglio**: lift cumulato con la banda di confidenza che si stringe nel tempo, controllo SRM, ricavo incrementale, commento dell'advisor.
7. Riattivazione clienti dormienti (4.000/mese): **non fattibile** a qualsiasi %. Così si vede che l'app non vende test impossibili.

## Struttura

```
backend/app/
  main.py         API FastAPI (contratto: docs/API.md) + serve il frontend compilato
  stats.py        sizing (power analysis), confronto gruppi, SRM: unica fonte dei numeri
  engine.py       snapshot giornalieri (equivalente Python della Query «Results»)
  sfmc_sql.py     DE, SQL e modifica journey generati; hash identico alla SQL
  sfmc_mock.py    SFMC simulato e generatore di dati con effetto reale
  sfmc_live.py    adapter REST/SOAP per una BU reale
  advisor.py      prompt LLM + validazione + fallback a regole
  datasources.py  sorgenti dei dati di vendita (SFMC DE, CSV, SQL)
frontend/         React + Vite + TypeScript, grafici SVG senza librerie, funziona offline
```

## Limiti noti

- Adapter live non testato su una BU reale (vedi sopra).
- In live, volumi e baseline del journey non arrivano dall'API: il wizard usa default modificabili. Un miglioramento naturale è stimarli da `_JourneyActivity` / `_Sent`.
- Holdout universale ed effetto frequenza sono visibili nell'interfaccia ma disabilitati.
- La tenuta dell'LLM in italiano e in JSON dipende dal modello. I prompt sono stati verificati con `qwen2.5:7b-instruct` su Ollama, su tutti i passi del wizard e sul commento dei risultati, per i tre journey del mock. Con un 7B le decisioni (posizione dell'holdout, % consigliata, alternativa) restano alle regole dell'app: il modello le spiega soltanto, usando fatti già formattati. Lasciate al modello, le contraddiceva.
- Su un laptop senza GPU un 7B impiega 40-120 secondi per risposta. Il timeout del client LLM è di 300 secondi.
- Windows: se la cartella del progetto ha un percorso lungo, `git clone` e `npm install` falliscono (path oltre i 260 caratteri). Clona con `git -c core.longpaths=true clone ...` e tieni il progetto in un percorso corto (es. `C:\dev\`).
