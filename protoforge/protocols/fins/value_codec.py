"""FINS point value encoding and decoding."""

import struct
from typing import Any


class FinsValueCodec:
    """将点位类型与 FINS 大端字节之间进行转换。

    该类保持无状态，使 FINS 内存行为和数据类型转换职责分离。
    """

    @staticmethod
    def type_name(point: Any) -> str:
        data_type = getattr(point, "data_type", "") if point else ""
        return str(getattr(data_type, "value", data_type) or "").lower()

    @classmethod
    def width(cls, point: Any) -> int:
        data_type = cls.type_name(point)
        if data_type in ("int32", "uint32", "dint", "float32"):
            return 4
        if data_type == "float64":
            return 8
        return 2

    @classmethod
    def encode(cls, point: Any, value: Any) -> bytes:
        data_type = cls.type_name(point)
        if data_type == "bool":
            return struct.pack(">H", 1 if bool(value) else 0)
        if data_type == "float32":
            return struct.pack(">f", float(value))
        if data_type == "float64":
            return struct.pack(">d", float(value))
        if data_type == "int16":
            return struct.pack(">h", int(value))
        if data_type == "uint16":
            return struct.pack(">H", int(value) & 0xFFFF)
        if data_type in ("int32", "dint"):
            return struct.pack(">i", int(value))
        if data_type == "uint32":
            return struct.pack(">I", int(value) & 0xFFFFFFFF)
        if data_type == "string" or isinstance(value, str):
            return str(value).encode("utf-8")
        return struct.pack(">h", int(value) & 0xFFFF)

    @classmethod
    def decode(cls, point: Any, data: bytes) -> Any:
        data_type = cls.type_name(point)
        if data_type == "string":
            if not data:
                return None
            return data.rstrip(b"\x00").decode("utf-8", errors="replace")

        width = cls.width(point)
        if len(data) < width:
            return None
        if data_type == "bool":
            return int.from_bytes(data[:2], byteorder="big") != 0
        if data_type == "float32":
            return struct.unpack(">f", data[:4])[0]
        if data_type == "float64":
            return struct.unpack(">d", data[:8])[0]
        if data_type == "int16":
            return struct.unpack(">h", data[:2])[0]
        if data_type == "uint16":
            return struct.unpack(">H", data[:2])[0]
        if data_type in ("int32", "dint"):
            return struct.unpack(">i", data[:4])[0]
        if data_type == "uint32":
            return struct.unpack(">I", data[:4])[0]
        return struct.unpack(">h", data[:2])[0]
