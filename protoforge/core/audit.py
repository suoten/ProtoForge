import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    id: int = 0
    timestamp: float = 0.0
    action: str = ""
    username: str = ""
    resource_type: str = ""
    resource_id: str = ""
    detail: str = ""
    ip_address: str = ""
    user_agent: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class AuditLogger:
    _MAX_ENTRIES = None

    @classmethod
    def _get_max_entries(cls) -> int:
        if cls._MAX_ENTRIES is None:
            try:
                from protoforge.config import get_settings
                cls._MAX_ENTRIES = get_settings().audit_max_entries
            except Exception as e:
                logger.debug("Failed to read audit_max_entries from config, using default: %s", e)
                cls._MAX_ENTRIES = 50000
        return cls._MAX_ENTRIES

    def __init__(self):
        self._entries: list[AuditEntry] = []
        self._database = None
        self._next_id = 1

    def set_database(self, database) -> None:
        self._database = database

    async def log(self, action: str, username: str, resource_type: str,
                  resource_id: str = "", detail: str = "",
                  ip_address: str = "", user_agent: str = "") -> None:
        entry = AuditEntry(
            id=self._next_id,
            timestamp=time.time(),
            action=action,
            username=username,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._next_id += 1
        self._entries.append(entry)
        if len(self._entries) > self._get_max_entries():
            self._entries = self._entries[-self._get_max_entries():]
        if self._database:
            try:
                await self._database.save_audit_entry(entry.to_dict())
            except Exception as e:
                logger.warning("Failed to persist audit entry: %s", e)

    async def query(self, username: Optional[str] = None,
                    action: Optional[str] = None,
                    resource_type: Optional[str] = None,
                    start_time: Optional[float] = None,
                    end_time: Optional[float] = None,
                    limit: int = 100,
                    offset: int = 0) -> tuple[list[dict], int]:
        if self._database:
            try:
                entries, total = await self._database.query_audit_entries(
                    username=username, action=action, resource_type=resource_type,
                    start_time=start_time, end_time=end_time,
                    limit=limit, offset=offset,
                )
                return entries, total
            except Exception as e:
                logger.warning("Audit DB query failed, falling back to memory: %s", e)

        results = []
        action_aliases = _get_action_aliases(action) if action else None
        for entry in reversed(self._entries):
            if username and entry.username != username:
                continue
            if action and not any(a in entry.action for a in action_aliases):
                continue
            if resource_type and entry.resource_type != resource_type:
                continue
            if start_time and entry.timestamp < start_time:
                continue
            if end_time and entry.timestamp > end_time:
                continue
            d = entry.to_dict()
            d["action"] = _normalize_action(d["action"])
            results.append(d)
        total = len(results)
        return results[offset:offset + limit], total

    async def get_stats(self) -> dict[str, Any]:
        now = time.time()
        today_start = now - (now % 86400)
        today_count = sum(1 for e in self._entries if e.timestamp >= today_start)
        active_users = list(set(e.username for e in self._entries)) if self._entries else []
        last_action = _normalize_action(self._entries[-1].action) if self._entries else ""
        last_timestamp = self._entries[-1].timestamp if self._entries else 0
        # 优先从数据库获取真实总数，避免内存条目不完整导致统计不准确
        total_entries = len(self._entries)
        if self._database:
            try:
                _, db_total = await self._database.query_audit_entries(limit=1, offset=0)
                total_entries = db_total
            except Exception:
                pass
        return {
            "total_entries": total_entries,
            "today_count": today_count,
            "active_users": active_users,
            "last_action": last_action,
            "last_timestamp": last_timestamp,
            "actions": list(set(_normalize_action(e.action) for e in self._entries)) if self._entries else [],
        }

    async def delete_entry(self, entry_id: int) -> bool:
        self._entries = [e for e in self._entries if e.id != entry_id]
        if not self._database:
            return True
        try:
            return await self._database.delete_audit_entry(entry_id)
        except Exception as e:
            logger.warning("Failed to delete audit entry %d: %s", entry_id, e)
            return False

    async def clear_entries(self, before_timestamp: Optional[float] = None) -> int:
        if before_timestamp:
            original_count = len(self._entries)
            self._entries = [e for e in self._entries if e.timestamp >= before_timestamp]
            cleared = original_count - len(self._entries)
        else:
            cleared = len(self._entries)
            self._entries = []
        if not self._database:
            return cleared
        try:
            return await self._database.clear_audit_entries(before_timestamp)
        except Exception as e:
            logger.warning("Failed to clear audit entries: %s", e)
            return cleared

    async def restore_from_db(self) -> None:
        if not self._database:
            return
        try:
            entries = await self._database.load_audit_entries(limit=1000)
            restored = []
            for e in entries:
                try:
                    restored.append(AuditEntry(**e))
                except Exception as entry_err:
                    logger.debug("Skipping invalid audit entry: %s", entry_err)
            existing_ids = {e.id for e in self._entries}
            for entry in restored:
                if entry.id not in existing_ids:
                    self._entries.append(entry)
            logger.info("Restored %d audit entries from database (total: %d)", len(restored), len(self._entries))
        except Exception as e:
            logger.warning("Failed to restore audit entries: %s", e)


audit_logger = AuditLogger()


# key: 规范action名, value: 可能的旧格式变体列表
_ACTION_ALIASES = {
    "run_test": ["run_test", "post_tests", "tests_quick-test", "tests_run"],
    "create_device": ["create_device", "post_devices", "devices_quick-create", "devices_batch-create"],
    "delete_device": ["delete_device", "delete_devices", "devices_batch-delete"],
    "update_device": ["update_device", "put_devices"],
    "start_protocol": ["start_protocol", "post_protocols", "protocols_start-all"],
    "stop_protocol": ["stop_protocol", "delete_protocols", "protocols_stop-all"],
    "create_scenario": ["create_scenario", "post_scenarios"],
    "delete_scenario": ["delete_scenario", "delete_scenarios"],
    "update_scenario": ["update_scenario", "put_scenarios"],
    "create_template": ["create_template", "post_templates"],
    "delete_template": ["delete_template", "delete_templates"],
    "update_template": ["update_template", "put_templates"],
    "login": ["login", "auth_login"],
    "register": ["register", "auth_register"],
    "change_password": ["change_password", "auth_change-password"],
    "delete_user": ["delete_user", "delete_users"],
    "update_user_role": ["update_user_role", "put_users"],
    "import_backup": ["import_backup", "post_backup"],
    "create_webhook": ["create_webhook", "post_webhooks"],
    "delete_webhook": ["delete_webhook", "delete_webhooks"],
    "update_webhook": ["update_webhook", "put_webhooks"],
    "create_forward": ["create_forward", "post_forward"],
    "delete_forward": ["delete_forward", "delete_forward"],
    "update_forward": ["update_forward", "put_forward"],
    "update_settings": ["update_settings", "put_settings"],
    "start_recording": ["start_recording", "post_recorder"],
    "stop_recording": ["stop_recording", "delete_recorder"],
}


def _get_action_aliases(action: str) -> list[str]:
    """Get all possible action string variants for a given canonical action name.

    Used for search/filter to match both new canonical names and old raw format names.
    """
    aliases = _ACTION_ALIASES.get(action, [action])
    # Always include the canonical name itself
    if action not in aliases:
        aliases.append(action)
    return aliases


def _normalize_action(action: str) -> str:
    """Normalize raw action names (e.g. post_protocols_profinet_start) to canonical names (e.g. start_protocol).

    Used when returning data to frontend so i18n can find the correct translation key.
    """
    if not action:
        return action
    # 1. Exact match in _ACTION_ALIASES keys
    if action in _ACTION_ALIASES:
        return action
    # 2. Check if action matches any alias
    for canonical, aliases in _ACTION_ALIASES.items():
        if action in aliases:
            return canonical
    # 3. Substring match: e.g. "post_protocols_profinet_start" contains "post_protocols"
    for canonical, aliases in _ACTION_ALIASES.items():
        for alias in aliases:
            if alias and alias in action:
                return canonical
    return action


# Action mapping: HTTP method + path pattern -> audit action + resource_type
_AUDIT_ACTION_MAP = [
    # Devices - specific paths first (longer path = higher priority)
    ("POST", "/devices/quick-create", "create_device", "device"),
    ("POST", "/devices/batch-create", "create_device", "device"),
    ("DELETE", "/devices/batch-delete", "delete_device", "device"),
    ("POST", "/devices", "create_device", "device"),
    ("DELETE", "/devices", "delete_device", "device"),
    ("PUT", "/devices", "update_device", "device"),
    # Scenarios
    ("POST", "/scenarios", "create_scenario", "scenario"),
    ("DELETE", "/scenarios", "delete_scenario", "scenario"),
    ("PUT", "/scenarios", "update_scenario", "scenario"),
    # Templates
    ("POST", "/templates", "create_template", "template"),
    ("DELETE", "/templates", "delete_template", "template"),
    ("PUT", "/templates", "update_template", "template"),
    # Protocols - specific paths first
    ("POST", "/protocols/start-all", "start_protocol", "protocol"),
    ("POST", "/protocols/stop-all", "stop_protocol", "protocol"),
    ("POST", "/protocols", "start_protocol", "protocol"),
    ("DELETE", "/protocols", "stop_protocol", "protocol"),
    # Tests - specific paths first
    ("POST", "/tests/quick-test", "run_test", "test"),
    ("POST", "/tests/run", "run_test", "test"),
    ("POST", "/tests", "run_test", "test"),
    # Auth
    ("POST", "/auth/login", "login", "auth"),
    ("POST", "/auth/register", "register", "auth"),
    ("POST", "/auth/change-password", "change_password", "auth"),
    ("DELETE", "/users", "delete_user", "auth"),
    ("PUT", "/users", "update_user_role", "auth"),
    # System
    ("POST", "/backup", "import_backup", "system"),
    ("PUT", "/settings", "update_settings", "system"),
    ("POST", "/recorder", "start_recording", "system"),
    ("DELETE", "/recorder", "stop_recording", "system"),
    # Webhooks
    ("POST", "/webhooks", "create_webhook", "webhook"),
    ("DELETE", "/webhooks", "delete_webhook", "webhook"),
    ("PUT", "/webhooks", "update_webhook", "webhook"),
    # Forward
    ("POST", "/forward", "create_forward", "forward"),
    ("DELETE", "/forward", "delete_forward", "forward"),
    ("PUT", "/forward", "update_forward", "forward"),
]

# Paths to skip entirely
_AUDIT_SKIP_PATHS = {
    "/health", "/api/v1/health", "/metrics", "/api/v1/metrics",
    "/docs", "/openapi.json", "/redoc",
}


async def audit_middleware(request, call_next):
    """FastAPI HTTP middleware that automatically logs audit entries for mutating operations."""
    path = request.url.path

    # Skip non-API paths and health/metrics
    if path in _AUDIT_SKIP_PATHS or not path.startswith("/api/v1/"):
        return await call_next(request)

    # Only audit mutating methods
    method = request.method.upper()
    if method not in ("POST", "PUT", "PATCH", "DELETE"):
        return await call_next(request)

    # Execute the request first
    response = await call_next(request)

    # Only log successful operations (2xx status)
    if response.status_code < 200 or response.status_code >= 300:
        return response

    # Match action from path
    action = ""
    resource_type = ""
    resource_id = ""

    # Strip /api/v1 prefix for matching
    api_path = path[len("/api/v1/"):] if path.startswith("/api/v1/") else path

    for m, p, act, rtype in _AUDIT_ACTION_MAP:
        if method == m and api_path.startswith(p):
            action = act
            resource_type = rtype
            # Extract resource ID from path (e.g., /devices/abc123 -> abc123)
            remainder = api_path[len(p):]
            if remainder:
                resource_id = remainder.strip("/").split("/")[0]
            break

    if not action:
        # Generic action for unmatched mutating operations
        action = f"{method.lower()}_{api_path.replace('/', '_').strip('_')}"
        resource_type = "system"

    # Get username from request state (set by auth middleware)
    username = ""
    try:
        user = getattr(request.state, "user", None)
        if user and isinstance(user, dict):
            username = user.get("username", "")
        elif user and hasattr(user, "username"):
            username = user.username
    except Exception:
        pass

    if not username:
        username = "anonymous"

    # Get client IP
    ip_address = request.client.host if request.client else ""

    # Build detail string
    detail = f"{method} {path}"
    if resource_id:
        detail += f" id={resource_id}"

    # Log the audit entry (fire and forget, don't block response)
    try:
        await audit_logger.log(
            action=action,
            username=username,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
            ip_address=ip_address,
        )
    except Exception as e:
        logger.debug("Failed to write audit log: %s", e)

    return response
