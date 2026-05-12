# Changelog

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
