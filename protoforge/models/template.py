from typing import Any, Optional

from pydantic import BaseModel, Field

from protoforge.models.device import PointConfig


class TemplateInfo(BaseModel):
    id: str
    name: str
    protocol: str
    description: str = ""
    manufacturer: str = ""
    model: str = ""
    point_count: int = 0
    tags: list[str] = Field(default_factory=list)


class TemplateDetail(BaseModel):
    id: str
    name: str
    protocol: str
    description: str = ""
    manufacturer: str = ""
    model: str = ""
    points: list[PointConfig] = Field(default_factory=list)
    protocol_config: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
