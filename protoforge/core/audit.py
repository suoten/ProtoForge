import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

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
                logger.debug("Failed to persist audit entry: %s", e)

    async def query(self, username: Optional[str] = None,
                    action: Optional[str] = None,
                    resource_type: Optional[str] = None,
                    start_time: Optional[float] = None,
                    end_time: Optional[float] = None,
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
                logger.debug("Audit DB query failed, falling back to memory: %s", e)

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
            "actions": list(set(e.action for e in self._entries)) if self._entries else [],
        }

    async def restore_from_db(self) -> None:
        if not self._database:
            return
        try:
            entries = await self._database.load_audit_entries(limit=1000)
            self._entries = [AuditEntry(**e) for e in entries]
            logger.info("Restored %d audit entries from database", len(self._entries))
        except Exception as e:
            logger.debug("Failed to restore audit entries: %s", e)


audit_logger = AuditLogger()
