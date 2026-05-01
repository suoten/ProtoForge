import json
import logging
from pathlib import Path
from typing import Any, Optional

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.models.template import TemplateDetail, TemplateInfo

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class TemplateManager:
    def __init__(self):
        self._templates: dict[str, TemplateDetail] = {}
        self._loaded = False

    def load_builtin_templates(self) -> None:
        if self._loaded:
            return
        self._load_from_dir(_TEMPLATES_DIR / "modbus")
        self._load_from_dir(_TEMPLATES_DIR / "opcua")
        self._load_from_dir(_TEMPLATES_DIR / "mqtt")
        self._load_from_dir(_TEMPLATES_DIR / "gb28181")
        self._load_from_dir(_TEMPLATES_DIR / "bacnet")
        self._load_from_dir(_TEMPLATES_DIR / "s7")
        self._load_from_dir(_TEMPLATES_DIR / "mc")
        self._load_from_dir(_TEMPLATES_DIR / "fins")
        self._load_from_dir(_TEMPLATES_DIR / "ab")
        self._load_from_dir(_TEMPLATES_DIR / "opcda")
        self._load_from_dir(_TEMPLATES_DIR / "fanuc")
        self._load_from_dir(_TEMPLATES_DIR / "mtconnect")
        self._load_from_dir(_TEMPLATES_DIR / "toledo")
        self._load_from_dir(_TEMPLATES_DIR / "profinet")
        self._load_from_dir(_TEMPLATES_DIR / "ethercat")
        self._load_from_dir(_TEMPLATES_DIR / "http_rest")
        self._loaded = True
        logger.info("Loaded %d built-in templates", len(self._templates))

    def list_templates(self, protocol: Optional[str] = None) -> list[TemplateInfo]:
        self.load_builtin_templates()
        result = []
        for t in self._templates.values():
            if protocol and t.protocol != protocol:
                continue
            result.append(
                TemplateInfo(
                    id=t.id,
                    name=t.name,
                    protocol=t.protocol,
                    description=t.description,
                    manufacturer=t.manufacturer,
                    model=t.model,
                    point_count=len(t.points),
                    tags=t.tags,
                )
            )
        return result

    def get_template(self, template_id: str) -> TemplateDetail:
        self.load_builtin_templates()
        template = self._templates.get(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")
        return template

    def add_template(self, template: TemplateDetail) -> None:
        self._templates[template.id] = template

    def remove_template(self, template_id: str) -> Optional[TemplateDetail]:
        return self._templates.pop(template_id, None)

    def update_template(self, template_id: str, data: dict[str, Any]) -> TemplateDetail:
        existing = self._templates.get(template_id)
        if not existing:
            raise ValueError(f"Template not found: {template_id}")
        points = [PointConfig(**p) for p in data.get("points", [])] if "points" in data else existing.points
        updated = TemplateDetail(
            id=template_id,
            name=data.get("name", existing.name),
            protocol=data.get("protocol", existing.protocol),
            description=data.get("description", existing.description),
            manufacturer=data.get("manufacturer", existing.manufacturer),
            model=data.get("model", existing.model),
            points=points,
            protocol_config=data.get("protocol_config", existing.protocol_config),
            tags=data.get("tags", existing.tags),
        )
        self._templates[template_id] = updated
        return updated

    def create_device_from_template(self, template_id: str, device_id: str, device_name: str,
                                    protocol_config: Optional[dict[str, Any]] = None) -> DeviceConfig:
        template = self.get_template(template_id)
        return DeviceConfig(
            id=device_id,
            name=device_name,
            protocol=template.protocol,
            template_id=template_id,
            points=list(template.points),
            protocol_config=protocol_config or dict(template.protocol_config),
        )

    def _load_from_dir(self, dir_path: Path) -> None:
        if not dir_path.exists():
            return
        for json_file in dir_path.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                points = [PointConfig(**p) for p in data.get("points", [])]
                template = TemplateDetail(
                    id=data.get("id", json_file.stem),
                    name=data.get("name", json_file.stem),
                    protocol=data.get("protocol", ""),
                    description=data.get("description", ""),
                    manufacturer=data.get("manufacturer", ""),
                    model=data.get("model", ""),
                    points=points,
                    protocol_config=data.get("protocol_config", {}),
                    tags=data.get("tags", []),
                )
                self._templates[template.id] = template
            except Exception as e:
                logger.warning("Failed to load template %s: %s", json_file, e)
