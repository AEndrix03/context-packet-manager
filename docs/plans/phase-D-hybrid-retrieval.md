# Phase D - Hybrid Retrieval

## Objective
Improve retrieval quality by combining sparse BM25 and dense FAISS with RRF and optional cross-encoder reranking.

## Scope
1. Add BM25 index builder/reader.
2. Add fusion strategy (RRF).
3. Add cross-encoder reranker plugin contract.
4. Preserve dense-only fallback.

## Implementation Steps
1. Introduce sparse index artifacts in packet layout.
2. Add hybrid indexer implementation to query builtins.
3. Register reranker extension interface in feature registry.
4. Add policy knob for enabling/disabling rerank.

## Tests
1. Hybrid result order deterministic for fixed inputs.
2. Fallback to dense-only when sparse index missing.
3. RRF score fusion produces expected ranking.
