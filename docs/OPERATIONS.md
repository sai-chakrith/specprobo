# Deployment and recovery procedure

## Local access controls and secrets

Follow the individual-token bootstrap in README. Keep the administrator file outside source control with filesystem access restricted to the operator account. Prefer a file-mounted secret over an environment value; neither should be logged or embedded in exported suites. Use a TLS reverse proxy before any non-loopback deployment. Individual token authentication provides application identities, not enterprise SSO or legal identity verification. Reviewer roles can ingest and approve; enforced two-person author/reviewer separation is not implemented.

Administrators provision users/workspaces and grant or revoke memberships. Rotate with `POST /users/{id}/credential` using `X-Admin-Key`; revoke the user credential with `?revoke=true`. Previous token hashes no longer authorize. Shared workspace keys are ignored in individual mode. Explicit `workspace_key` mode is for a controlled localhost demonstration only.

`GET /health` is liveness. `GET /ready` checks database accessibility and audit-chain integrity and reports incomplete indexes, authentication mode and model revision. Monitor response status, audit validity, incomplete-job count and uvicorn error logs; alert on failed jobs and repeated HTTP 503/422. These endpoints do not prove model or ECU availability. No external monitoring service was configured.

## Docker acceptance (not run on the development host)

Prerequisites: Docker/Compose with a running Linux container daemon, access to the pinned uv package and required locked Python packages, a private administrator secret file, and permission to use the intended data volume.

```powershell
$env:SPECPROBE_ADMIN_SECRET_PATH = (Resolve-Path .specprobe/admin.secret).Path
# Record versions before testing.
docker version
docker compose version
docker compose config
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
Invoke-RestMethod http://127.0.0.1:8501/_stcore/health
```

The API runs as UID 10001; persistent volume files must be writable by that account. Previously created root-owned volumes need an operator-reviewed ownership migration/backup. The configuration does not automatically change existing volume ownership. Verify secret-file readability by the API container without making it readable to unrelated users.

Bootstrap an individual reviewer using README. Confirm shared workspace keys alone return 401 and viewer approval attempts return 403. Upload synthetic JSON, review all fields and source, generate/approve/run/export, and execute the Python export in a controlled environment. Restart containers and repeat retrieval/report access. Inject an indexing failure through the tested adapter in a test environment and verify recovery. Restore the database to a fresh volume and rebuild vectors; validate hashes, source/suite approval state and audit integrity. Capture image digests, `compose ps`, health responses and test output. Python 3.11 image behavior must be exercised independently of the Windows Python 3.14 environment.

Application dependencies are locked by `uv.lock` and installation uses `uv sync --frozen`. The base image tag is not a digest-pinned release; pin and record the accepted image digest for release reproducibility. Docker itself, image vulnerability scanning, registry credentials, resource-limit tuning and load tests were unavailable here. Do not interpret the committed Docker definition as an executed deployment validation.

## Database and indexing recovery

Schema version 3 adds durable index jobs/upload blobs and user memberships; old tables/suite payloads remain unchanged. Historical uploads do not gain original-file blobs retroactively; reingest authorized originals to obtain corrected extraction and provenance. Legacy normalized JSON is excluded from source retrieval/new generation until reingested and reviewed. Startup is additive/idempotent; a database from a newer application version is refused. Take a backup before an upgrade. Do not downgrade an already migrated database without restoring its compatible backup.

Create an online, integrity-checked backup to a **new** destination:

```powershell
uv run python -c "from pathlib import Path; from specprobe.storage.recovery import backup_database; print(backup_database(Path('specprobe.db'),Path('.specprobe/pilot.backup')))"
```

The sidecar `.sha256` records the resulting bytes. Keep backup and sidecar under independent access control; a sidecar beside the backup is not an external trust root. The database includes original upload blobs, extracted evidence, review decisions, approved suite snapshots, users and audit events; encrypt/restrict backup storage accordingly.

For restoration, stop the API, restore to a new database path, independently verify its sidecar hash, set `SPECPROBE_DATABASE_URL=sqlite:///...` to that path, and use a fresh `SPECPROBE_VECTOR_PATH`. Restart and verify `/ready` plus the workspace audit endpoint. Call `POST /workspaces/{id}/documents/{doc}/recover` for every document. This reconstructs Chroma from persisted text using idempotent vector IDs, so copying an inconsistent live Chroma directory is unnecessary. Existing completed jobs can also be rebuilt. Recheck approved-only query results and snapshot/revocation gates before resuming use. A full cold restore with real volumes is still an operator acceptance task.

Uploads commit the source, proposals, original bytes and pending job before vector indexing. Failure leaves a failed/pending/indexing job with an error type and attempt count. Incomplete jobs cannot gain new source approval. Manual recovery is explicit; an automatic background job scheduler and exactly-once multi-worker index execution are not implemented. Parallel retries are idempotent in vector IDs, but job status/attempt count is not a distributed lease.

File-backed SQLite serializes audit writes using a transaction-held mutex update and a busy timeout. Lock contention rolls back and API database failures return 503, enabling transaction retry. Batch field approval is one transaction. SQLite in-memory databases are a test convenience; concurrency claims apply to the file-backed database tests. Arbitrary process-kill, power-loss, disk-full and hostile-administrator scenarios need additional acceptance testing.

## Approved bench adapter acceptance

The generated Python export defaults to `EcuSimulator`. Supply a reviewed implementation of `MessageAdapter` with `is_hardware=True`, measured `receive(timeout_ms)`, bounded ISO-TP message assembly and controlled environment application. Construct `ControlledTransport(..., hardware_enabled=True, approval_reference='<signed bench approval ID>')` only in an explicitly approved bench launcher. The API has no hardware execution endpoint.

Implement safe case preparation and actual idle/session-observation methods for timing suites; unsupported S3 observation produces a configuration failure. Do not infer ECU state from the SpecProbe oracle. Review any service that resets, unlocks security, writes a DID or starts a routine against the bench safety procedure. Independently validate custom data masks, seed/key provider and every setup response. Preserve raw frames, timestamps, adapter/software versions and approval reference as acceptance evidence. No actual CAN messages were transmitted during this upgrade.
