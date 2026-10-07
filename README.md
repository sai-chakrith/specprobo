# SpecProbe

SpecProbe implements a **bounded, simulator-first engineering pilot** for Case Study 5: UDS Diagnostics and Automated Test Generation Assistant. It ingests specifications, retains source evidence, requires document/field/suite review, generates deterministic tests, retrieves cited knowledge and exports Python automation. It is not independently validated for arbitrary OEM documents or production ECUs.

See [STATUS](STATUS.md), [validation evidence and dependencies](docs/VALIDATION.md), [deployment and recovery](docs/OPERATIONS.md) and [supervised pilot protocol](docs/PILOT.md).

## Launch on Windows

Use Python 3.11+ and the locked environment:

```powershell
uv sync --frozen --extra dev
# Create a new local administrator secret; keep the file private and outside source control.
New-Item -ItemType Directory -Force .specprobe | Out-Null
uv run python -c "import secrets,pathlib; p=pathlib.Path('.specprobe/admin.secret'); p.open('x').write(secrets.token_urlsafe(48))"
$env:SPECPROBE_AUTH_MODE = 'individual'
$env:SPECPROBE_ADMIN_SECRET_FILE = (Resolve-Path .specprobe/admin.secret).Path
uv run uvicorn specprobe.api.app:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
uv run streamlit run src/specprobe/ui/app.py
```

Open http://127.0.0.1:8501; API docs are at http://127.0.0.1:8000/docs. Restart existing API/UI processes after upgrading. Environment variables are explicitly exported; `.env.example` is documentation and is not automatically loaded.

Provision one user and workspace through the API (administrator secret file must match the API process):

```powershell
$admin = @{ 'X-Admin-Key' = (Get-Content .specprobe/admin.secret -Raw).Trim() }
$workspaceKey = uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/workspaces -Headers $admin -ContentType application/json -Body (@{workspace_id='pilot';api_key=$workspaceKey} | ConvertTo-Json)
$user = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/users/engineer -Headers $admin
Invoke-RestMethod -Method Put -Uri 'http://127.0.0.1:8000/workspaces/pilot/members/engineer?role=reviewer' -Headers $admin
# $user.token is returned once. Enter it as Individual access token in the UI.
```

Viewer roles can read and query; editors can ingest/generate/run approved suites; reviewers can approve/revoke. Audit review identities come from the authenticated token. Administrator-controlled membership supports `viewer`, `editor`, `reviewer`, `revoked`; `POST /users/{id}/credential` rotates a token, and `?revoke=true` disables it. Tokens are stored as hashes. TLS, identity lifecycle and private secret-file permissions remain deployment responsibilities.

For the existing localhost demonstration only, explicitly set `SPECPROBE_AUTH_MODE=workspace_key` before starting the API. This compatibility mode uses shared workspace keys and caller-supplied reviewer names; it does not provide individual accountability. It is not the deployed default.

## Engineer workflow

1. Upload authorized text PDF, XLSX or EcuSpec JSON (maximum 10 MB); TXT/Markdown are knowledge references. `data/synthetic/ground_truth/oem_b.json` is a complete **synthetic demonstration**, not an OEM specification.
2. Inspect extracted evidence and index status. Retry incomplete indexing with `POST /workspaces/{id}/documents/{document_id}/recover`; then approve the source.
3. Review every field, including preconditions, units, session/security references and unresolved requirements. Edits retain original provenance; batch approval commits atomically. Missing, contradictory or unsupported executable requirements block generation.
4. Generate a uniquely named suite. Inspect setup and every intermediate expected response, positive/negative cases, request lengths, traces and configured response masks.
5. Approve the exact immutable snapshot. Source or suite revocation blocks subsequent execution/export. Later field edits require a new reviewed snapshot. Protocol revision 2 blocks execution/export of old snapshots until regeneration and review.
6. Run the simulator and inspect separate setup, communication, configuration and ECU response mismatch results. Download JSON reports or an executable Python template.

Supported modeled SIDs: `0x10`, `0x11`, `0x22`, `0x27`, `0x2E`, `0x31`, `0x3E`. `DataIdentifier.preconditions` constrains writes; `read_preconditions` constrains reads; routine conditions constrain routine execution. Explicit read prose maps to the read field. Other DID prose follows the write-condition schema convention and must be checked by the reviewer. Empty DID read/write session permissions disable that operation. Normalized JSON evidence is marked explicitly, flags schema-derived defaults, and does not invent raw file line numbers. Schema-only defaults are excluded from source retrieval. Reingest and review original legacy JSON uploads before new generation/retrieval; historical records remain stored. OR/negated compound prose and unmapped requirements require engineer resolution. Units must use the supported canonical forms; seconds in the labeled S3 table column convert to milliseconds.

`response_profile` configures DID data, two-byte seeds, identity/XOR seed-key algorithms, XOR byte and positive-response masks. Masks cannot hide service/echo identity or length mismatch. `basis=engineer_configured` requires explicit readable-DID data and seeds. This label does **not** mean externally validated. Otherwise zero-filled DID values, seed bytes and XOR keys are labeled simulator conventions. Proprietary key functions, variable seed lengths, real reset persistence and OEM-specific NRC behavior require an approved extension and bench vectors.

`ControlledTransport` provides bounded P2/P2-star exchanges, response-pending handling, frame/echo checks and hardware enablement plus an approval-reference gate. No CAN interface is supplied or opened. Simulator S3 checks use virtual time and an observed session state. A real adapter must implement measured receive deadlines, controlled idle intervals, session observation and safe state preparation. Hardware execution is not available through the API.

## Local AI and evaluation

Offline retrieval returns approved source excerpts using deterministic hash embeddings. These are not trained semantic embeddings. Optional local models require separately supplied infrastructure:

```powershell
uv sync --frozen --extra dev --extra local-model
$env:SPECPROBE_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:SPECPROBE_OLLAMA_MODEL = '<your-approved-installed-model>'
$env:SPECPROBE_EMBED_MODEL_PATH = 'C:/models/<approved-local-embedding-directory>'
uv run python -m eval.local_ai_eval --output .specprobe/local-ai.json
```

Model answers must quote contiguous text from the cited excerpt; valid citation numbers alone are insufficient. Unsupported claims produce an insufficient-evidence answer. Structured source conflicts require engineer resolution. This conservative gate rejects some valid paraphrases and is not semantic entailment validation. The benchmark records retrieval recall@5/MRR separately from extractive answer support and preserves raw answers for human semantic review. The missing-infrastructure run is explicitly `NOT_RUN`.

When changing embedding models/dimensions, use a new vector path and reindex every approved source. The optional model loader uses local files only. Chroma telemetry is disabled.

```powershell
uv run ruff check src tests eval
uv run mypy src
uv run pytest -q
uv run python -m eval.extraction_eval
uv run python -m eval.heldout_eval --output .specprobe/candidate-extraction.json
uv run python -m eval.mutation_eval
uv run python -m eval.pilot_eval --observations data/evaluation/pilot-observations.csv --output .specprobe/pilot.json
```

The frozen extraction set is a **synthetic candidate holdout awaiting independent human review**. Its PDF table currently produces an explicit unresolved-target failure; its XLSX routine matrix extracts successfully. Reports include precision/recall by field type, missed requirements, correction actions and null measured correction time. Neither synthetic extraction scores nor mutation scores are real-world reliability percentages. Business benefits remain unmeasured until the supervised pilot is completed.

Docker configuration uses frozen dependencies, non-root execution, file-mounted administrator secrets and health checks. Docker is unavailable on the development host; follow the runtime validation procedure in `docs/OPERATIONS.md` before accepting that deployment.
