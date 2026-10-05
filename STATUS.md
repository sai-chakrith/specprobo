# Status

## Real

- Typed synthetic ECU specification and provenance model.
- Deterministic, configurable NRC priority and oracle.
- Independent stateful in-memory ECU simulator and transport.
- Deterministic test generation and execution report foundation.
- Eight constructor-configured simulator mutations with differential and live-mutant tests.
- Generator setup sequences, provenance traces, JSON/Markdown report models, demo, and mutation evaluation entrypoint.
- SQLAlchemy 2 SQLite models, DB-enforced append-only hash-chained audit log, workspace-scoped repository, persistent Chroma backend, and in-memory vector fake.
- C2 golden vectors cover every implemented service; C4 baseline has 38 hand-authored cases.

## Stubbed or pending

- Ingestion, API authentication/routes, Streamlit, SocketCAN, CAPL export, ODX/CDD parsing, and real Ollama extraction are stubbed/not included in this pass.
- Production ECU validation is not implemented; validation is against the independent simulator only.
- Conservative choice: a missing environment signal makes a precondition false.
- Current demo/eval runs report no survivors for the current named and auto-mutant catalogs; survivor reasons are still emitted whenever a future catalog produces one.
