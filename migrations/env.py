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

# FIXED: P4 - W19 环境变量覆盖 alembic.ini 中的硬编码 SQLite URL
# 优先使用 PROTOFORGE_DB_PATH 环境变量，支持 PostgreSQL 和 SQLite 两种数据库
# alembic.ini 中的 sqlalchemy.url 仅为占位默认值，生产环境必须设置环境变量
db_path = os.environ.get("PROTOFORGE_DB_PATH", "")
if db_path:
    if db_path.startswith("postgresql"):
        sqlalchemy_url = db_path.replace("postgresql://", "postgresql+asyncpg://")
    else:
        sqlalchemy_url = f"sqlite+aiosqlite:///{db_path}"
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
