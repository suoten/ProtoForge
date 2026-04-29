import json
import logging
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import aiosqlite

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.models.scenario import Rule, ScenarioConfig
from protoforge.models.template import TemplateDetail

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "protoforge.db"


class Database:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(_DEFAULT_DB_PATH)
        self._db: Optional[aiosqlite.Connection] = None
        self._is_postgres = False
        self._pg_pool = None

    def _is_postgresql_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in ("postgresql", "postgres", "postgresql+asyncpg")

    async def connect(self) -> None:
        if self._is_postgresql_url(self._db_path):
            await self._connect_postgres()
        else:
            await self._connect_sqlite()

    async def _connect_sqlite(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._create_tables_sqlite()
        logger.info("SQLite database connected: %s", self._db_path)

    async def _connect_postgres(self) -> None:
        try:
            import asyncpg
        except ImportError:
            raise RuntimeError(
                "PostgreSQL support requires asyncpg. Install it with: pip install asyncpg"
            )
        self._pg_pool = await asyncpg.create_pool(self._db_path, min_size=2, max_size=10, autocommit=True)
        self._is_postgres = True
        async with self._pg_pool.acquire() as conn:
            await self._create_tables_postgres(conn)
        logger.info("PostgreSQL database connected")

    async def close(self) -> None:
        if self._is_postgres and self._pg_pool:
            await self._pg_pool.close()
            self._pg_pool = None
        elif self._db:
            await self._db.close()
            self._db = None

    async def _create_tables_sqlite(self) -> None:
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                protocol TEXT NOT NULL,
                template_id TEXT,
                points TEXT NOT NULL DEFAULT '[]',
                protocol_config TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_devices_protocol ON devices(protocol);

            CREATE TABLE IF NOT EXISTS scenarios (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                devices TEXT NOT NULL DEFAULT '[]',
                rules TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                protocol TEXT NOT NULL,
                description TEXT DEFAULT '',
                manufacturer TEXT DEFAULT '',
                model TEXT DEFAULT '',
                points TEXT NOT NULL DEFAULT '[]',
                protocol_config TEXT NOT NULL DEFAULT '{}',
                tags TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_templates_protocol ON templates(protocol);

            CREATE TABLE IF NOT EXISTS test_cases (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                steps TEXT NOT NULL DEFAULT '[]',
                setup_steps TEXT NOT NULL DEFAULT '[]',
                teardown_steps TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS test_suites (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                test_case_ids TEXT NOT NULL DEFAULT '[]',
                tags TEXT NOT NULL DEFAULT '[]',
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS test_reports (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                start_time REAL DEFAULT 0,
                end_time REAL DEFAULT 0,
                total INTEGER DEFAULT 0,
                passed INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                skipped INTEGER DEFAULT 0,
                environment TEXT NOT NULL DEFAULT '{}',
                test_cases TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                id TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at REAL DEFAULT 0,
                login_attempts INTEGER DEFAULT 0,
                locked_until REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                action TEXT NOT NULL,
                username TEXT NOT NULL,
                resource_type TEXT NOT NULL DEFAULT '',
                resource_id TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                ip_address TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_username ON audit_log(username);
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);

            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                protocol TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL DEFAULT 0,
                messages TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_recordings_protocol ON recordings(protocol);
        """)
        await self._db.commit()

    async def _create_tables_postgres(self, conn) -> None:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                protocol TEXT NOT NULL,
                template_id TEXT,
                points TEXT NOT NULL DEFAULT '[]',
                protocol_config TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_protocol ON devices(protocol)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS scenarios (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                devices TEXT NOT NULL DEFAULT '[]',
                rules TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                protocol TEXT NOT NULL,
                description TEXT DEFAULT '',
                manufacturer TEXT DEFAULT '',
                model TEXT DEFAULT '',
                points TEXT NOT NULL DEFAULT '[]',
                protocol_config TEXT NOT NULL DEFAULT '{}',
                tags TEXT NOT NULL DEFAULT '[]'
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_templates_protocol ON templates(protocol)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS test_cases (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                steps TEXT NOT NULL DEFAULT '[]',
                setup_steps TEXT NOT NULL DEFAULT '[]',
                teardown_steps TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS test_suites (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                test_case_ids TEXT NOT NULL DEFAULT '[]',
                tags TEXT NOT NULL DEFAULT '[]',
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS test_reports (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                start_time REAL DEFAULT 0,
                end_time REAL DEFAULT 0,
                total INTEGER DEFAULT 0,
                passed INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                skipped INTEGER DEFAULT 0,
                environment TEXT NOT NULL DEFAULT '{}',
                test_cases TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                id TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at REAL DEFAULT 0,
                login_attempts INTEGER DEFAULT 0,
                locked_until REAL DEFAULT 0
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                timestamp REAL NOT NULL,
                action TEXT NOT NULL,
                username TEXT NOT NULL,
                resource_type TEXT NOT NULL DEFAULT '',
                resource_id TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                ip_address TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT ''
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_username ON audit_log(username)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                protocol TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL DEFAULT 0,
                messages TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}'
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_protocol ON recordings(protocol)")

    async def _execute(self, sql: str, params: tuple = ()) -> None:
        if self._is_postgres:
            async with self._pg_pool.acquire() as conn:
                await conn.execute(sql, *params)
        else:
            await self._db.execute(sql, params)
            await self._db.commit()

    async def _fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        if self._is_postgres:
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(sql, *params)
                return dict(row) if row else None
        else:
            async with self._db.execute(sql, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        if self._is_postgres:
            async with self._pg_pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
                return [dict(r) for r in rows]
        else:
            async with self._db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    def _upsert_sql(self, table: str, columns: list[str], conflict_key: str = "id") -> str:
        cols = ", ".join(columns)
        placeholders_pg = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
        placeholders_sqlite = ", ".join("?" for _ in columns)
        update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != conflict_key)

        pg_sql = (
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders_pg})"
            f" ON CONFLICT ({conflict_key}) DO UPDATE SET {update_set}"
        )
        sqlite_sql = (
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders_sqlite})"
            f" ON CONFLICT ({conflict_key}) DO UPDATE SET {update_set}"
        )
        if self._is_postgres:
            return pg_sql
        return sqlite_sql

    def _where_sql(self, column: str) -> str:
        return f"{column} = $1" if self._is_postgres else f"{column} = ?"

    async def save_device(self, config: DeviceConfig) -> None:
        points_json = json.dumps([p.model_dump() for p in config.points])
        config_json = json.dumps(config.protocol_config)
        sql = self._upsert_sql("devices", ["id", "name", "protocol", "template_id", "points", "protocol_config"])
        await self._execute(
            sql,
            (config.id, config.name, config.protocol, config.template_id, points_json, config_json),
        )

    async def load_device(self, device_id: str) -> Optional[DeviceConfig]:
        row = await self._fetchone(
            f"SELECT * FROM devices WHERE {self._where_sql('id')}",
            (device_id,),
        )
        if not row:
            return None
        return self._row_to_device(row)

    async def load_all_devices(self) -> list[DeviceConfig]:
        rows = await self._fetchall("SELECT * FROM devices")
        return [self._row_to_device(row) for row in rows]

    async def delete_device(self, device_id: str) -> None:
        await self._execute(
            f"DELETE FROM devices WHERE {self._where_sql('id')}",
            (device_id,),
        )

    async def save_scenario(self, config: ScenarioConfig) -> None:
        devices_json = json.dumps([d.model_dump() for d in config.devices])
        rules_json = json.dumps([r.model_dump() for r in config.rules])
        sql = self._upsert_sql("scenarios", ["id", "name", "description", "devices", "rules"])
        await self._execute(
            sql,
            (config.id, config.name, config.description, devices_json, rules_json),
        )

    async def load_scenario(self, scenario_id: str) -> Optional[ScenarioConfig]:
        row = await self._fetchone(
            f"SELECT * FROM scenarios WHERE {self._where_sql('id')}",
            (scenario_id,),
        )
        if not row:
            return None
        return self._row_to_scenario(row)

    async def load_all_scenarios(self) -> list[ScenarioConfig]:
        rows = await self._fetchall("SELECT * FROM scenarios")
        return [self._row_to_scenario(row) for row in rows]

    async def delete_scenario(self, scenario_id: str) -> None:
        await self._execute(
            f"DELETE FROM scenarios WHERE {self._where_sql('id')}",
            (scenario_id,),
        )

    async def save_template(self, template: TemplateDetail) -> None:
        points_json = json.dumps([p.model_dump() for p in template.points])
        config_json = json.dumps(template.protocol_config)
        tags_json = json.dumps(template.tags)
        sql = self._upsert_sql("templates", ["id", "name", "protocol", "description", "manufacturer", "model", "points", "protocol_config", "tags"])
        await self._execute(
            sql,
            (template.id, template.name, template.protocol, template.description,
             template.manufacturer, template.model, points_json, config_json, tags_json),
        )

    async def load_all_templates(self) -> list[TemplateDetail]:
        rows = await self._fetchall("SELECT * FROM templates")
        return [self._row_to_template(row) for row in rows]

    async def load_template(self, template_id: str) -> Optional[TemplateDetail]:
        row = await self._fetchone(
            f"SELECT * FROM templates WHERE {self._where_sql('id')}",
            (template_id,),
        )
        if not row:
            return None
        return self._row_to_template(row)

    async def delete_template(self, template_id: str) -> None:
        await self._execute(
            f"DELETE FROM templates WHERE {self._where_sql('id')}",
            (template_id,),
        )

    def _row_to_device(self, row: dict) -> DeviceConfig:
        points = [PointConfig(**p) for p in json.loads(row["points"])]
        return DeviceConfig(
            id=row["id"],
            name=row["name"],
            protocol=row["protocol"],
            template_id=row.get("template_id"),
            points=points,
            protocol_config=json.loads(row["protocol_config"]),
        )

    def _row_to_scenario(self, row: dict) -> ScenarioConfig:
        devices = [DeviceConfig(**d) for d in json.loads(row["devices"])]
        rules = [Rule(**r) for r in json.loads(row["rules"])]
        return ScenarioConfig(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            devices=devices,
            rules=rules,
        )

    def _row_to_template(self, row: dict) -> TemplateDetail:
        points = [PointConfig(**p) for p in json.loads(row["points"])]
        return TemplateDetail(
            id=row["id"],
            name=row["name"],
            protocol=row["protocol"],
            description=row["description"],
            manufacturer=row["manufacturer"],
            model=row["model"],
            points=points,
            protocol_config=json.loads(row["protocol_config"]),
            tags=json.loads(row["tags"]),
        )

    async def save_test_case(self, case_data: dict[str, Any]) -> None:
        sql = self._upsert_sql("test_cases", ["id", "name", "description", "tags", "steps", "setup_steps", "teardown_steps"])
        await self._execute(
            sql,
            (case_data["id"], case_data.get("name", ""), case_data.get("description", ""),
             json.dumps(case_data.get("tags", [])), json.dumps(case_data.get("steps", [])),
             json.dumps(case_data.get("setup_steps", [])), json.dumps(case_data.get("teardown_steps", []))),
        )

    async def load_test_case(self, case_id: str) -> Optional[dict[str, Any]]:
        row = await self._fetchone(
            f"SELECT * FROM test_cases WHERE {self._where_sql('id')}",
            (case_id,),
        )
        if not row:
            return None
        return {
            "id": row["id"], "name": row["name"], "description": row["description"],
            "tags": json.loads(row["tags"]), "steps": json.loads(row["steps"]),
            "setup_steps": json.loads(row["setup_steps"]),
            "teardown_steps": json.loads(row["teardown_steps"]),
        }

    async def load_all_test_cases(self) -> list[dict[str, Any]]:
        rows = await self._fetchall("SELECT * FROM test_cases")
        return [{
            "id": r["id"], "name": r["name"], "description": r["description"],
            "tags": json.loads(r["tags"]), "steps": json.loads(r["steps"]),
            "setup_steps": json.loads(r["setup_steps"]),
            "teardown_steps": json.loads(r["teardown_steps"]),
        } for r in rows]

    async def delete_test_case(self, case_id: str) -> None:
        await self._execute(
            f"DELETE FROM test_cases WHERE {self._where_sql('id')}",
            (case_id,),
        )

    async def save_test_suite(self, suite_data: dict[str, Any]) -> None:
        sql = self._upsert_sql("test_suites", ["id", "name", "description", "test_case_ids", "tags", "created_at", "updated_at"])
        await self._execute(
            sql,
            (suite_data["id"], suite_data.get("name", ""), suite_data.get("description", ""),
             json.dumps(suite_data.get("test_case_ids", [])), json.dumps(suite_data.get("tags", [])),
             suite_data.get("created_at", 0), suite_data.get("updated_at", 0)),
        )

    async def load_all_test_suites(self) -> list[dict[str, Any]]:
        rows = await self._fetchall("SELECT * FROM test_suites")
        return [{
            "id": r["id"], "name": r["name"], "description": r["description"],
            "test_case_ids": json.loads(r["test_case_ids"]), "tags": json.loads(r["tags"]),
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        } for r in rows]

    async def delete_test_suite(self, suite_id: str) -> None:
        await self._execute(
            f"DELETE FROM test_suites WHERE {self._where_sql('id')}",
            (suite_id,),
        )

    async def load_test_suite(self, suite_id: str) -> Optional[dict[str, Any]]:
        row = await self._fetchone(
            f"SELECT * FROM test_suites WHERE {self._where_sql('id')}",
            (suite_id,),
        )
        if not row:
            return None
        return {
            "id": row["id"], "name": row["name"], "description": row["description"],
            "test_case_ids": json.loads(row["test_case_ids"]), "tags": json.loads(row["tags"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    async def save_test_report(self, report_data: dict[str, Any]) -> None:
        sql = self._upsert_sql("test_reports", ["id", "name", "start_time", "end_time", "total", "passed", "failed", "errors", "skipped", "environment", "test_cases"])
        await self._execute(
            sql,
            (report_data["id"], report_data.get("name", ""),
             report_data.get("start_time", 0), report_data.get("end_time", 0),
             report_data.get("total", 0), report_data.get("passed", 0),
             report_data.get("failed", 0), report_data.get("errors", 0),
             report_data.get("skipped", 0),
             json.dumps(report_data.get("environment", {})),
             json.dumps(report_data.get("test_cases", []))),
        )

    async def load_test_reports(self, count: int = 50) -> list[dict[str, Any]]:
        limit_clause = f"LIMIT ${1}" if self._is_postgres else "LIMIT ?"
        rows = await self._fetchall(
            f"SELECT * FROM test_reports ORDER BY created_at DESC {limit_clause}",
            (count,),
        )
        return [{
            "id": r["id"], "name": r["name"],
            "start_time": r["start_time"], "end_time": r["end_time"],
            "total": r["total"], "passed": r["passed"], "failed": r["failed"],
            "errors": r["errors"], "skipped": r["skipped"],
            "environment": json.loads(r["environment"]),
            "test_cases": json.loads(r["test_cases"]),
        } for r in rows]

    async def delete_test_report(self, report_id: str) -> None:
        await self._execute(
            f"DELETE FROM test_reports WHERE {self._where_sql('id')}",
            (report_id,),
        )

    async def load_test_report(self, report_id: str) -> Optional[dict[str, Any]]:
        row = await self._fetchone(
            f"SELECT * FROM test_reports WHERE {self._where_sql('id')}",
            (report_id,),
        )
        if not row:
            return None
        return {
            "id": row["id"], "name": row["name"],
            "start_time": row["start_time"], "end_time": row["end_time"],
            "total": row["total"], "passed": row["passed"], "failed": row["failed"],
            "errors": row["errors"], "skipped": row["skipped"],
            "environment": json.loads(row["environment"]),
            "test_cases": json.loads(row["test_cases"]),
        }

    async def save_user(self, user_data: dict[str, Any]) -> None:
        sql = self._upsert_sql("users", ["username", "id", "password_hash", "role", "created_at", "login_attempts", "locked_until"], conflict_key="username")
        await self._execute(
            sql,
            (user_data["username"], user_data["id"], user_data["password_hash"],
             user_data.get("role", "user"), user_data.get("created_at", 0),
             user_data.get("login_attempts", 0), user_data.get("locked_until", 0.0)),
        )

    async def load_all_users(self) -> list[dict[str, Any]]:
        rows = await self._fetchall("SELECT * FROM users")
        return [{
            "id": r["id"], "username": r["username"],
            "password_hash": r["password_hash"], "role": r["role"],
            "created_at": r["created_at"],
            "login_attempts": r["login_attempts"],
            "locked_until": r["locked_until"],
        } for r in rows]

    async def load_user(self, username: str) -> Optional[dict[str, Any]]:
        row = await self._fetchone(
            f"SELECT * FROM users WHERE {self._where_sql('username')}",
            (username,),
        )
        if not row:
            return None
        return {
            "id": row["id"], "username": row["username"],
            "password_hash": row["password_hash"], "role": row["role"],
            "created_at": row["created_at"],
            "login_attempts": row["login_attempts"],
            "locked_until": row["locked_until"],
        }

    async def delete_user(self, username: str) -> None:
        await self._execute(
            f"DELETE FROM users WHERE {self._where_sql('username')}",
            (username,),
        )

    async def save_audit_entry(self, entry: dict[str, Any]) -> None:
        if self._is_postgres:
            sql = "INSERT INTO audit_log (timestamp, action, username, resource_type, resource_id, detail, ip_address, user_agent) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)"
        else:
            sql = "INSERT INTO audit_log (timestamp, action, username, resource_type, resource_id, detail, ip_address, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        await self._execute(
            sql,
            (entry["timestamp"], entry["action"], entry["username"],
             entry.get("resource_type", ""), entry.get("resource_id", ""),
             entry.get("detail", ""), entry.get("ip_address", ""),
             entry.get("user_agent", "")),
        )

    async def query_audit_entries(
        self,
        username: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions = []
        params: list[Any] = []
        idx = 1

        if username:
            conditions.append(f"username = ${idx}" if self._is_postgres else "username = ?")
            params.append(username)
            idx += 1
        if action:
            conditions.append(f"action = ${idx}" if self._is_postgres else "action = ?")
            params.append(action)
            idx += 1
        if resource_type:
            conditions.append(f"resource_type = ${idx}" if self._is_postgres else "resource_type = ?")
            params.append(resource_type)
            idx += 1
        if start_time is not None:
            conditions.append(f"timestamp >= ${idx}" if self._is_postgres else "timestamp >= ?")
            params.append(start_time)
            idx += 1
        if end_time is not None:
            conditions.append(f"timestamp <= ${idx}" if self._is_postgres else "timestamp <= ?")
            params.append(end_time)
            idx += 1

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        limit_clause = f"LIMIT ${idx}" if self._is_postgres else "LIMIT ?"
        offset_clause = f"OFFSET ${idx + 1}" if self._is_postgres else "OFFSET ?"
        params.extend([limit, offset])

        rows = await self._fetchall(
            f"SELECT timestamp, action, username, resource_type, resource_id, detail, ip_address, user_agent "
            f"FROM audit_log {where_clause} ORDER BY timestamp DESC {limit_clause} {offset_clause}",
            tuple(params),
        )
        entries = [{
            "timestamp": r["timestamp"], "action": r["action"],
            "username": r["username"], "resource_type": r["resource_type"],
            "resource_id": r["resource_id"], "detail": r["detail"],
            "ip_address": r["ip_address"], "user_agent": r["user_agent"],
        } for r in rows]

        count_params = params[:-2]
        count_rows = await self._fetchall(
            f"SELECT COUNT(*) as cnt FROM audit_log {where_clause}",
            tuple(count_params) if count_params else (),
        )
        total = count_rows[0]["cnt"] if count_rows else 0

        return entries, total

    async def load_audit_entries(self, limit: int = 1000) -> list[dict[str, Any]]:
        limit_clause = f"LIMIT ${1}" if self._is_postgres else "LIMIT ?"
        rows = await self._fetchall(
            f"SELECT timestamp, action, username, resource_type, resource_id, detail, ip_address, user_agent FROM audit_log ORDER BY timestamp DESC {limit_clause}",
            (limit,),
        )
        return [{
            "timestamp": r["timestamp"], "action": r["action"],
            "username": r["username"], "resource_type": r["resource_type"],
            "resource_id": r["resource_id"], "detail": r["detail"],
            "ip_address": r["ip_address"], "user_agent": r["user_agent"],
        } for r in rows]

    async def delete_audit_entry(self, entry_id: int) -> bool:
        if self._is_postgres:
            result = await self._fetchone(
                "DELETE FROM audit_log WHERE id = $1 RETURNING id",
                (entry_id,),
            )
        else:
            cursor = await self._db.execute(
                "DELETE FROM audit_log WHERE id = ?", (entry_id,)
            )
            await self._db.commit()
            return cursor.rowcount > 0
        return result is not None

    async def clear_audit_entries(self, before_timestamp: Optional[float] = None) -> int:
        if before_timestamp is not None:
            if self._is_postgres:
                count_result = await self._fetchone(
                    "SELECT COUNT(*) as cnt FROM audit_log WHERE timestamp < $1",
                    (before_timestamp,),
                )
                count = count_result["cnt"] if count_result else 0
                await self._execute(
                    "DELETE FROM audit_log WHERE timestamp < $1",
                    (before_timestamp,),
                )
                return count
            else:
                cursor = await self._db.execute(
                    "DELETE FROM audit_log WHERE timestamp < ?", (before_timestamp,)
                )
                await self._db.commit()
                return cursor.rowcount
        else:
            if self._is_postgres:
                count_result = await self._fetchone("SELECT COUNT(*) as cnt FROM audit_log")
                count = count_result["cnt"] if count_result else 0
                await self._execute("DELETE FROM audit_log")
                return count
            else:
                cursor = await self._db.execute("DELETE FROM audit_log")
                await self._db.commit()
                return cursor.rowcount

    async def save_recording(self, recording_data: dict[str, Any]) -> None:
        sql = self._upsert_sql("recordings", ["id", "name", "protocol", "start_time", "end_time", "messages", "metadata"])
        await self._execute(
            sql,
            (recording_data["id"], recording_data["name"], recording_data["protocol"],
             recording_data["start_time"], recording_data.get("end_time", 0),
             json.dumps(recording_data.get("messages", [])),
             json.dumps(recording_data.get("metadata", {}))),
        )

    async def load_recording(self, rec_id: str) -> Optional[dict[str, Any]]:
        row = await self._fetchone(
            f"SELECT * FROM recordings WHERE {self._where_sql('id')}",
            (rec_id,),
        )
        if not row:
            return None
        return {
            "id": row["id"], "name": row["name"], "protocol": row["protocol"],
            "start_time": row["start_time"], "end_time": row["end_time"],
            "messages": json.loads(row["messages"]),
            "metadata": json.loads(row["metadata"]),
        }

    async def load_all_recordings(self) -> list[dict[str, Any]]:
        rows = await self._fetchall("SELECT id, name, protocol, start_time, end_time, metadata FROM recordings")
        return [{
            "id": r["id"], "name": r["name"], "protocol": r["protocol"],
            "start_time": r["start_time"], "end_time": r["end_time"],
            "metadata": json.loads(r["metadata"]),
        } for r in rows]

    async def delete_recording(self, rec_id: str) -> None:
        await self._execute(
            f"DELETE FROM recordings WHERE {self._where_sql('id')}",
            (rec_id,),
        )

    async def export_all(self) -> dict[str, Any]:
        result = {}
        for table in ("devices", "scenarios", "templates", "test_cases",
                       "test_suites", "test_reports", "users", "recordings"):
            try:
                rows = await self._fetchall(f"SELECT * FROM {table}")
                result[table] = rows
            except Exception:
                result[table] = []
        try:
            rows = await self._fetchall("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 5000")
            result["audit_log"] = rows
        except Exception:
            result["audit_log"] = []
        return result

    async def import_all(self, data: dict[str, Any]) -> dict[str, int]:
        restored = {}
        table_columns = {
            "devices": ["id", "name", "protocol", "template_id", "points", "protocol_config"],
            "scenarios": ["id", "name", "description", "devices", "rules"],
            "templates": ["id", "name", "protocol", "description", "manufacturer", "model", "points", "protocol_config", "tags"],
            "test_cases": ["id", "name", "description", "tags", "steps", "setup_steps", "teardown_steps"],
            "test_suites": ["id", "name", "description", "test_case_ids", "tags", "created_at", "updated_at"],
            "test_reports": ["id", "name", "start_time", "end_time", "total", "passed", "failed", "errors", "skipped", "environment", "test_cases"],
            "users": ["username", "id", "password_hash", "role", "created_at", "login_attempts", "locked_until"],
            "recordings": ["id", "name", "protocol", "start_time", "end_time", "messages", "metadata"],
        }
        for table, columns in table_columns.items():
            rows = data.get(table, [])
            count = 0
            for row in rows:
                try:
                    values = [row.get(c, "") for c in columns]
                    sql = self._upsert_sql(table, columns)
                    await self._execute(sql, tuple(values))
                    count += 1
                except Exception:
                    pass
            restored[table] = count
        return restored
