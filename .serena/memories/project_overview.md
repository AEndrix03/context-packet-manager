# Project Overview
Context Packet Manager (CPM) is a Python-based ecosystem for building, managing, and serving modular context packets for RAG apps. It includes CPM Core (CLI/service for building/querying packets), Embedding Pool (FastAPI embedding server with multiple models), and CPM Registry (self-hosted registry backed by S3-compatible storage and SQLite).

Tech stack highlights: Python 3.10-3.12, FastAPI (embedding server), FAISS for vector search, Sentence Transformers, S3-compatible storage for registry artifacts.