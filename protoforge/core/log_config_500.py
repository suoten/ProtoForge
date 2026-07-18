"""500 错误专用日志配置

提供 dictConfig 格式的日志配置，将 500 错误单独写入独立文件，
便于运维快速排查。同时提供慢请求和错误率告警能力。

使用方式 1（在 cli.py 中替换现有 log_config）::

    from protoforge.core.log_config_500 import get_log_config
    uvicorn.run(..., log_config=get_log_config(log_level="info"))

使用方式 2（程序中直接应用）::

    import logging.config
    from protoforge.core.log_config_500 import get_log_config
    logging.config.dictConfig(get_log_config())

日志文件结构::
    logs/
      protoforge.log          # 全量日志（INFO+）
      error_500.log           # 仅 500 错误（ERROR+，独立文件）
      access.log              # 访问日志
"""

import os
from pathlib import Path


_LOG_DIR = Path(os.environ.get("PROTOFORGE_LOG_DIR", "logs"))
_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
_LOG_BACKUP_COUNT = 10


def get_log_config(log_level: str = "info") -> dict:
    """返回完整的 dictConfig 配置字典。

    Args:
        log_level: 基础日志级别 (debug/info/warning/error)

    Returns:
        可直接传给 logging.config.dictConfig 或 uvicorn log_config 的字典
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    return {
        "version": 1,
        "disable_existing_loggers": False,

        # =====================================================================
        #  过滤器
        # =====================================================================
        "filters": {
            # 500 监控专用过滤器
            "error_500_filter": {
                "()": "protoforge.core.log_config_500._Error500Filter",
            },
        },

        # =====================================================================
        #  格式化器
        # =====================================================================
        "formatters": {
            # 标准格式
            "standard": {
                "format": "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            # 详细格式（含文件名和行号，用于错误日志）
            "detailed": {
                "format": (
                    "%(asctime)s %(levelname)-8s [%(name)s:%(lineno)d] "
                    "%(message)s"
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            # JSON 格式（便于 ELK/Loki 等日志系统采集）
            "json": {
                "()": "protoforge.core.log_config_500._JsonFormatter",
            },
            # 访问日志格式
            "access": {
                "format": (
                    '%(asctime)s %(levelname)-8s %(client_addr)s - '
                    '"%(request_line)s" %(status_code)s %(duration_ms)dms'
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },

        # =====================================================================
        #  处理器
        # =====================================================================
        "handlers": {
            # 控制台输出
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": "ext://sys.stderr",
                "level": log_level.upper(),
            },
            # 全量日志文件（轮转）
            "file_all": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "standard",
                "filename": str(_LOG_DIR / "protoforge.log"),
                "maxBytes": _LOG_MAX_BYTES,
                "backupCount": _LOG_BACKUP_COUNT,
                "encoding": "utf-8",
                "level": "DEBUG",
            },
            # ★ 500 错误专用文件（独立轮转，方便快速排查）
            "file_500": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "detailed",
                "filename": str(_LOG_DIR / "error_500.log"),
                "maxBytes": _LOG_MAX_BYTES,
                "backupCount": 20,  # 500 错误保留更多历史
                "encoding": "utf-8",
                "level": "ERROR",
                "filters": ["error_500_filter"],
            },
            # 500 错误 JSON 格式文件（便于日志采集系统）
            "file_500_json": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "json",
                "filename": str(_LOG_DIR / "error_500.jsonl"),
                "maxBytes": _LOG_MAX_BYTES,
                "backupCount": 20,
                "encoding": "utf-8",
                "level": "ERROR",
                "filters": ["error_500_filter"],
            },
            # 访问日志
            "access_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "access",
                "filename": str(_LOG_DIR / "access.log"),
                "maxBytes": _LOG_MAX_BYTES,
                "backupCount": 5,
                "encoding": "utf-8",
                "level": "INFO",
            },
        },

        # =====================================================================
        #  日志器
        # =====================================================================
        "loggers": {
            # ProtoForge 应用日志
            "protoforge": {
                "level": log_level.upper(),
                "handlers": ["console", "file_all", "file_500", "file_500_json"],
                "propagate": False,
            },
            # 500 错误监控专用
            "protoforge.error_monitor": {
                "level": "ERROR",
                "handlers": ["file_500", "file_500_json"],
                "propagate": True,
            },
            # API 层日志
            "protoforge.api": {
                "level": log_level.upper(),
                "handlers": ["console", "file_all", "file_500"],
                "propagate": False,
            },
            # 协议层日志
            "protoforge.protocols": {
                "level": log_level.upper(),
                "handlers": ["console", "file_all"],
                "propagate": False,
            },
            # 数据库层日志
            "protoforge.db": {
                "level": log_level.upper(),
                "handlers": ["console", "file_all", "file_500"],
                "propagate": False,
            },
            # Uvicorn
            "uvicorn": {
                "level": log_level.upper(),
                "propagate": True,
            },
            "uvicorn.error": {
                "level": log_level.upper(),
                "propagate": True,
            },
            "uvicorn.access": {
                "handlers": ["access_file"],
                "level": "INFO",
                "propagate": False,
            },
            # 第三方库降噪
            "asyncua": {"level": "WARNING", "propagate": True},
            "asyncpg": {"level": "WARNING", "propagate": True},
            "aiosqlite": {"level": "WARNING", "propagate": True},
        },

        # =====================================================================
        #  根日志器
        # =====================================================================
        "root": {
            "level": log_level.upper(),
            "handlers": ["console", "file_all", "file_500"],
        },
    }


# =============================================================================
#  自定义过滤器
# =============================================================================

class _Error500Filter(logging.Filter):
    """只放行 ERROR 及以上级别的日志（用于 500 错误专用文件）。

    过滤掉 DEBUG/INFO/WARNING 级别的日志，确保 error_500.log 只包含真正的错误。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR


# =============================================================================
#  JSON 格式化器（便于 ELK/Loki/Grafana 采集）
# =============================================================================

class _JsonFormatter(logging.Formatter):
    """将日志格式化为 JSON 行（JSONL），便于日志采集系统解析。

    输出示例::

        {"ts":"2026-01-01 12:00:00","level":"ERROR","logger":"protoforge.api",
         "file":"device_routes.py","line":70,"msg":"...","traceback":"..."}
    """

    def format(self, record: logging.LogRecord) -> str:
        import json as _json
        log_entry = {
            "ts": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "file": record.filename,
            "line": record.lineno,
            "msg": record.getMessage(),
        }

        # 异常信息
        if record.exc_info and record.exc_info[1] is not None:
            import traceback
            log_entry["exception"] = str(record.exc_info[1])
            log_entry["traceback"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        # 额外字段（如 500_MONITOR 标记）
        if hasattr(record, "method"):
            log_entry["method"] = record.method
        if hasattr(record, "path"):
            log_entry["path"] = record.path
        if hasattr(record, "status_code"):
            log_entry["status_code"] = record.status_code
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms

        return self._json.dumps(log_entry, ensure_ascii=False)
