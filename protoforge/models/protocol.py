from typing import Any

from pydantic import BaseModel


class ProtocolInfo(BaseModel):
    name: str
    display_name: str
    description: str = ""
    version: str = ""
    config_schema: dict[str, Any] = {}
