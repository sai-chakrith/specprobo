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

- Ingestion and review are real: ReportLab renders OEM-A PDF, openpyxl renders OEM-B XLSX, pdfplumber/openpyxl return provenance-bearing blocks/rows, deterministic extraction proposes all structured spec sections, FakeLLM parses whole prose sentences, and OllamaClient is an opt-in JSON-schema/retry client. SQLAlchemy persists proposed fields with audited review decisions. FastAPI routes and the Streamlit review client are functional and offline-testable. SocketCAN, CAPL export, and ODX/CDD parsing remain pending.
- Production ECU validation is not implemented; validation is against the independent simulator only.
- Conservative choice: a missing environment signal makes a precondition false.
- Mechanical evaluation reports total, compilable, output mismatch, crash, survived, equivalent, genuine gap, raw score, and adjusted score. The generated suite is exactly `generate_suite(spec)`, with 2,014 cases and no survivor padding. The current generated result is raw 81.5% and adjusted 93.9%: 30 equivalent survivors and zero genuine gaps. Survivors are checked against at least 5,000 deterministic hypothesis-driven sequences. The security-access, tester-present, and NRC families are general rules, not mutant-targeted cases. Excluded helper and transport-wrapper lines are explicitly printed. F1 validates both baseline and generated suites on the clean simulator before scoring.

### Equivalent survivor review

Each item below was compared across the full deterministic sequence set and is observably equivalent; none is dead code:

- AUTO-0013: observably equivalent.
- AUTO-0019: observably equivalent.
- AUTO-0030: observably equivalent.
- AUTO-0040: observably equivalent.
- AUTO-0054: observably equivalent.
- AUTO-0062: observably equivalent.
- AUTO-0082: observably equivalent.
- AUTO-0084: observably equivalent.
- AUTO-0086: observably equivalent.
- AUTO-0088: observably equivalent.
- AUTO-0090: observably equivalent.
- AUTO-0101: observably equivalent.
- AUTO-0102: observably equivalent.
- AUTO-0124: observably equivalent.
- AUTO-0158: observably equivalent.
- AUTO-0160: observably equivalent.
- AUTO-0162: observably equivalent.
- AUTO-0163: observably equivalent.
- AUTO-0166: observably equivalent.
- AUTO-0167: observably equivalent.
- AUTO-0174: observably equivalent.
- AUTO-0184: observably equivalent.
- AUTO-0187: observably equivalent.
- AUTO-0193: observably equivalent.
- AUTO-0198: observably equivalent.
- AUTO-0210: observably equivalent.
- AUTO-0216: observably equivalent.
- AUTO-0221: observably equivalent.
- AUTO-0222: observably equivalent.
- AUTO-0226: observably equivalent.
