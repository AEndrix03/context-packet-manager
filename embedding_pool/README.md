# Embedding Pool (standalone)

## Install Service

python -m venv .venv
.venv\Scripts\activate
pip install -U pip
pip install -e .

### Use with CPU

pip install -e ".[cpu]"

### Use with GPU

pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -e ".[gpu]"

## Init (creates .config/ in current dir)

embedpool init

## Start server (foreground)

embedpool pool start

## Start server detached

embedpool pool start --detach

## Register local sentence-transformers model

embedpool register --type local_st --model "jinaai/jina-embeddings-v2-base-code" --alias jina1 --min 1 --max 3

## Status

embedpool pool status

## Embed request

curl -X POST http://127.0.0.1:8876/embed \
-H "Content-Type: application/json" \
-d '{"model":"jina1","texts":["hello"],"options":{"normalize":true,"max_seq_length":1024}}'
