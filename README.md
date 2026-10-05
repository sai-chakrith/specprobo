# SpecProbe

SpecProbe is an offline proof of concept that turns synthetic OEM diagnostic specifications into reviewed, deterministic UDS conformance tests. The LLM boundary proposes fields only; the oracle owns expected protocol outcomes.

This repository is validated only against an ECU simulator with seeded defects, not production ECUs. Mutation score covers only the seeded defect classes.

## Quick start

```text
python -m pip install -e ".[dev]"
make lint test
```

The first foundation milestone contains the typed domain model, provenance, independent oracle and simulator, deterministic test generation, and runner. Integration adapters and UI are intentionally added in later milestones.
