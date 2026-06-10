"""Layer 1: Pydantic Response Model <-> DB Table Column Cross-Check.

At startup, this module introspects:
  - Pydantic Response models (fields defined in protoforge.models.*)
  - DB table columns (from the DDL in protoforge.db.session.Database)

And reports mismatches where a Response model field has no corresponding
DB column, which would cause silent data loss or AttributeError at runtime.

Since ProtoForge uses raw SQL (no ORM), we maintain a registry that maps
each Response model to its DB table, then compare field names vs column names.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


@dataclass
class SchemaMismatch:
    """A single field/column mismatch."""

    model_name: str
    table_name: str
    field_name: str
    mismatch_type: str  # "field_not_in_db" | "column_not_in_model"
    detail: str = ""


@dataclass
class SchemaAuditResult:
    """Result of a schema audit run."""

    mismatches: list[SchemaMismatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.mismatches) == 0

    def summary(self) -> str:
        if self.ok:
            return "Schema audit passed: all Response model fields match DB columns."
        lines = [f"Schema audit found {len(self.mismatches)} mismatch(es):"]
        for m in self.mismatches:
            lines.append(f"  [{m.mismatch_type}] {m.model_name}.{m.field_name} <-> {m.table_name}: {m.detail}")
        for w in self.warnings:
            lines.append(f"  [warning] {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registry: maps Pydantic Response model -> DB table name
# ---------------------------------------------------------------------------

# Known mappings between Response models and DB tables.
# Key: Pydantic model class
# Value: DB table name
# Fields that exist in the model but are computed/virtual (not stored in DB)
# should be listed in _VIRTUAL_FIELDS below.

_MODEL_TABLE_MAP: dict[type[BaseModel], str] = {}

# Virtual fields: fields that exist in Response models but are NOT stored
# as DB columns (they are computed at runtime).
# Format: {("ModelName", "field_name"): reason}
_VIRTUAL_FIELDS: dict[tuple[str, str], str] = {
    # DeviceInfo fields computed at runtime, not in DB
    ("DeviceInfo", "status"): "computed at runtime from protocol state",
    ("DeviceInfo", "points"): "loaded from JSON column 'points' and transformed to PointValue list",
    ("DeviceInfo", "edgelite_status"): "computed at runtime from integration state",
    ("DeviceInfo", "protocol_active"): "computed at runtime from protocol state",
    # ScenarioInfo fields computed from nested data
    ("ScenarioInfo", "status"): "computed at runtime from engine state",
    ("ScenarioInfo", "device_count"): "computed from nested devices list",
    ("ScenarioInfo", "rule_count"): "computed from nested rules list",
    # ScenarioDetail inherits ScenarioInfo + adds nested lists
    ("ScenarioDetail", "status"): "inherited computed field from runtime engine state",
    ("ScenarioDetail", "device_count"): "inherited computed field",
    ("ScenarioDetail", "rule_count"): "inherited computed field",
    ("ScenarioDetail", "devices"): "loaded from JSON column 'devices'",
    ("ScenarioDetail", "rules"): "loaded from JSON column 'rules'",
    # TemplateInfo computed field
    ("TemplateInfo", "point_count"): "computed from nested points list",
    # ProtocolInfo is entirely virtual (no DB table)
    ("ProtocolInfo", "name"): "virtual model, no DB table",
    ("ProtocolInfo", "display_name"): "virtual model, no DB table",
    ("ProtocolInfo", "description"): "virtual model, no DB table",
    ("ProtocolInfo", "version"): "virtual model, no DB table",
    ("ProtocolInfo", "config_schema"): "virtual model, no DB table",
}

# Models that have NO corresponding DB table (purely virtual/computed)
_VIRTUAL_MODELS: set[str] = {
    "ProtocolInfo",
    "PointConfig",
    "PointValue",
    "DeviceConfig",
    "DeviceStatus",
    "DataType",
    "GeneratorType",
    "ScenarioConfig",
    "ScenarioConfigUpdate",
    "ScenarioStatus",
    "Rule",
    "RuleType",
    "TemplateDetail",
    "IntegrationMessage",
    "HandshakeRequest",
    "HandshakeResponse",
    "BackhaulConfig",
    "ChannelConfig",
    "IntegrationConfig",
    "ProtocolMappingResultModel",
    "DataTypeMappingResultModel",
    "CompatibilityReportModel",
    "BatchPushRequest",
    "BatchPushResult",
    "MessageType",
    "AlarmReactionRule",
}


def register_model_table(model_cls: type[BaseModel], table_name: str) -> None:
    """Register a Pydantic model <-> DB table mapping."""
    _MODEL_TABLE_MAP[model_cls] = table_name


def _auto_register_models() -> None:
    """Auto-register known model-table mappings from protoforge.models."""
    from protoforge.models.device import DeviceInfo
    from protoforge.models.scenario import ScenarioDetail, ScenarioInfo
    from protoforge.models.template import TemplateInfo

    if not _MODEL_TABLE_MAP:
        register_model_table(DeviceInfo, "devices")
        register_model_table(ScenarioInfo, "scenarios")
        register_model_table(ScenarioDetail, "scenarios")
        register_model_table(TemplateInfo, "templates")


# ---------------------------------------------------------------------------
# DB column introspection
# ---------------------------------------------------------------------------

async def get_db_columns(db, table_name: str) -> set[str]:
    """Get column names from a DB table.

    Works with both SQLite and PostgreSQL via the Database class.
    """
    if db._is_postgres:
        async with db._pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
                table_name,
            )
            return {r["column_name"] for r in rows}
    else:
        cursor = await db._db.execute(f"PRAGMA table_info({table_name})")
        rows = await cursor.fetchall()
        return {row[1] for row in rows}


# ---------------------------------------------------------------------------
# Audit logic
# ---------------------------------------------------------------------------

async def audit_schema(db) -> SchemaAuditResult:
    """Run the Pydantic model <-> DB column cross-check.

    Args:
        db: A connected Database instance.

    Returns:
        SchemaAuditResult with any mismatches found.
    """
    _auto_register_models()
    result = SchemaAuditResult()

    for model_cls, table_name in _MODEL_TABLE_MAP.items():
        model_name = model_cls.__name__

        # Get model fields (only direct fields, not nested model fields)
        model_fields = set(model_cls.model_fields.keys())

        # Get DB columns
        try:
            db_columns = await get_db_columns(db, table_name)
        except Exception as e:
            result.warnings.append(
                f"Could not introspect DB table '{table_name}': {e}"
            )
            continue

        # Check each model field against DB columns
        for field_name in model_fields:
            # Skip virtual/computed fields
            virtual_key = (model_name, field_name)
            if virtual_key in _VIRTUAL_FIELDS:
                continue

            # Map Python field name to possible DB column names
            # Handle cases like protocol_config -> protocol_config (direct match)
            possible_db_names = {field_name}
            # Also check snake_case conversion (already snake_case in this project)

            if not possible_db_names & db_columns:
                result.mismatches.append(SchemaMismatch(
                    model_name=model_name,
                    table_name=table_name,
                    field_name=field_name,
                    mismatch_type="field_not_in_db",
                    detail=f"Field '{field_name}' in {model_name} has no matching column in DB table '{table_name}'. "
                           f"DB columns: {sorted(db_columns)}",
                ))

        # Check each DB column against model fields (informational, not error)
        for col_name in db_columns:
            virtual_key = (model_name, col_name)
            if virtual_key in _VIRTUAL_FIELDS:
                continue
            if col_name not in model_fields:
                # This is a warning, not an error - DB can have extra columns
                # (e.g., JSON storage columns, internal fields)
                result.warnings.append(
                    f"DB column '{col_name}' in table '{table_name}' not in {model_name} model fields. "
                    f"This may be intentional (JSON storage, internal field)."
                )

    return result


def audit_schema_sync() -> SchemaAuditResult:
    """Synchronous version of schema audit that checks model definitions only.

    This does NOT connect to the database. It only checks that the
    _MODEL_TABLE_MAP and _VIRTUAL_FIELDS registry is consistent.
    Useful for CI/pre-commit checks.
    """
    _auto_register_models()
    result = SchemaAuditResult()

    for model_cls, table_name in _MODEL_TABLE_MAP.items():
        model_name = model_cls.__name__
        model_fields = set(model_cls.model_fields.keys())

        for field_name in model_fields:
            virtual_key = (model_name, field_name)
            if virtual_key in _VIRTUAL_FIELDS:
                continue

    # Check that all registered virtual fields reference valid model names
    for (model_name, field_name), reason in _VIRTUAL_FIELDS.items():
        # Try to find the model class
        found = False
        for model_cls in _MODEL_TABLE_MAP:
            if model_cls.__name__ == model_name:
                if field_name not in model_cls.model_fields:
                    result.warnings.append(
                        f"Virtual field registry references {model_name}.{field_name} "
                        f"but that field doesn't exist in the model."
                    )
                found = True
                break
        if not found and model_name not in _VIRTUAL_MODELS:
            result.warnings.append(
                f"Virtual field registry references model '{model_name}' "
                f"which is not registered in _MODEL_TABLE_MAP or _VIRTUAL_MODELS."
            )

    return result


def scan_all_response_models() -> list[tuple[str, str, set[str]]]:
    """Scan all Pydantic BaseModel subclasses in protoforge.models.

    Returns list of (model_name, module_name, field_names) for models
    that are NOT in _VIRTUAL_MODELS and could potentially need DB mapping.
    """
    import importlib
    import pkgutil

    _auto_register_models()
    unregistered = []

    try:
        import protoforge.models as models_pkg
        for importer, modname, ispkg in pkgutil.walk_packages(
            models_pkg.__path__, prefix="protoforge.models."
        ):
            try:
                mod = importlib.import_module(modname)
            except Exception:
                continue
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseModel)
                    and attr is not BaseModel
                    and attr.__name__ not in _VIRTUAL_MODELS
                    and attr not in _MODEL_TABLE_MAP
                ):
                    fields = set(attr.model_fields.keys())
                    unregistered.append((attr.__name__, modname, fields))

    except Exception as e:
        logger.debug("Failed to scan models package: %s", e)

    return unregistered
