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
        self._add_lathe_station_templates()
        self._load_from_dir(_TEMPLATES_DIR / "toledo")
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

    def _add_lathe_station_templates(self) -> None:
        """
        MTConnect 车床按工位拆分模板。

        原 mtconnect_lathe 保留用于兼容旧设备；三个 station 模板由同一组
        MTConnect 测点派生，但会在 simulator registry 中绑定到不同工艺。
        """
        base = self._templates.get("mtconnect_lathe")
        if base is None:
            return

        station_defs = [
            {
                "id": "mtconnect_lathe_rough",
                "name": "MTConnect车床 粗加工工位",
                "uuid": "mtc-lathe-rough-001",
                "process_tag": "粗加工",
                "description": (
                    "MTConnect标准车床粗加工工位，固定运行粗车工艺；"
                    "主轴约2000RPM，负载和电流较高，适合单独观察粗加工数据。"
                ),
            },
            {
                "id": "mtconnect_lathe_semi_finish",
                "name": "MTConnect车床 半精加工工位",
                "uuid": "mtc-lathe-semi-finish-001",
                "process_tag": "半精加工",
                "description": (
                    "MTConnect标准车床半精加工工位，固定运行半精车工艺；"
                    "主轴约3000RPM，负载、电流和粗糙度介于粗加工与精加工之间。"
                ),
            },
            {
                "id": "mtconnect_lathe_finish",
                "name": "MTConnect车床 精加工工位",
                "uuid": "mtc-lathe-finish-001",
                "process_tag": "精加工",
                "description": (
                    "MTConnect标准车床精加工工位，固定运行精车工艺；"
                    "主轴约4000RPM，负载较低，转速和表面质量更稳定。"
                ),
            },
        ]

        for spec in station_defs:
            if spec["id"] in self._templates:
                continue
            template = base.model_copy(deep=True)
            template.id = spec["id"]
            template.name = spec["name"]
            template.description = spec["description"]
            template.protocol_config = {
                **template.protocol_config,
                "device_uuid": spec["uuid"],
            }
            template.tags = [
                tag for tag in template.tags
                if tag not in {"粗加工", "半精加工", "精加工"}
            ]
            template.tags.extend(["工位", spec["process_tag"]])
            self._templates[template.id] = template
