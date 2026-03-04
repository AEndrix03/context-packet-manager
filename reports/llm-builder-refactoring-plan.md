# CPM LLM Builder Plugin — Piano di Refactoring Completo

## Contesto

Plugin per il sistema CPM (Context Packet Manager).
Scopo: dato un file sorgente qualsiasi, produrre chunk semanticamente coesi,
arricchiti (title, summary, tags, anchors, relations) pronti per l'embedding RAG.

Target chunk size: **200–350 token** (sweet spot RAG).
Requisito principale: **agnostico al linguaggio** (Java, Dart, C++, Angular/TS,
Python, Kotlin, Swift, PHP, Markdown, YAML, JSON, testo libero, ecc.).

---

## Principi architetturali del refactoring

1. **LLM-first chunking**: il LLM decide i confini semantici, non il prechunker.
   Il prechunker deterministico diventa solo un pre-split di emergenza per file
   enormi (> 600 righe), per non saturare il context window del LLM.
2. **Token budget rigoroso**: max 350 token per chunk, min 80 token.
3. **Cache granulare a 3 livelli**: file hash → window hash → chunk enrichment.
4. **Zero dipendenze dalla struttura sintattica del linguaggio** nel core plugin.
   La sintassi è delegata interamente al LLM tramite prompt.
5. **Fallback graceful**: se il LLM fallisce, usare prechunk deterministico base
   senza enrichment piuttosto che crashare.

---

## Struttura file target

```
cpm-llm-builder/
├── __init__.py
├── entrypoint.py          # invariato, aggancio al CPM core
├── features.py            # invariato, registrazione feature CPM
├── schemas.py             # MODIFICATO: nuovi dataclass, token budget
├── classifiers.py         # MODIFICATO: +30 estensioni, language hints
├── splitter.py            # NUOVO: sostituisce prechunk.py
├── llm_client.py          # MODIFICATO: nuovo prompt strategy, window batching
├── postprocess.py         # MODIFICATO: logica merge/split più aggressiva
├── validators.py          # MODIFICATO: warning più ricchi
├── cache.py               # MODIFICATO: cache v3 a 3 livelli
├── prompts/
│   ├── __init__.py
│   ├── chunk_and_enrich_v2.txt   # NUOVO prompt principale
│   └── enrich_only_v2.txt        # prompt fallback (solo enrichment)
└── tests/
    ├── test_classifiers.py
    ├── test_splitter.py
    ├── test_postprocess.py
    ├── test_validators.py
    └── test_llm_client.py        # con mock HTTP
```

---

## Step 1 — `schemas.py`

### Modifiche

**`ChunkConstraints`**: abbassare i default e aggiungere `window_lines`.

```python
@dataclass(frozen=True)
class ChunkConstraints:
    max_chunk_tokens: int = 350       # era 800 — CRITICO
    min_chunk_tokens: int = 80        # era 120
    max_segments_per_request: int = 6 # era 8
    window_lines: int = 120           # max righe per finestra LLM
    overlap_lines: int = 5            # righe di overlap tra finestre
```

**Nuovo dataclass `Window`**: rappresenta una finestra di righe del file
inviata al LLM per il chunking.

```python
@dataclass(frozen=True)
class Window:
    id: str               # "{path}:win:{start_line}"
    path: str
    text: str
    start_line: int
    end_line: int
    language: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: ...
```

**`Chunk`**: aggiungere campo `window_id` per tracciabilità e
`chunk_tokens` (calcolato al momento della creazione).

```python
@dataclass(frozen=True)
class Chunk:
    ...
    window_id: str = ""        # NUOVO
    chunk_tokens: int = 0      # NUOVO, calcolato da estimate_tokens
```

**`estimate_tokens`**: migliorare con euristica per CJK e simboli.

```python
def estimate_tokens(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    ascii_chars = sum(1 for c in cleaned if ord(c) < 128)
    non_ascii = len(cleaned) - ascii_chars
    # CJK e simili: ~1 token per carattere
    return max(1, (ascii_chars // 4) + non_ascii)
```

---

## Step 2 — `classifiers.py`

### Modifiche

Espandere `PIPELINES_BY_EXT` con **tutti** i linguaggi comuni.
Aggiungere helper `language_hints(classification)` che restituisce
suggerimenti testuali da iniettare nel prompt LLM.

**Estensioni da aggiungere** (lista completa):

```python
# JVM
".kt":    FileClassification("code_generic", "kotlin",     "text/x-kotlin"),
".kts":   FileClassification("code_generic", "kotlin",     "text/x-kotlin"),
".scala": FileClassification("code_generic", "scala",      "text/x-scala"),
".groovy":FileClassification("code_generic", "groovy",     "text/x-groovy"),

# Mobile
".dart":  FileClassification("code_generic", "dart",       "text/x-dart"),
".swift": FileClassification("code_generic", "swift",      "text/x-swift"),
".m":     FileClassification("code_generic", "objc",       "text/x-objc"),

# Web / Frontend
".jsx":   FileClassification("code_generic", "javascript", "text/javascript"),
".vue":   FileClassification("code_generic", "vue",        "text/x-vue"),
".scss":  FileClassification("code_generic", "scss",       "text/x-scss"),
".css":   FileClassification("code_generic", "css",        "text/css"),

# Scripting
".php":   FileClassification("code_generic", "php",        "text/x-php"),
".rb":    FileClassification("code_generic", "ruby",       "text/x-ruby"),
".lua":   FileClassification("code_generic", "lua",        "text/x-lua"),
".sh":    FileClassification("code_generic", "shell",      "text/x-shellscript"),
".bash":  FileClassification("code_generic", "shell",      "text/x-shellscript"),
".ps1":   FileClassification("code_generic", "powershell", "text/x-powershell"),

# Systems
".zig":   FileClassification("code_generic", "zig",        "text/x-zig"),
".ex":    FileClassification("code_generic", "elixir",     "text/x-elixir"),
".exs":   FileClassification("code_generic", "elixir",     "text/x-elixir"),
".erl":   FileClassification("code_generic", "erlang",     "text/x-erlang"),

# Config / Data
".toml":  FileClassification("text",         "toml",       "application/toml"),
".xml":   FileClassification("text",         "xml",        "text/xml"),
".proto": FileClassification("code_generic", "protobuf",   "text/x-protobuf"),
".sql":   FileClassification("code_generic", "sql",        "text/x-sql"),
".tf":    FileClassification("code_generic", "terraform",  "text/x-terraform"),
".gradle":FileClassification("code_generic", "groovy",     "text/x-groovy"),
```

**Nuovo `language_hints()`**:

```python
LANGUAGE_HINTS: dict[str, str] = {
    "kotlin":     "Use 'fun' keyword for functions, 'class'/'object'/'data class' for types.",
    "dart":       "Use 'class' and methods. Widgets extend StatelessWidget/StatefulWidget.",
    "swift":      "Use 'func', 'class', 'struct', 'protocol', 'extension'.",
    "vue":        "File has <template>, <script>, <style> sections. Split by section first.",
    "php":        "Functions start with 'function', classes with 'class'.",
    "typescript": "Angular: look for @Component, @Injectable decorators as chunk boundaries.",
    "sql":        "Chunk by statement: CREATE, ALTER, INSERT, SELECT blocks.",
    "protobuf":   "Chunk by message, enum, service definitions.",
    "terraform":  "Chunk by resource, module, variable, output blocks.",
    "shell":      "Chunk by function definition or logical comment blocks.",
}

def language_hints(cls: FileClassification) -> str:
    return LANGUAGE_HINTS.get(cls.language, "")
```

---

## Step 3 — `splitter.py` (sostituisce `prechunk.py`)

### Responsabilità

Il splitter **non** cerca di capire la sintassi. Ha un solo obiettivo:
tagliare il file in **finestre (Window)** di dimensione gestibile da mandare
al LLM. Non sono chunk finali, sono input al LLM.

### Logica

```
1. Se file <= window_lines righe → una sola Window (intero file)
2. Se file > window_lines righe → sliding window con overlap
   - ogni window: window_lines righe
   - overlap: overlap_lines righe con la window precedente
   - i confini cercano di allinearsi a righe vuote (paragraph boundary)
     per non spezzare blocchi logici
```

### API pubblica

```python
def split_into_windows(
    path: str,
    content: str,
    classification: FileClassification,
    constraints: ChunkConstraints,
) -> list[Window]:
    ...
```

### Dettaglio implementazione

```python
def _find_split_point(lines: list[str], target: int, search_radius: int = 10) -> int:
    """
    Cerca una riga vuota vicino a `target` entro `search_radius`.
    Se non trovata, ritorna `target` esatto.
    """
    for delta in range(search_radius):
        for candidate in (target - delta, target + delta):
            if 0 < candidate < len(lines) and not lines[candidate].strip():
                return candidate
    return target
```

Le Window hanno overlap per garantire che chunk che attraversano un confine
di window vengano catturati correttamente dal LLM almeno in una delle due.
Il postprocessor elimina i duplicati per ID.

---

## Step 4 — `prompts/chunk_and_enrich_v2.txt` (nuovo prompt principale)

Questo è il cambiamento più importante. Il LLM riceve una Window e decide
lui i confini dei chunk.

```
You are a semantic code chunker for a RAG (Retrieval-Augmented Generation) system.

TASK: Given a source file window, identify logical chunks and enrich them.
A chunk should represent ONE coherent concept: a function, a class, a section,
a configuration block, a route group, etc.

TARGET SIZE: 200–350 tokens per chunk. Never exceed 400 tokens.
If a single function/class exceeds 400 tokens, split it at logical sub-boundaries
(inner methods, major code blocks), never in the middle of a statement.

LANGUAGE HINTS: {language_hints}

INPUT (JSON):
{
  "source": { "path": "...", "language": "...", "mime": "...", "hash": "..." },
  "window":  { "id": "...", "start_line": N, "end_line": N, "text": "..." },
  "constraints": { "max_chunk_tokens": 350, "min_chunk_tokens": 80 }
}

OUTPUT: Return ONLY a valid JSON object:
{
  "chunks": [
    {
      "id":       "<path>:<kind>:<start_line>:<short_hash>",
      "title":    "Short descriptive title (max 60 chars)",
      "summary":  "One sentence describing what this chunk does (max 150 chars)",
      "tags":     ["language", "kind", "...up to 5 tags"],
      "anchors":  { "path": "...", "start_line": N, "end_line": N },
      "text":     "Exact source text of this chunk",
      "relations": {
        "calls":      ["symbol1", "symbol2"],
        "called_by":  [],
        "imports":    ["Module1"],
        "extends":    "ParentClass"
      }
    }
  ]
}

RULES:
- Never omit parts of the window. Every line must appear in exactly one chunk.
- Do not invent or modify source text in "text" field. Copy verbatim.
- Overlap lines (seen in previous window) should be included only if they
  logically complete a chunk starting in this window.
- If a chunk is too small (< 80 tokens), merge it with the adjacent chunk.
- Tags must include: language, chunk kind (function/class/import_block/
  config/test/etc.), and up to 3 semantic tags.
```

### `prompts/enrich_only_v2.txt` (fallback)

Usato solo quando il prechunk deterministico è già stato fatto e si vuole
solo aggiungere metadati (degraded mode se il chunk-and-enrich fallisce).

```
You are a chunk enrichment assistant for a RAG system.
Given pre-computed segments, add: title, summary, tags, relations.
Do NOT change chunk boundaries or text.
Return ONLY valid JSON: { "chunks": [...] }
```

---

## Step 5 — `llm_client.py`

### Modifiche principali

**Nuovo metodo `chunk_and_enrich()`** — prende una `Window`, ritorna `list[Chunk]`.
Sostituisce il vecchio `enrich()` che prendeva `Sequence[Segment]`.

```python
def chunk_and_enrich(
    self,
    *,
    source: SourceDocument,
    window: Window,
    constraints: ChunkConstraints,
    language_hints: str = "",
) -> list[Chunk]:
    ...
```

**Logica di building payload**:

```python
def _build_chunk_enrich_payload(
    source, window, constraints, model, prompt_version, language_hints
) -> dict:
    system_prompt = _load_prompt("chunk_and_enrich_v2.txt").replace(
        "{language_hints}", language_hints or "None"
    )
    task_payload = {
        "source": { ... },
        "window": window.to_dict(),
        "constraints": constraints.to_dict(),
    }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(task_payload, separators=(",",":"))},
        ],
        "temperature": 0,
        "stream": False,
    }
```

**Mantenere compatibilità** con il vecchio `enrich()` per non rompere
eventuali consumer esistenti — deprecarlo con un warning.

**Retry logic**: invariata, ma aggiungere rilevamento di `context_length_exceeded`
per ridurre automaticamente `window_lines` e riprovare con finestra più piccola.

```python
def _is_context_overflow(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in ("context_length", "too long", "max_tokens", "token limit"))
```

---

## Step 6 — `postprocess.py`

### Modifiche

**Deduplicazione per anchor**: chunk con stessi `start_line/end_line/path`
provenienti da window overlappate vanno deduplicati (tenere quello con
summary più lungo come euristica di qualità).

```python
def deduplicate_by_anchor(chunks: Sequence[Chunk]) -> list[Chunk]:
    seen: dict[tuple, Chunk] = {}
    for chunk in chunks:
        key = (
            chunk.anchors.get("path", ""),
            chunk.anchors.get("start_line", 0),
            chunk.anchors.get("end_line", 0),
        )
        existing = seen.get(key)
        if existing is None or len(chunk.summary) > len(existing.summary):
            seen[key] = chunk
    return list(seen.values())
```

**Ordinamento finale** per `start_line` prima di restituire.

**`apply_chunk_constraints`**: abbassare i soglie in linea con i nuovi default.
Invariata nella logica, ma **il split deve ricalcolare summary e tags**
per ogni sotto-chunk usando il testo effettivo, non ereditare quelli del
chunk padre (che si riferivano al blocco intero).

```python
def _resummary(text: str) -> str:
    """Fallback summary per chunk splittati automaticamente."""
    first_line = text.strip().splitlines()[0][:120]
    return first_line + "…" if len(text) > 120 else first_line
```

---

## Step 7 — `cache.py`

### Cache v3 — struttura

```python
CACHE_VERSION = 3

@dataclass
class WindowCacheEntry:
    window_hash: str          # hash del testo della window
    chunks: list[Chunk]       # chunk prodotti dal LLM per questa window

@dataclass
class FileCacheEntry:
    source_hash: str
    classification: dict[str, Any]
    windows: list[WindowCacheEntry]   # NUOVO: sostituisce segments

@dataclass
class CacheV3:
    files: dict[str, FileCacheEntry]
    # segment_enrichment rimosso: non più necessario col nuovo approccio
```

### Migrazione v2 → v3

```python
def _migrate_v2_to_v3(payload: Mapping) -> CacheV3:
    """
    I vecchi segment_enrichment diventano chunk orfani associati
    a una window sintetica per file. Sufficienti per non perdere
    il lavoro già fatto, ma verranno re-processati al prossimo
    cambio file.
    """
```

### Cache key per window

```python
def window_cache_key(window: Window, model: str, prompt_version: str) -> str:
    payload = {
        "window_text_hash": stable_hash(window.text),
        "model": model,
        "prompt_version": prompt_version,
    }
    return stable_hash(json.dumps(payload, sort_keys=True))
```

---

## Step 8 — `validators.py`

### Aggiunte

```python
@dataclass(frozen=True)
class ValidationResult:
    chunks: tuple[Chunk, ...]
    warnings: tuple[str, ...]
    stats: ChunkStats          # NUOVO

@dataclass(frozen=True)
class ChunkStats:
    total: int
    avg_tokens: float
    min_tokens: int
    max_tokens: int
    oversized: int             # chunk > max_chunk_tokens
    undersized: int            # chunk < min_chunk_tokens
    missing_summary: int
    missing_tags: int
```

Aggiungere warning esplicito se `avg_tokens > 400`:
```
"WARNING: avg chunk size {avg} tokens — consider reducing window_lines or max_chunk_tokens"
```

---

## Step 9 — `features.py` (modifiche al pipeline principale)

Questo file orchestra tutto. Il nuovo flusso deve essere:

```python
def process_file(path, content, constraints, source_doc) -> list[Chunk]:

    # 1. Classifica
    classification = classify_file(path, content)
    if not classification.is_supported_text:
        return []

    # 2. Cerca in cache (file hash)
    cached = cache.get_file(path, source_hash)
    if cached:
        return cached

    # 3. Split in windows
    windows = split_into_windows(path, content, classification, constraints)

    # 4. Per ogni window: cache check → LLM chunk_and_enrich → fallback
    all_chunks: list[Chunk] = []
    hints = language_hints(classification)

    for window in windows:
        win_key = window_cache_key(window, model, prompt_version)
        cached_win = cache.get_window(path, win_key)
        if cached_win:
            all_chunks.extend(cached_win)
            continue
        try:
            chunks = llm_client.chunk_and_enrich(
                source=source_doc,
                window=window,
                constraints=constraints,
                language_hints=hints,
            )
        except Exception as e:
            log(f"LLM failed for window {window.id}: {e}, using fallback")
            chunks = _fallback_chunks(window, source_doc)

        cache.set_window(path, win_key, chunks)
        all_chunks.extend(chunks)

    # 5. Postprocess: deduplicazione overlap + size constraints
    all_chunks = deduplicate_by_anchor(all_chunks)
    all_chunks = apply_chunk_constraints(all_chunks, constraints)
    all_chunks = sorted(all_chunks, key=lambda c: c.anchors.get("start_line", 0))

    # 6. Validate
    result = validate_chunks(all_chunks)
    for w in result.warnings:
        log(w)

    # 7. Salva cache file-level
    cache.set_file(path, source_hash, list(result.chunks))

    return list(result.chunks)
```

**`_fallback_chunks()`**: crea chunk grezzi dalla window senza enrichment,
per garantire che il file sia sempre rappresentato nella knowledge base
anche in caso di errore LLM.

```python
def _fallback_chunks(window: Window, source: SourceDocument) -> list[Chunk]:
    """Chunk deterministico di emergenza: paragrafi o blocchi da 200 righe."""
```

---

## Ordine di implementazione consigliato per Claude Code

```
1. schemas.py          — base di tutto, prima i dataclass
2. classifiers.py      — aggiungere estensioni + language_hints
3. splitter.py         — nuovo, sostituisce prechunk
4. prompts/            — i file .txt dei prompt
5. llm_client.py       — nuovo metodo chunk_and_enrich
6. postprocess.py      — deduplicate_by_anchor + resummary
7. cache.py            — v3 + migrazione
8. validators.py       — stats
9. features.py         — orchestrazione aggiornata
10. tests/             — unit test per ogni modulo
```

---

## Test da implementare

| File test | Cosa testa |
|-----------|-----------|
| `test_classifiers.py` | ogni estensione, language_hints, shebang detection |
| `test_splitter.py` | file piccoli (1 window), grandi (multi-window), overlap, boundary alignment |
| `test_postprocess.py` | deduplicazione overlap, split chunk grandi, merge chunk piccoli, ordinamento |
| `test_validators.py` | chunk vuoti, duplicati, stats corrette |
| `test_llm_client.py` | mock HTTP: response OpenAI-like, chat completions, fallback su context overflow, retry backoff |
| `test_cache.py` | migrazione v2→v3, round-trip serialize/deserialize |

---

## Note finali per Claude Code

- Mantenere tutti i moduli **indipendenti**: nessun import circolare.
- `splitter.py` non deve importare `llm_client.py` e viceversa.
- Usare **`from __future__ import annotations`** ovunque.
- Ogni dataclass frozen=True dove possibile.
- Nessuna dipendenza esterna nuova oltre a `requests` e `pyyaml` già presenti.
- I prompt `.txt` devono essere letti dal filesystem relativo al plugin root,
  non hardcoded nelle stringhe Python.
- Tutti i `print` di log devono passare per un metodo `_log()` che può
  essere silenziato tramite `verbose=False`.
