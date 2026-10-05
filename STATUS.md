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

- Ingestion front-half is real: ReportLab renders OEM-A PDF, openpyxl renders OEM-B XLSX, pdfplumber/openpyxl return provenance-bearing blocks/rows, deterministic extraction proposes fields, FakeLLM normalizes prose conditions, and SQLAlchemy persists proposed fields with audited review decisions. Ollama is an opt-in interface and was not run offline. API authentication/routes, Streamlit, SocketCAN, CAPL export, and ODX/CDD parsing remain pending.
- Production ECU validation is not implemented; validation is against the independent simulator only.
- Conservative choice: a missing environment signal makes a precondition false.
- Mechanical evaluation reports total, compilable, output mismatch, crash, survived, equivalent, genuine gap, raw score, and adjusted score. The generated suite is exactly `generate_suite(spec)`, with 1,484 cases and no survivor padding. The generated result is raw 76.4% and adjusted 90.1%: 34 equivalent survivors and 7 genuine gaps. Survivors are checked against at least 5,000 deterministic hypothesis-driven sequences. The remaining genuine gaps are AUTO-0007 (NRC constant), AUTO-0048/AUTO-0123/AUTO-0124 (security-key sequence length/state), and AUTO-0092/AUTO-0167/AUTO-0169 (tester-present unsupported subfunction). The former line-97-style conditional survivors were re-examined: the survivors at the service-gate/empty-candidate paths are observable protocol gaps, not dead code; helper and transport-wrapper lines are explicitly excluded and printed.
