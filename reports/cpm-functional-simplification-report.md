# CPM Functional Analysis - Complessita, Superfluita, Semplificazione

Data: 2026-02-20
Autore: Analisi funzionale + tecnica (focus adozione, UX CLI, data ingestion)

## 1. Obiettivo

Rendere CPM "facile e potente" richiede due mosse parallele:
1. ridurre la complessita percepita nel percorso base (setup -> build -> query -> publish/install)
2. confinare le feature avanzate in un layer expert, senza perderne il valore enterprise

Questo report valuta le funzionalita attuali, indica quelle particolarmente complesse, quelle potenzialmente superflue nel core UX, e propone soluzioni concrete.

## 2. Baseline osservata

Comandi esposti oggi da `cpm help`:
- Core: `init`, `build`, `query`, `install`, `publish`, `pkg`, `lookup`, `embed`, `benchmark`, `benchmark-trend`, `diff`, `replay`, `help`, `listing`, `doctor`, `list`
- Plugin/esempi: `cpm-llm-builder`, `sample-builder`, `sample-command`

Osservazioni strutturali:
- Nel listing/help compaiono anche feature non "task CLI" (es. builder/retriever), aumentando rumore cognitivo.
- La piattaforma include gia controlli supply-chain molto avanzati (policy, verify, replay, drift, benchmark gates).
- Il dominio funzionale e ampio: packaging locale, OCI, hub policy, retrieval ibrido, audit.

## 3. Funzionalita particolarmente complesse (motivi e soluzioni)

## 3.1 Query runtime (alta complessita)

Motivo:
- `query` accorpa responsabilita molto diverse: risoluzione packet, source lazy (`--source`/`--registry`), lock storico (`--as-of`), scelta retriever/indexer/reranker, output/replay, embedding transport.
- Alto numero di flag aumenta rischio uso errato e support burden.

Soluzione:
- Introdurre modalita operative esplicite:
  - `cpm query simple` (solo input minimi)
  - `cpm query advanced` (flag completi)
- In alternativa, mantenere un solo comando ma con preset:
  - `--profile fast|balanced|strict-audit`
- Risolvere automaticamente retriever/indexer/reranker dal lock/config, esponendo override solo in advanced.

## 3.2 Build command multifunzione (alta complessita)

Motivo:
- `build` include `run`, `embed`, `lock`, `verify`, `describe`, `inspect`: molto potente ma difficile da apprendere.
- Molti utenti devono solo "costruire bene" senza capire lock/verify all'inizio.

Soluzione:
- Distinguere UX:
  - `cpm build` = happy path opinionato
  - `cpm packet verify|lock|inspect|describe` = manutenzione avanzata
- Aggiungere check guidati post-build con output prescrittivo (es. "next best action").

## 3.3 Embedding subsystem (complessita operativa)

Motivo:
- Provider model: add/list/remove/set-default/test/refresh/probe + auth/header/extra + discovery cache.
- Forte flessibilita tecnica ma costo cognitivo alto per onboarding.

Soluzione:
- Wizard `cpm embed quickstart`:
  - rileva endpoint
  - propone modello consigliato
  - verifica dimensioni
  - imposta default
- Conservare i comandi avanzati ma portarli in documentazione expert.

## 3.4 Supply-chain features nel percorso quotidiano (complessita percepita)

Motivo:
- Policy/hub verification/replay/diff/benchmark gates sono fondamentali in ambienti regulated, ma non necessari per il 70-80% dei casi iniziali.
- Se mostrati come "norma" troppo presto, rallentano adozione.

Soluzione:
- Product tiering esplicito:
  - Core: build/query/install/publish
  - Pro: benchmark/hybrid/rerank
  - Governance: policy/replay/diff/strict verify
- Abilitazione progressiva via config profile, non via dozzine di flag iniziali.

## 3.5 Plugin discoverability e collision model (complessita architetturale)

Motivo:
- Naming con `group:name`, collision handling, precedence workspace/user e utile ma non immediato.
- Esporre troppi dettagli registry a utenti finali crea attrito.

Soluzione:
- Nascondere i dettagli registry in output standard.
- Fornire `cpm plugin explain <name>` per casi diagnostici.
- Mostrare in help solo command-kind eseguibili, non builder/retriever interni.

## 4. Funzionalita potenzialmente superflue nel core UX (non inutili in assoluto)

## 4.1 `listing` separato da `help`

Motivo:
- Sovrapposizione funzionale elevata (`listing` e quasi alias di `help`).

Soluzione:
- Unificare in `help` con `--format json`.
- Tenere `listing` solo come alias deprecato (hidden).

## 4.2 Comandi sample in distribuzione standard (`sample-builder`, `sample-command`)

Motivo:
- Inquinano l'output comandi e comunicano maturita inferiore del prodotto.

Soluzione:
- Spostare sample plugin in `dev profile` oppure caricarli solo in test fixture.
- Non mostrarli in help/listing default.

## 4.3 Esposizione top-level di feature non task-oriented (`default-builder`, `native-retriever`)

Motivo:
- Sono primitive interne/registrate, ma appaiono come comandi "utente" in help.

Soluzione:
- Filtrare in CLI per `kind=command` nell'overview.
- Introdurre `cpm registry list --all-kinds` per diagnostica tecnica.

## 4.4 `benchmark-trend` come comando separato

Motivo:
- Valore alto per performance engineering, valore basso per utente standard.

Soluzione:
- Integrarlo in `benchmark --trend`.
- Mantenere `benchmark-trend` come alias compatibile.

## 5. Data Ingestion: valutazione curata e semplificazione

Punti forti attuali:
- pipeline chunking + embedding + index consolidata
- lockfile e artifact coerenti
- possibilita di sorgenti lazy (dir/oci/http)

Principali attriti:
- troppe scelte manuali precoci (builder/model/indexer/reranker/policy)
- scarsa distinzione tra ingest "documentale" e ingest "codebase" nel percorso base
- fallback/normalizzazioni utili ma non sempre trasparenti per l'utente

Soluzioni proposte:
1. `cpm ingest` come frontend unico
- `cpm ingest docs <path>`
- `cpm ingest code <path>`
- internamente delega a `build run` con preset affidabili

2. Profili ingestion opinionati
- `--profile docs-fast`, `docs-quality`, `code-rag`
- ogni profilo mappa chunking/model/indexing/rerank policy

3. Explainability operativa
- output finale standardizzato con:
  - sorgente risolta
  - builder effettivo
  - modello embedding usato
  - lock/versione prodotta
  - azione successiva consigliata

4. Guardrail automatici
- warning quando l'utente forza combinazioni incoerenti (es. reranker senza benefici attesi)
- suggerimenti auto-fix nel messaggio CLI

## 6. Disegno target: facile + potente

Layer 1 (default, facile):
- `init`, `ingest`, `query`, `publish`, `install`

Layer 2 (power user):
- `embed`, `pkg`, `lookup`, `benchmark`

Layer 3 (governance/enterprise):
- `policy`, `replay`, `diff`, verify avanzato, hub policy remota

Regola UX:
- default minimalista
- advanced esplicito
- diagnostica separata

## 7. Piano di razionalizzazione consigliato

Fase 1 (rapida, alto impatto):
1. Filtrare help/listing ai soli command-kind
2. Nascondere sample commands dal runtime standard
3. Unificare `help/listing` e introdurre `help --format json`

Fase 2 (semplificazione ingestion/query):
1. Introdurre `cpm ingest` con preset
2. Aggiungere `query` profiles (`fast|balanced|strict-audit`)
3. Spostare opzioni rare in modalita advanced

Fase 3 (governance progressiva):
1. Spostare replay/diff/benchmark-trend in area "governance"
2. abilitare gate policy strict solo da profilo enterprise
3. documentazione separata: Quickstart vs Governance Playbook

## 8. KPI per misurare il miglioramento

1. Time-to-first-answer (setup + first query)
2. Numero medio di flag per comando nel flusso base
3. Percentuale utenti che completano build+query senza consultare docs avanzata
4. Riduzione ticket su errori di configurazione embeddings/registry
5. Adozione progressive: quota utenti che attiva feature governance dopo onboarding base

## 9. Conclusione

CPM e gia molto potente, ma oggi espone troppe capacita avanzate nel percorso primario.
La strategia corretta non e rimuovere potenza, ma "incapsularla":
- core UX minimale e opinionata
- advanced/gov opt-in
- data ingestion guidata da preset robusti

Questo approccio conserva il vantaggio tecnico di CPM e ne migliora drasticamente usabilita e adozione.
