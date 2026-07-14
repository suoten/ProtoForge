import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# FIXED: P4 - W19 Environment variable overrides hardcoded SQLite URL in alembic.ini.
# Prefer PROTOFORGE_DB_PATH env var, supporting both PostgreSQL and SQLite.
# The sqlalchemy.url in alembic.ini is only a placeholder default; production must set the env var.
db_path = os.environ.get("PROTOFORGE_DB_PATH", "")
if db_path:
    if db_path.startswith("postgresql"):
        sqlalchemy_url = db_path.replace("postgresql://", "postgresql+asyncpg://")
    else:
        sqlalchemy_url = f"sqlite+aiosqlite:///{db_path}"
    config.set_main_option("sqlalchemy.url", sqlalchemy_url)
else:
    # Ensure the default URL from alembic.ini uses an async driver,
    # because env.py uses async_engine_from_config which requires async drivers.
    default_url = config.get_main_option("sqlalchemy.url") or "sqlite:///data/protoforge.db"
    if default_url.startswith("postgresql://"):
        sqlalchemy_url = default_url.replace("postgresql://", "postgresql+asyncpg://")
    elif default_url.startswith("sqlite:///") and "+" not in default_url:
        sqlalchemy_url = default_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    else:
        sqlalchemy_url = default_url
    config.set_main_option("sqlalchemy.url", sqlalchemy_url)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
