# Phase E - Context Compiler

## Objective
Return structured context packages (not only ranked chunks) for downstream LLM consumption.

## Target Output
1. `outline`
2. `core_snippets`
3. `glossary`
4. `risks`
5. `citations`

## Implementation Steps
1. Add compiler stage after retrieval/rerank.
2. Implement semantic dedup and section-aware ordering.
3. Add token-budget allocator.
4. Enforce citation presence on all snippets.

## Tests
1. Compiler always emits citations for included snippets.
2. Token budget cap is respected.
3. Deterministic output under fixed input ordering.
