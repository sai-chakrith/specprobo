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

The unmodified generated suite is 1,484 cases: 225 mutants are compilable, 172 are killed by output mismatch, 27 crash, and 41 survive. Of the survivors, 34 are equivalent and 7 are genuine gaps. Raw score is 76.4%; adjusted score is 90.1%. Run `python -m eval.extraction_eval` for the per-field extraction table; its offline FakeLLM run is 100% precision and recall for DID, length, and precondition fields for both OEMs.
