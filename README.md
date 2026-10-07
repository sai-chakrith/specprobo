# SpecProbe

SpecProbe implements the Case Study 5 diagnostic assistant workflow: ingest authorized specifications, review extracted fields, retrieve cited knowledge, generate deterministic UDS tests, approve a saved test suite, export Python automation, and compare simulator responses. The LLM proposes or explains information; deterministic rules own expected protocol outcomes.

## Run locally

Python 3.11 or later is required. Install the locked development environment:

```powershell
uv sync --extra dev
```

Start these in two terminals from the repository:

```powershell
uv run uvicorn specprobe.api.app:app --host 127.0.0.1 --port 8000
```

```powershell
uv run streamlit run src/specprobe/ui/app.py
```

Open http://localhost:8501. API documentation is at http://localhost:8000/docs. SQLite data and Chroma collections persist across restarts. Copying `.env.example` does not automatically load environment variables: export them in your shell or deployment configuration.

Docker is also supported:

```text
docker compose up --build
```

The API and UI bind to localhost on ports 8000 and 8501. Docker stores the database and vectors in the `specprobe-data` named volume. Docker requires an installed daemon and was not exercised on the development host.

## Engineer workflow

1. Enter a workspace name and an API key of at least eight characters; click **Create workspace** once. Enter your reviewer name.
2. Upload an authorized source into its standard, OEM, ECU, or project collection. Supported files are text-based PDF, XLSX, EcuSpec JSON, TXT and Markdown (10 MB maximum). TXT/Markdown are knowledge references rather than executable specifications.
3. Approve the source document, then inspect extracted values and page/sheet/row evidence in **Specification review**. Approve, edit with JSON, or reject individual fields. After reviewing every field, batch approval is available. Rejected fields must be corrected before generation.
4. Select the source document and generate a uniquely named suite. Inspect the saved specification, requests, setup sequences, expected responses, trace references and coverage summary.
5. Approve that exact suite snapshot. Only approved suites may be exported or run. Revoking suite or source approval blocks subsequent execution; source revocation also blocks export and knowledge retrieval.
6. Download the executable Python template or JSON suite, run against the simulator, validate individual hex messages, and download reports. The Python template exposes `make_transport(spec)` for an independently validated bench adapter.

For a complete demonstration, upload `data/synthetic/ground_truth/oem_b.json`. The rendered OEM-A PDF and OEM-B XLSX provide alternative structured input formats. JSON follows the `EcuSpec` schema and carries complete reviewable defaults. PDF/XLSX extraction supports the repository's documented synthetic layouts and canonical field paths; arbitrary OEM layouts need parser adaptation and expert validation. Missing required sections fail generation rather than falling back to a demo ECU. Scanned PDFs require OCR before ingestion.

Saved suites are snapshots: later field edits do not silently change their tests. Generate and approve a new suite to incorporate a revision. Suite/run IDs must be globally unique within the database; repeated IDs return HTTP 409.

## Local AI and retrieval

Offline mode uses deterministic token-hash embeddings and returns source excerpts with citations. Similarity scores are not calibrated confidence. Unapproved documents never appear in retrieval. Collections separate standard/OEM/ECU/project knowledge within each workspace.

For local model explanations, run an approved Ollama model on your infrastructure and configure:

```powershell
$env:SPECPROBE_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:SPECPROBE_OLLAMA_MODEL = 'llama3.2'
```

Then select **Use the configured local model** in the Knowledge tab. Evidence and questions are supplied as untrusted content, citations must refer to retrieved evidence, and answers remain subject to engineer review. Optional prose extraction through Ollama is enabled with `SPECPROBE_EXTRACTION_MODE=ollama`. Local model connectivity failures return an explicit error. A live model was not provisioned or benchmarked during development; client integration is tested with controlled responses.

For semantic BGE/E5 embeddings, install `uv sync --extra dev --extra local-model`, download an approved model separately, and point `SPECPROBE_EMBED_MODEL_PATH` at its local directory. Loading uses `local_files_only=True`; the application does not download models. Start with a new `SPECPROBE_VECTOR_PATH` when changing embedding models or dimensions and reingest sources. Chroma telemetry is disabled.

## Validation and practical limits

```text
uv run ruff check src tests
uv run mypy src
uv run pytest -q
uv run python -m eval.extraction_eval
uv run python -m eval.mutation_eval
```

Regression tests cover JSON/PDF/XLSX upload-to-run, edited values, workspace isolation, approval and revocation gates, saved snapshots, persistent retrieval after restart, executable Python export, citation controls, audit integrity and UI onboarding. The independent simulator is tested using hand-authored golden vectors and named/AST-generated defects.

The demo suite has 2,014 cases. Mechanical evaluation reports 227 compilable mutants, 185 output mismatches, 27 crashes and 30 equivalent survivors: raw 81.5%, adjusted 93.9%, with no observable genuine gaps in the classifier's tested sequences. These are simulator results, not real ECU defect-detection guarantees. Extraction evaluation measures the synthetic fixture layouts; its scores do not establish accuracy on arbitrary OEM documents.

Coverage reports count generated positive/negative/suppressed outcomes, services, NRCs and test families. They are not percentages of a complete ISO 14229 requirements catalogue. P2/P2-star/S3 values are stored, but real timing behavior is not measured. Deterministic security keys and zero-filled DID read data are simulator conventions that must be replaced or parameterized for actual ECUs. Python export satisfies the case study's alternative framework export requirement; native CANoe/CAPL, SocketCAN and ODX/CDD integrations remain optional future adapters.

This is a controlled engineering pilot. Keys isolate workspaces and are salted/hashed, but reviewers are named by the key holder rather than independently authenticated enterprise users. Public workspace registration is intended for localhost use; enterprise rollout needs identity/RBAC, TLS, deployment isolation, backup and operational controls. Engineering acceptance, generation accuracy on representative customer specifications, authoring-time reduction and template reuse rate require a measured user pilot.
