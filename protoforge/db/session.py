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
        self._pg_pool = await asyncpg.create_pool(self._db_path, min_size=2, max_size=10)
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

    async def save_device(self, config: DeviceConfig) -> None:
        points_json = json.dumps([p.model_dump() for p in config.points])
        config_json = json.dumps(config.protocol_config)
        await self._execute(
            """INSERT OR REPLACE INTO devices (id, name, protocol, template_id, points, protocol_config)
               VALUES ($1, $2, $3, $4, $5, $6)""" if self._is_postgres else
            """INSERT OR REPLACE INTO devices (id, name, protocol, template_id, points, protocol_config)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (config.id, config.name, config.protocol, config.template_id, points_json, config_json),
        )

    async def load_device(self, device_id: str) -> Optional[DeviceConfig]:
        row = await self._fetchone(
            "SELECT * FROM devices WHERE id = $1" if self._is_postgres else "SELECT * FROM devices WHERE id = ?",
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
            "DELETE FROM devices WHERE id = $1" if self._is_postgres else "DELETE FROM devices WHERE id = ?",
            (device_id,),
        )

    async def save_scenario(self, config: ScenarioConfig) -> None:
        devices_json = json.dumps([d.model_dump() for d in config.devices])
        rules_json = json.dumps([r.model_dump() for r in config.rules])
        await self._execute(
            """INSERT OR REPLACE INTO scenarios (id, name, description, devices, rules)
               VALUES ($1, $2, $3, $4, $5)""" if self._is_postgres else
            """INSERT OR REPLACE INTO scenarios (id, name, description, devices, rules)
               VALUES (?, ?, ?, ?, ?)""",
            (config.id, config.name, config.description, devices_json, rules_json),
        )

    async def load_scenario(self, scenario_id: str) -> Optional[ScenarioConfig]:
        row = await self._fetchone(
            "SELECT * FROM scenarios WHERE id = $1" if self._is_postgres else "SELECT * FROM scenarios WHERE id = ?",
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
            "DELETE FROM scenarios WHERE id = $1" if self._is_postgres else "DELETE FROM scenarios WHERE id = ?",
            (scenario_id,),
        )

    async def save_template(self, template: TemplateDetail) -> None:
        points_json = json.dumps([p.model_dump() for p in template.points])
        config_json = json.dumps(template.protocol_config)
        tags_json = json.dumps(template.tags)
        await self._execute(
            """INSERT OR REPLACE INTO templates (id, name, protocol, description, manufacturer, model, points, protocol_config, tags)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""" if self._is_postgres else
            """INSERT OR REPLACE INTO templates (id, name, protocol, description, manufacturer, model, points, protocol_config, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (template.id, template.name, template.protocol, template.description,
             template.manufacturer, template.model, points_json, config_json, tags_json),
        )

    async def load_all_templates(self) -> list[TemplateDetail]:
        rows = await self._fetchall("SELECT * FROM templates")
        return [self._row_to_template(row) for row in rows]

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
        await self._execute(
            """INSERT OR REPLACE INTO test_cases (id, name, description, tags, steps, setup_steps, teardown_steps)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""" if self._is_postgres else
            """INSERT OR REPLACE INTO test_cases (id, name, description, tags, steps, setup_steps, teardown_steps)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (case_data["id"], case_data.get("name", ""), case_data.get("description", ""),
             json.dumps(case_data.get("tags", [])), json.dumps(case_data.get("steps", [])),
             json.dumps(case_data.get("setup_steps", [])), json.dumps(case_data.get("teardown_steps", []))),
        )

    async def load_test_case(self, case_id: str) -> Optional[dict[str, Any]]:
        row = await self._fetchone(
            "SELECT * FROM test_cases WHERE id = $1" if self._is_postgres else "SELECT * FROM test_cases WHERE id = ?",
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
            "DELETE FROM test_cases WHERE id = $1" if self._is_postgres else "DELETE FROM test_cases WHERE id = ?",
            (case_id,),
        )

    async def save_test_suite(self, suite_data: dict[str, Any]) -> None:
        await self._execute(
            """INSERT OR REPLACE INTO test_suites (id, name, description, test_case_ids, tags, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""" if self._is_postgres else
            """INSERT OR REPLACE INTO test_suites (id, name, description, test_case_ids, tags, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
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
            "DELETE FROM test_suites WHERE id = $1" if self._is_postgres else "DELETE FROM test_suites WHERE id = ?",
            (suite_id,),
        )

    async def save_test_report(self, report_data: dict[str, Any]) -> None:
        await self._execute(
            """INSERT OR REPLACE INTO test_reports (id, name, start_time, end_time, total, passed, failed, errors, skipped, environment, test_cases)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""" if self._is_postgres else
            """INSERT OR REPLACE INTO test_reports (id, name, start_time, end_time, total, passed, failed, errors, skipped, environment, test_cases)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (report_data["id"], report_data.get("name", ""),
             report_data.get("start_time", 0), report_data.get("end_time", 0),
             report_data.get("total", 0), report_data.get("passed", 0),
             report_data.get("failed", 0), report_data.get("errors", 0),
             report_data.get("skipped", 0),
             json.dumps(report_data.get("environment", {})),
             json.dumps(report_data.get("test_cases", []))),
        )

    async def load_test_reports(self, count: int = 50) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT * FROM test_reports ORDER BY created_at DESC LIMIT $1" if self._is_postgres else "SELECT * FROM test_reports ORDER BY created_at DESC LIMIT ?",
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
            "DELETE FROM test_reports WHERE id = $1" if self._is_postgres else "DELETE FROM test_reports WHERE id = ?",
            (report_id,),
        )

    async def save_user(self, user_data: dict[str, Any]) -> None:
        await self._execute(
            """INSERT OR REPLACE INTO users (username, id, password_hash, role, created_at, login_attempts, locked_until)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""" if self._is_postgres else
            """INSERT OR REPLACE INTO users (username, id, password_hash, role, created_at, login_attempts, locked_until)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
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

    async def delete_user(self, username: str) -> None:
        await self._execute(
            "DELETE FROM users WHERE username = $1" if self._is_postgres else "DELETE FROM users WHERE username = ?",
            (username,),
        )
