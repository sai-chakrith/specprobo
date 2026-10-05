# Status

## Real

- Typed synthetic ECU specification and provenance model.
- Deterministic, configurable NRC priority and oracle.
- Independent stateful in-memory ECU simulator and transport.
- Deterministic test generation and execution report foundation.
- Eight constructor-configured simulator mutations with differential and live-mutant tests.
- Generator setup sequences, provenance traces, JSON/Markdown report models, demo, and mutation evaluation entrypoint.

## Stubbed or pending

- Ingestion, Chroma, SQLAlchemy, API authentication, Streamlit, SocketCAN, CAPL export, ODX/CDD parsing, and real Ollama extraction are stubbed/not included in this pass.
- Production ECU validation is not implemented; validation is against the independent simulator only.
- Conservative choice: a missing environment signal makes a precondition false.
