# Engineering validation status

Readiness: suitable for a **supervised simulator pilot within the supported schema**. Case Study 5's complete validation and engineering-value requirements are not yet demonstrated. No production-readiness or complete ISO 14229 compliance claim is made.

## Stage status

| Priority | Implemented locally | Validation boundary |
|---|---|---|
| 1 Correctness | Scoped DID/routine prose binding; typed numeric/boolean/!= witnesses; isolated conjunct negatives; per-step expected responses; setup/communication/mismatch classification; NRC priority correction | Reproduced failures before fixes; regression and differential checks. OEM condition semantics still need review. |
| 2 Specification validation | Nested references, service/model support, routine controls and complete parameter lengths, units, contradictions, unresolved requirements, data/seed/mask identity and length checks | Reviewed typed input required; no automatic arbitrary OEM interpretation. |
| 3 Extraction | Header aliases, title/repeated-header handling, duplicate/conflict rejection, page/table/sheet/row evidence with merged source references, scanned/ambiguous-layout rejection, field evaluator and frozen candidate documents | Independent human ground truth review is pending. Candidate gridless PDF cannot be extracted; exact missed fields are reported. |
| 4 Protocol | Hand-authored golden/configured/stateful/boundary vectors; independent udsoncan response decoding; session P2 wire-format fix; ECU data/seeds/XOR/identity/masks | Independent parser validates response structure, not actual ECU state machines. No approved bench run. |
| 5 Timing/transport | P2/P2-star deadlines, pending limit, malformed/missing/uncorrelated frames, virtual S3 boundary and missing-expiry fault checks; gated adapter interface | No wall-clock ECU timing measurement, ISO-TP/CAN adapter or hardware run. |
| 6 Local AI | Extractive evidence-support gate, conflict/insufficient-evidence/injection regressions, separate retrieval/model benchmark harness | Ollama/embedding infrastructure unavailable; benchmark NOT_RUN. Semantic groundedness unmeasured. |
| 7 Recovery | Durable upload bytes/index jobs, idempotent retry after restart, atomic batch approval, serialized audit writes, schema-version guard, online SQLite backup and restore tests | SQLite only. Tested interruptions/contended writes do not establish arbitrary power-loss durability or tamper resistance against an administrator. |
| 8 Access/deployment | Individual hashed tokens, workspace viewer/editor/reviewer permissions, authenticated review actor, administrator provisioning/revocation/rotation, health/readiness, locked Docker definition/non-root/file secrets | No Docker executable/daemon on host; no enterprise IAM/TLS/rate-limit or load-test validation. |
| 9 Engineering value | Supervised counterbalanced pilot protocol, observation template and validated aggregation tool | Pilot NOT_RUN; no measured time savings, acceptance rate or confirmed ECU defects. |

Preserved: upload/review/generate/approve/simulator-run/export workflow, persistent source retrieval and saved suite snapshots. Old suite snapshots remain stored, but revision 2 requires regeneration/review before running/exporting.

Evidence and exact reproduction commands are in [docs/VALIDATION.md](docs/VALIDATION.md). External acceptance steps are in [docs/OPERATIONS.md](docs/OPERATIONS.md) and [docs/PILOT.md](docs/PILOT.md).
