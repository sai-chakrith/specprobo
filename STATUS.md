# Status

The Case Study 5 application workflow is implemented and regression tested for the supported synthetic layouts and typed EcuSpec JSON input.

Implemented:
- PDF, XLSX, JSON and knowledge-reference ingestion with page/sheet/row source evidence.
- Persisted document approval and field approve/edit/reject decisions with hash-chained audit logs.
- Specification assembly from the selected approved upload, with required-field and reference validation; no demo substitution.
- Saved deterministic suite snapshots, complete hexadecimal requests/responses and coverage counts.
- Separate hash-bound suite approval, revocation gates, simulator execution and persisted reports.
- Python automation and JSON export of approved suites, with a transport adaptation seam.
- Request validation and expected/actual response comparison against a saved specification.
- Workspace/knowledge-kind collections in persistent local Chroma; approved-only cited search.
- Optional Ollama explanations, valid-citation enforcement, explicit inference failures, and offline evidence mode.
- Optional local BGE/E5 embeddings; model downloads are separate and opt-in.
- Streamlit upload, source/field/suite review, batch approval, knowledge search, exports, execution and report views.
- Docker API/UI definitions with a persistent data volume and locked application dependencies.

Validation is against the independent simulator and synthetic fixtures. Live local model quality, customer OEM layouts, real ECU behavior/timing, Docker runtime, and enterprise identity infrastructure need environment-specific validation. SocketCAN, native CAPL/CANoe and ODX/CDD adapters are not implemented. Python is the supported automation export target.

The current mutation evaluation retains the documented 2,014-case demo suite, raw score 81.5%, adjusted score 93.9%, 30 equivalent survivors and no genuine gaps under the deterministic sequence classifier. Equivalent means observationally equivalent over that classifier's sequences, not a formal proof.

See README.md for launch commands, the full engineer workflow, model configuration, and practical limits.
