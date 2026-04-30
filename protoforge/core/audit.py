import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    timestamp: float
    action: str
    username: str
    resource_type: str
    resource_id: str
    detail: str = ""
    ip_address: str = ""
    user_agent: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class AuditLogger:
    _MAX_ENTRIES = 50000

    def __init__(self):
        self._entries: list[AuditEntry] = []
        self._database = None

    def set_database(self, database) -> None:
        self._database = database

    async def log(self, action: str, username: str, resource_type: str,
                  resource_id: str = "", detail: str = "",
                  ip_address: str = "", user_agent: str = "") -> None:
        entry = AuditEntry(
            timestamp=time.time(),
            action=action,
            username=username,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._entries.append(entry)
        if len(self._entries) > self._MAX_ENTRIES:
            self._entries = self._entries[-self._MAX_ENTRIES:]
        if self._database:
            try:
                await self._database.save_audit_entry(entry.to_dict())
            except Exception as e:
                logger.warning("Failed to persist audit entry: %s", e)

    async def query(self, username: str | None = None,
                    action: str | None = None,
                    resource_type: str | None = None,
                    start_time: float | None = None,
                    end_time: float | None = None,
                    limit: int = 100,
                    offset: int = 0) -> list[dict]:
        if self._database:
            try:
                entries, _ = await self._database.query_audit_entries(
                    username=username, action=action, resource_type=resource_type,
                    start_time=start_time, end_time=end_time,
                    limit=limit, offset=offset,
                )
                return entries
            except Exception as e:
                logger.warning("Audit DB query failed, falling back to memory: %s", e)

        results = []
        for entry in reversed(self._entries):
            if username and entry.username != username:
                continue
            if action and entry.action != action:
                continue
            if resource_type and entry.resource_type != resource_type:
                continue
            if start_time and entry.timestamp < start_time:
                continue
            if end_time and entry.timestamp > end_time:
                continue
            results.append(entry.to_dict())
            if len(results) >= limit + offset:
                break
        return results[offset:offset + limit]

    async def get_stats(self) -> dict[str, Any]:
        return {
            "total_entries": len(self._entries),
            "actions": list({e.action for e in self._entries}) if self._entries else [],
        }

    async def delete_entry(self, entry_id: int) -> bool:
        if not self._database:
            return False
        try:
            return await self._database.delete_audit_entry(entry_id)
        except Exception as e:
            logger.warning("Failed to delete audit entry %d: %s", entry_id, e)
            return False

    async def clear_entries(self, before_timestamp: float | None = None) -> int:
        if before_timestamp:
            self._entries = [e for e in self._entries if e.timestamp >= before_timestamp]
        else:
            self._entries = []
        if not self._database:
            return 0
        try:
            return await self._database.clear_audit_entries(before_timestamp)
        except Exception as e:
            logger.warning("Failed to clear audit entries: %s", e)
            return 0

    async def restore_from_db(self) -> None:
        if not self._database:
            return
        try:
            entries = await self._database.load_audit_entries(limit=1000)
            self._entries = [AuditEntry(**e) for e in entries]
            logger.info("Restored %d audit entries from database", len(self._entries))
        except Exception as e:
            logger.warning("Failed to restore audit entries: %s", e)


audit_logger = AuditLogger()
