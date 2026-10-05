# SpecProbe

SpecProbe is an offline proof of concept that turns synthetic OEM diagnostic specifications into reviewed, deterministic UDS conformance tests. The LLM boundary proposes fields only; the oracle owns expected protocol outcomes.

This repository is validated only against an ECU simulator with seeded defects, not production ECUs. Mutation score is calculated over the eight named mutants plus mechanically discovered decision-point mutants from one simulator implementation; survivor classifications are printed by the demo and evaluation commands.

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

The compliance layer uses SQLAlchemy 2 with SQLite triggers and hash-chained audit rows, plus a persistent Chroma backend and an in-memory fake for tests. Ingestion, API, UI, ODX/CDD, CAPL, and SocketCAN remain outside this pass.
