# Changelog

## v1.2.4 — 2026-09-16

**Bug Fix — MQTT 设备启动后外部订阅者（MQTTX 等）收不到数据：**

- 根因：点位 `address` 为单段值（官方 MQTT 模板即如此，如 GPS 模板 `address="latitude"`）时，发布主题被错误地当作**完整 topic** 使用，实际发到 `latitude`、`speed` 等顶层主题，`topic_prefix` 与 `device_id` 层级全部丢失，订阅 `protoforge/gps/#` 的客户端永远收不到数据
- 修复：新主题推导规则 —— address 含 `{device_id}` 占位符 → 替换后使用；address 含 `/`（多级路径）→ 视为显式完整 topic；address 为空或单段 → 走默认层级 `{topic_prefix}/{device_id}/{point.name}`
- 顺带验证：amqtt 0.11.3 `internal_message_broadcast` 内部广播路径本身可达（最小复现脚本确认），排除此前怀疑的 amqtt API 断裂
- 回归脚本 `scripts/diag_mqtt_publish.py`：完整复现用户场景（broker + GPS 设备 + 外部订阅者），修复后订阅 `protoforge/gps/#` 正常收到 `protoforge/gps/latitude` 等消息
- 注意：`topic_prefix` 在该版本起真正生效，使用官方模板创建的 MQTT 设备主题将变为 `{topic_prefix}/{device_id}/{point_name}`（如 `tracker/gps/<设备ID>/latitude`）

## v1.2.3 — 2026-09-15

**Bug Fix — 实时日志页高频流量下浏览器崩溃（含全站 WebSocket 推送排查）：**

- 后端 `/ws/logs` 改为批量下发：一次排干队列积压（最多 200 条/帧），循环内高频日志（多设备被持续轮询）从每秒上千个 WS 帧降为个位数大帧
- 后端 `/ws/devices` 加变化检测：设备列表仅在内容变化时发送，空闲期零重复推送（原实现每 0.1s 全量重发）；协议状态事件批量排干（最多 20 个/帧，帧型 `protocol_status_batch`）
- Dashboard 日志流适配批量帧并改为 200ms 批量刷入（原逐条 unshift 每 500 条触发全量重渲染；且只处理旧 `log` 帧型，批量改造后已失效）
- 前端 Logs 页改为 200ms 定时批量刷入：一次 flush 只触发一次列表重渲染和一次滚动，不再逐条全量重渲染 2000 行导致主线程饱和、内存飙升
- 前端列表改用稳定 key（自增 id），新增日志只追加/裁剪，避免全列表重渲染；搜索过滤改为预拼接搜索串
- 前端重连前先关闭残留 WebSocket，修复多连接叠加导致消息重复、负载倍增
- `LogBus.emit` 跨线程安全：工作线程中的协议服务通过 `call_soon_threadsafe` 投递
- 设备点位写入 API 拒绝 inf/-inf/nan（400），修复 JSON 序列化抛 "Out of range float values" 导致的 500
- 回归脚本 `scripts/diag_log_ws_stress.py`：真实 uvicorn + WebSocket 压测，覆盖跨线程投递、循环内突发（500 条仅 2 帧）、洪峰优雅降级、设备列表变化检测

## v1.2.2 — 2026-09-15

**Bug Fix — 按照说明文档手动部署后登录 401：**

- `protoforge demo` 未设置 `PROTOFORGE_ADMIN_PASSWORD` 时，默认密码改为 `admin`（与说明文档承诺一致）；此前会生成随机密码，导致按说明文档使用 `admin`/`admin` 登录的用户收到 401
- Demo 启动时自动设置 `PROTOFORGE_RESET_ADMIN_PASSWORD=1`，旧数据库（密码为历史随机值）也会同步为 demo 默认密码；显式设置 `PROTOFORGE_RESET_ADMIN_PASSWORD=0` 可关闭
- 非 demo 模式（`protoforge run`）行为不变：未配置时仍生成随机密码并在启动横幅打印，生产环境安全默认不受影响
- 同步修正文档：README.md / README_EN.md / DEPLOYMENT.md（Docker 段密码说明），明确 demo 与生产模式的密码规则

## v1.2.1 — 2026-09-14

**Documentation Enhancement:**

- Added comprehensive Modbus register type mapping section (Coil/Discrete Input/Input Register/Holding Register with function codes)
- Added data type & register usage table (bool/int16/int32/uint32/float32/float64/string/real with byte order)
- Added step-by-step tutorial: creating devices from real address tables (Modbus address table → ProtoForge config → verification code)
- Added Modbus RTU serial port configuration documentation (baudrate/databits/parity/stopbits)
- Added multi-device coexistence documentation (multiple slave_ids on same port)
- Added write behavior documentation (FC05/06/0F/10/16/17 response and read-back behavior)
- Added data generator documentation (fixed/random/sine/increment/ramp with update_frequency parameter)
- Added competitor comparison table (vs Modbus Slave/Poll, Kepware, Node-RED Mock, real PLC)
- Added protocol compliance documentation (standards followed + exception code mapping per protocol)
- Added ARM/Raspberry Pi deployment guide with resource consumption benchmarks
- Added open source vs enterprise feature comparison table
- Updated README_EN.md with all corresponding English documentation

## v1.2.0 — 2026-09-13

**IoT Industrial Device Testing Platform:**

- Added Test Plan Management: versioned test plans with CRUD operations, clone, status filtering (draft/active/archived). Backend: `protoforge/testing/plan.py` (TestPlan/TestRun data models + TestPlanManager). Frontend: `TestPlans.vue` with create/edit/delete/clone/run/history UI.
- Added Test Execution Engine: `protoforge/testing/runner.py` (PlanRunner class) orchestrates protocol/device startup, runs test suites, applies fault scenarios, generates JUnit XML / JSON / HTML reports.
- Added Protocol Compliance Checking: `protoforge/testing/compliance.py` with 5 protocol-specific checkers (Modbus TCP, S7, OPC-UA, IEC 104, MQTT). Each checker has defined rules and violation reporting. Compliance score (percentage) generated per check.
- Added REST API endpoints: `test_plan_routes.py` (CRUD + run + history + report download) and `compliance_routes.py` (protocols list + rules preview + check execution + reports history).
- Added database tables: `test_plans`, `test_runs`, `compliance_reports` with full CRUD in `db/session.py`.
- Added CLI command: `protoforge test run` for CI/CD integration.
- Added frontend pages: `TestPlans.vue` (plan management with modal forms, run result display, report download buttons) and `Compliance.vue` (protocol selector, rules preview, check execution, score display, history tab).
- Added i18n support for all new UI elements (Chinese + English).
- Added Playwright E2E tests: 31 browser tests covering page rendering, CRUD, execution, reports, compliance checking, navigation, error handling, i18n — all passing.

**E2E Test Results (31/31 passed):**

- Test Plans page rendering: title, menu, breadcrumb, create button, empty state ✅
- CRUD operations: create, edit, delete, clone, status filter ✅
- Run & reports: execute plan, view result modal, download JUnit/HTML/JSON, run history ✅
- Compliance page rendering: title, menu, tabs, protocol selector, run check button ✅
- Compliance interactive: select protocol, view rules, run check, view score, history tab ✅
- Error handling: empty name validation, disabled button without protocol, 404 responses ✅
- Navigation: menu navigation, direct URL access ✅
- i18n: Chinese default, English switch ✅

## v1.1.1 — 2026-09-11

**UI/UX fixes (deep testing):**

- Fixed i18n `directionLabels` keys not translating in Debug Logs page — `logs.directionLabels.system` showed as raw key instead of "系统"/"System". Root cause: `directionLabels` object existed in i18n.js but was outside the `logs` namespace. Fix: moved `directionLabels` into `logs` object in both zh and en.
- Fixed NDropdown menus not responding to click — language switcher, user menu, and device "更多" dropdown used default `hover` trigger which was unreliable. Fix: added `trigger="click"` to all NDropdown components in App.vue and Devices.vue for consistent click-to-open behavior.

**Deep testing results (all passed):**

- Dashboard: 7 devices, 4 running protocols, 122 templates, 22 protocol categories ✅
- Device Management: batch start/stop, edit, data points, quick create, CSV import/export ✅
- Protocol Services: 22 protocols with start/stop/configure/detail ✅
- Template Marketplace: 122 templates with category filter and search ✅
- Simulation Testing: single device test passed (100% pass rate, 0.02s), test case editor ✅
- Debug Logs: real-time WebSocket logs, protocol/direction filter, search, export ✅
- Recorder: start/stop recording, recording list with detail/replay/export/delete ✅
- Integration: EdgeLite connection config, per-device push/start-collect/read-points/verify ✅
- Data Forward: add target, start/stop forward ✅
- Webhook: CRUD, test webhook ✅
- Settings: EdgeLite URL, CORS config, save ✅
- Audit Log: search, delete, clear ✅
- Backup & Restore: export backup, restore from file ✅
- Scenario Editor: drag-and-drop canvas, save layout, add device ✅
- i18n: Chinese/English switch works correctly ✅
- Fault Injection API: sensor_drift, sensor_stuck, comm_loss, etc. (9 types) ✅
- CSV Export API: returns valid CSV with all device points ✅

## v1.1.0 — 2026-09-11

**New Protocols (17 → 21):**

- Added IEC 60870-5-104: Power telecontrol protocol (SCADA). Pure Python TCP server with APDU/ASDU parsing, U/S/I-format frames, spontaneous data transmission, command control (single/double/set-point commands). 7 device templates (BMS, CT/PT, microgrid, protection relay, solar plant, substation RTU, transformer).
- Added IEC 61850: Substation automation standard with MMS TCP mapping. BER-encoded PDU parsing, Initiate/Conclude/Read/Write/GetNameList services, Logical Device → Logical Node → Data Object model, CDC types (SPS, MV, SPC, DPC). 3 device templates (bay controller, protection IED, solar IED).
- Added CoAP (RFC 7252): Constrained Application Protocol for low-power IoT. Pure Python UDP server with CON/NON messages, GET/POST/PUT/DELETE, Uri-Path option parsing, Observe (RFC 7641) push, /.well-known/core discovery. 4 device templates (air quality, env sensor, gateway, smart meter).
- Added DDS (Data Distribution Service): OMG standard pub/sub middleware with simplified RTPS wire protocol over TCP/UDP. Topic-based data distribution, subscribe/publish actions, QoS policies. 3 device templates (power grid, robot fleet, wind turbine).
- All 4 new protocols are pure Python — no third-party dependencies required, included in core package.

**Template expansion (90+ → 122):**

- Added 32 new device templates across 4 new protocols (17 templates) and 2 existing protocols (energy meter, PV inverter for Modbus).
- Fixed 6 duplicate template IDs that caused silent template overwriting during loading.
- Total: 122 templates across 21 protocol categories.

**CSV batch import/export:**

- Added `GET /api/v1/devices/export-csv` endpoint — export all devices as CSV with one click.
- Added `POST /api/v1/devices/import-csv` endpoint — batch import devices from CSV content.
- Frontend CSV import/export buttons in Devices page.
- Fixed route conflict: `/devices/export-csv` was incorrectly matched as `/{device_id}` — moved export route before parameterized route.
- Fixed `AttributeError: 'DeviceInfo' object has no attribute 'get'` — export logic now handles both Pydantic models and dicts.

**Recording compression:**

- Recorder `export_compressed` method now uses gzip compression for storage optimization.
- Reduced disk space usage for recorded protocol traces.

**i18n fixes:**

- Fixed i18n key display issue where `devices.importCSV` and `devices.exportCSV` showed as raw keys instead of translated text.
- Added missing i18n keys (`importCSV`, `exportCSV`, `create`, `created`, `csvEmpty`, `csvExported`, `csvExportFailed`, `csvImported`, `csvImportFailed`) in both zh and en.
- Removed incorrectly placed i18n keys from `common` namespace.
- Fixed Vue component `t()` function calls — removed incorrect fallback parameters.

**Documentation:**

- Updated README.md: protocol count 17 → 21, template count 90+ → 122, added new protocols in feature list, protocol table, port table, and architecture diagram.
- Updated version numbers across `pyproject.toml`, `protoforge/__init__.py`, and `web/package.json`.
- Updated keywords in `pyproject.toml` to include new protocols.
- Updated protocol optional-dependencies documentation in `pyproject.toml`.

**OPC-DA:**

- Real protocol implementation improvements (server.py modified).

## v1.0.0 — 2026-08-31

**Architecture refactor (core split):**

- Split the former `protoforge/core` catch-all namespace into four domain packages:
  `protoforge/engine` (simulation engine, devices, registry, event bus),
  `protoforge/simulation` (scenarios, fault injection, behavior models, time series),
  `protoforge/integrations` (EdgeLite, forward, webhook), and
  `protoforge/observability` (log bus, metrics, audit, error monitor). `protoforge/core` now only contains `auth` plus backward-compatible re-exports.
- Updated all 376 internal imports (90 files) to the new layout; ruff per-file-ignores updated accordingly.

**Protocol layer hardening:**

- Fixed silent MQTT data loss with amqtt >= 0.11: `Broker.internal_publish()` was renamed to `internal_message_broadcast()` (without a retain parameter), and the old `hasattr(internal_publish)` guard silently skipped every publish — broker connections worked but subscribers never received data. Added a version-tolerant `_broker_publish()` shim (uses `internal_message_broadcast` + public `retain_message()` on amqtt >= 0.11, falls back to `internal_publish` on older versions) and made a missing broker API log an ERROR plus a protocol-error metric instead of failing silently. Verified end-to-end on amqtt 0.11.3 (real broker + real client subscribe, retain stored).
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
