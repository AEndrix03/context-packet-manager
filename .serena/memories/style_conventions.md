# Style & Conventions
- Python 3.10-3.12; type hints encouraged.
- Ruff configured per component: line length 120 in `cpm/` and `registry/`, 110 in `embedding_pool/`.
- Black configured in `cpm/` and `registry/`.
- Naming: modules/functions `snake_case`, classes `PascalCase`.
- Tests follow `test_*.py` or `*_test.py` under `cpm/tests/`, `embedding_pool/tests/`, or `registry/tests/`.
- Avoid committing registry DB artifacts unless explicitly required (e.g., `registry/registry.db*`).