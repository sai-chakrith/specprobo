# Status

## Real

- Typed synthetic ECU specification and provenance model.
- Deterministic, configurable NRC priority and oracle.
- Independent stateful in-memory ECU simulator and transport.
- Deterministic test generation and execution report foundation.
- Eight constructor-configured simulator mutations with differential and live-mutant tests, plus AST-generated mechanical mutants compiled into fresh simulator subclasses.
- Generator setup sequences, provenance traces, JSON/Markdown report models, demo, and mutation evaluation entrypoint.
- SQLAlchemy 2 SQLite models, DB-enforced append-only hash-chained audit log, salted/hashed workspace API keys, workspace-scoped repository, explicit offline Chroma embeddings, and in-memory vector fake.
- C2 golden vectors cover every implemented service; the baseline loader reads five hand-authored example cases from `tests/baseline_cases.json`.

## Stubbed or pending

- Ingestion, API authentication/routes, Streamlit, SocketCAN, CAPL export, ODX/CDD parsing, and real Ollama extraction are stubbed/not included in this pass.
- Production ECU validation is not implemented; validation is against the independent simulator only.
- Conservative choice: a missing environment signal makes a precondition false.
- Mechanical evaluation reports total, killed, survived, and uncompilable mutants. Survivors are checked against at least 5,000 deterministic spec-aware request sequences and printed with operator, source line, code diff, and classification.
