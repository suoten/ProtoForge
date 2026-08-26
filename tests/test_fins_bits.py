from protoforge.protocols.fins.server import FinsDeviceBehavior
from protoforge.protocols.fins.value_codec import FinsValueCodec
from protoforge.models.device import DataType, PointConfig


def test_dm_bit_read_write_round_trip() -> None:
    behavior = FinsDeviceBehavior([])

    behavior.write_bits(0x02, 100, 5, b"\x01")

    assert behavior.read_bits(0x02, 100, 5, 1) == b"\x01"
    assert behavior.read_area(0x82, 100 * 2, 2) == b"\x00\x20"

    behavior.write_bits(0x02, 100, 5, b"\x00")

    assert behavior.read_bits(0x02, 100, 5, 1) == b"\x00"
    assert behavior.read_area(0x82, 100 * 2, 2) == b"\x00\x00"


def test_word_write_syncs_all_supported_point_types() -> None:
    points = [
        PointConfig(name="i16", address="DM100", data_type=DataType.INT16),
        PointConfig(name="u16", address="DM101", data_type=DataType.UINT16),
        PointConfig(name="i32", address="DM102", data_type=DataType.INT32),
        PointConfig(name="u32", address="DM104", data_type=DataType.UINT32),
        PointConfig(name="f32", address="DM106", data_type=DataType.FLOAT32),
        PointConfig(name="f64", address="DM108", data_type=DataType.FLOAT64),
        PointConfig(name="text", address="DM112", data_type=DataType.STRING, fixed_value="old"),
    ]
    behavior = FinsDeviceBehavior(points)

    values = {
        "i16": -123,
        "u16": 54321,
        "i32": -123456,
        "u32": 345678,
        "f32": 12.5,
        "f64": -0.125,
        "text": "newer-string",
    }
    for name, value in values.items():
        behavior.on_write(name, value)

    # 模拟客户端将每个点的原始字节写入 FINS DM 区域，再同步回页面点位。
    for name, value in values.items():
        point = next(point for point in points if point.name == name)
        raw = FinsValueCodec.encode(point, value)
        word_address = int(point.address[2:])
        behavior.write_area(0x82, word_address * 2, raw)
        behavior.sync_word_write_to_points(0x82, word_address, raw)

    assert behavior._values["i16"] == -123
    assert behavior._values["u16"] == 54321
    assert behavior._values["i32"] == -123456
    assert behavior._values["u32"] == 345678
    assert behavior._values["f32"] == 12.5
    assert behavior._values["f64"] == -0.125
    assert behavior._values["text"] == "newer-string"


def test_word_write_can_sync_point_when_write_starts_before_it() -> None:
    point = PointConfig(name="f32", address="DM101", data_type=DataType.FLOAT32)
    behavior = FinsDeviceBehavior([point])
    raw = FinsValueCodec.encode(point, 3.5)

    behavior.write_area(0x82, 100 * 2, b"\x00\x00" + raw)
    behavior.sync_word_write_to_points(0x82, 100, b"\x00\x00" + raw)

    assert behavior._values["f32"] == 3.5
