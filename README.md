# SpecProbe

SpecProbe is an offline proof of concept that turns synthetic OEM diagnostic specifications into reviewed, deterministic UDS conformance tests. The LLM boundary proposes fields only; the oracle owns expected protocol outcomes.

This repository is validated only against an ECU simulator with seeded defects, not production ECUs. Mutation evaluation includes the named simulator mutants and real AST mutants compiled into fresh simulator subclasses. Mechanical mutants record their operator, source line, original code, mutated code, compile status, killed tests, and survivor classification; the denominator is never reduced without printing that evidence.

## Quick start

```text
uv sync --extra dev
make lint test
make demo
make eval
```

On Windows without `make`, use the equivalent commands:

```text
uv run ruff check src tests
uv run mypy src
uv run pytest -q
uv run python -m specprobe.demo
uv run python -m eval.mutation_eval
```

The compliance layer uses SQLAlchemy 2 with SQLite triggers and hash-chained audit rows, plus a persistent Chroma backend and an in-memory fake for tests. Synthetic OEM-A PDF and OEM-B XLSX documents are rendered under `data/synthetic/rendered/`; `specprobe.ingest` parses them into page/sheet-row provenance and proposes fields through the offline FakeLLM boundary. Proposed fields are persisted workspace-scoped and review decisions are audited; only approved or edited fields are eligible for suite generation. API, UI, ODX/CDD, CAPL, and SocketCAN remain outside this pass.

## Offline vectors

Tests and CI use the dependency-free deterministic `HashEmbedding`. Connected development may use `LocalEmbedding` with a locally downloaded BGE-small or E5-small model by setting `SPECPROBE_EMBED_MODEL_PATH`; the one-time model download must be performed on a connected machine and copied to that path. Chroma telemetry is disabled and vector tests reject socket connections.

## Baseline evaluation

The baseline is loaded from `tests/baseline_cases.json`. Its expected bytes are hand-authored hex values and are never computed from the oracle. Run `python -m eval.mutation_eval --author-time-minutes 35` to include measured human authoring time.

The unmodified generated suite is 2,014 cases: 227 mutants are compilable, 185 are killed by output mismatch, 27 crash, and 30 survive. All 30 survivors are observably equivalent under the 5,000-sequence classifier; no genuine gaps remain. Raw score is 81.5%; adjusted score is 93.9%. Run `python -m eval.extraction_eval` for per-field extraction tables. FakeLLM reports 100% recall and 50% precision for preconditions because negated prose variants are deliberately reported as wrong tuples; sessions, security, services, routines, timing, and NRC priority are measured separately.

The FastAPI app is `specprobe.api.app`; start it with `uvicorn specprobe.api.app:app`. The Streamlit review client is `streamlit run src/specprobe/ui/app.py`. Both use workspace API keys, audited review decisions, and approved-only suite metadata. CAPL export and SocketCAN remain stubs.
