# Changelog

## v1.0.0 — 2026-08-31

**Architecture refactor (core split):**

- Split the former `protoforge/core` catch-all namespace into four domain packages:
  `protoforge/engine` (simulation engine, devices, registry, event bus),
  `protoforge/simulation` (scenarios, fault injection, behavior models, time series),
  `protoforge/integrations` (EdgeLite, forward, webhook), and
  `protoforge/observability` (log bus, metrics, audit, error monitor). `protoforge/core` now only contains `auth` plus backward-compatible re-exports.
- Updated all 376 internal imports (90 files) to the new layout; ruff per-file-ignores updated accordingly.

**Protocol layer hardening:**

- Fixed Modbus TCP server wrongly rejecting reads on stopped devices: removed the stale `"stop" → 0x04` exception mapping so stopped devices respond with last-known values (matches real PLC behaviour and the EdgeLite collection path); updated outdated adversarial unit tests accordingly.
- Added concurrency contract documentation to `ProtocolServer` base class (event-loop discipline, lifecycle idempotency, connection-handler robustness, write propagation, error reporting).
- Added `ProtocolErrorCategory` enum and `record_protocol_error()` hook; wired all 13 protocol servers' fallback exception handlers to emit `protoforge_protocol_errors_total{protocol, category}` metrics (NETWORK vs INTERNAL), exposed via `/metrics` in Prometheus format.

**CI & contract gating:**

- Removed `|| true` soft-fail from OpenAPI export/validation steps; added an OpenAPI drift gate that fails CI when `openapi.json` is not regenerated after API changes.
- Fixed all remaining ruff findings (bare except, SIM105/SIM108, B027, E402/E722/F841/E712); `ruff check protoforge/ tests/ scripts/` now passes clean.

**Housekeeping & storage:**

- Version aligned to 1.0.0 across `pyproject.toml`, `protoforge.__version__`, and `web/package.json`.
- Root directory cleaned: test outputs, coverage artifacts, screenshots, and OCR experiment files removed; `.gitignore` hardened against re-entry.
- `scripts/` triaged: 68 one-off debug/verification scripts removed; 35 operational tools retained (protocol `diag_*`, acceptance tests, CI-referenced scripts).
- Verified storage is already consolidated on a single SQLite database (`data/protoforge.db`) with Alembic migrations; archived 15 stale integration-test databases (43 files) from `data/` to `data/backups/stale-dbs/`.
- Confirmed `k8s/secrets.yaml` / Helm secrets contain only `CHANGE_ME` placeholders (no real credentials in repo).

## v0.1.7 — 2026-05-10

**Protocol startup port conflict fix:**

- Fixed protocol servers (OPC UA/S7/MC/HTTP) using `asyncio.create_task()` for background startup, where port binding failure still returned 200 OK. Now `start_protocol()` waits 0.3s to check server status, returning 503 if ERROR state detected immediately.
- Added configuration logging during protocol startup for easier port configuration troubleshooting.

**Protocol management UI fix:**

- Fixed missing "Stop All" button on protocol management page. Added `stopAll` function and `stoppingAll` state for one-click stop of all running protocols.

**i18n interpolation fix:**

- Fixed `{n}` not being replaced with actual numbers in confirmation dialogs (e.g., "Will start {n} protocols" showing raw template instead of "Will start 3 protocols"), unified to `{count}` with correct parameter passing.

**Health check fix:**

- Fixed Dashboard health check showing "Database: Operation Failed" / "Engine: Operation Failed", changed to more accurate "Error" label.

**Device recovery fix:**

- Fixed `create_device()` throwing `ValueError` when device already exists during startup recovery, added `allow_update` parameter for recovery scenarios.

## v0.2.0 — 2026-05-11

**P0 Security Fixes:**

- Replaced hardcoded default admin password "admin" with auto-generated random password when `PROTOFORGE_ADMIN_PASSWORD` is not set
- Fixed `_notifyUser()` parameter order error in api.js persistence warning
- Changed no-auth mode identity from admin to anonymous/viewer
- Fixed device point reading to prioritize protocol server data over memory simulation
- Fixed scenario rule actions not propagating to protocol server layer
- Fixed test report restoration from DB losing step details

**P1 Reliability Fixes:**

- Added ProtocolStatusEvent + WebSocket push for real-time protocol status updates
- Unified device creation behavior: all creation methods now auto-start devices
- Fixed ScenarioEditor rule data bidirectional mapping (edge double-click editing)
- Added device re-registration when protocol starts after device creation
- Replaced `dict[str, Any]` with Pydantic models in auth_routes.py
- Changed CORS default from `*` to `localhost:5173,localhost:3000`
- Added logging for silent exception fallbacks in auth.py, failover.py, rate_limit.py
- Added try/except for database connection failures with clear error messages
- Replaced Chinese error message matching in frontend with error_type/error_code matching
- Unified protocol port definitions: edgelite.py and constants.js now read from config
- Removed Chinese error messages from rate_limit.py 429 response
