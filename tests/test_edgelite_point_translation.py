"""Unit tests for ProtoForge→EdgeLite point address translation.

Validates ``_translate_point_address`` and the protocol-aware ``_build_points``:
- Modbus: output address carries the register-area prefix (``HR``/``IR``/``C``/``DI``)
  because EdgeLite's modbus driver decides the area solely from the address prefix
  (it ignores ``register_type``); ``register_type`` is still emitted as redundant
  info and must mirror ProtoForge server storage rules (``auto+bool→coil``,
  ``auto→holding``, explicit prefixes mapped directly), so EdgeLite reads from
  the same region ProtoForge writes to.
- S7: ProtoForge ``DB1.DBD2`` → EdgeLite ``DB1.D2`` (strip the leading ``B``
  of the type token after the first dot), avoiding ``int("BD2")`` ValueError
  in EdgeLite's ``s7.py:_parse_address``.
"""

from __future__ import annotations

import pytest

from protoforge.integrations.edgelite import (
    _build_points,
    _normalize_protocol_alias,
    _translate_point_address,
)


# ---------------------------------------------------------------------------
#  Modbus 地址翻译
# ---------------------------------------------------------------------------


class TestModbusAddressTranslation:
    """Modbus 点位地址 → (address, register_type) 翻译。"""

    @pytest.mark.parametrize(
        "address,data_type,expected_addr,expected_reg",
        [
            # 显式前缀 → 归一化为规范前缀 + 裸地址（EdgeLite 只认前缀）
            ("C100", "bool", "C100", "coil"),
            ("COIL5", "bool", "C5", "coil"),
            ("0X10", "bool", "C10", "coil"),
            ("HR100", "float32", "HR100", "holding"),
            ("4X100", "float32", "HR100", "holding"),
            ("IR8", "float32", "IR8", "input"),
            ("3X8", "float32", "IR8", "input"),
            ("DI3", "bool", "DI3", "discrete"),
            ("DISCRETE_INPUT7", "bool", "DI7", "discrete"),
            # 6 位 PLC 记法 (400001 → addr 0)，同样输出带前缀地址
            ("400100", "float32", "HR99", "holding"),
            ("300100", "float32", "IR99", "input"),
            ("000100", "bool", "C99", "coil"),
            ("100100", "bool", "DI99", "discrete"),
        ],
    )
    def test_explicit_prefix_and_plc_notation(self, address, data_type, expected_addr, expected_reg):
        result = _translate_point_address("modbus_tcp", address, data_type)
        assert result["address"] == expected_addr
        assert result["register_type"] == expected_reg

    def test_auto_bool_maps_to_coil(self):
        """auto 区域 + bool → coil（复刻 server.py:667-668 存储规则）。

        这是 coolant_on 点位的关键用例：ProtoForge 存 coils[4]，EdgeLite
        必须读 coil 而非默认的 holding，否则值错位。
        """
        result = _translate_point_address("modbus_tcp", "4", "bool")
        assert result == {"address": "C4", "register_type": "coil"}

    def test_auto_numeric_maps_to_holding(self):
        """auto 区域 + 非 bool → holding。"""
        result = _translate_point_address("modbus_tcp", "100", "float32")
        assert result == {"address": "HR100", "register_type": "holding"}

        result2 = _translate_point_address("modbus_tcp", "200", "int32")
        assert result2 == {"address": "HR200", "register_type": "holding"}

    def test_holding_prefix_bool_stays_holding(self):
        """显式 HR 前缀即使 data_type=bool 也保持 holding（遵从显式地址）。"""
        result = _translate_point_address("modbus_tcp", "HR50", "bool")
        assert result == {"address": "HR50", "register_type": "holding"}

    def test_empty_address_defaults_to_holding(self):
        result = _translate_point_address("modbus_tcp", "", "float32")
        assert result == {"address": "0", "register_type": "holding"}

    def test_none_address_defaults_to_holding(self):
        result = _translate_point_address("modbus_tcp", None, "float32")
        assert result == {"address": "0", "register_type": "holding"}

    def test_unparseable_address_falls_back(self):
        """无法解析的地址退化为纯数字 + holding，不抛异常。"""
        result = _translate_point_address("modbus_tcp", "garbage", "float32")
        assert result == {"address": "0", "register_type": "holding"}

    def test_modbus_rtu_same_rules_as_tcp(self):
        """modbus_rtu 与 modbus_tcp 共用同一翻译规则。"""
        result = _translate_point_address("modbus_rtu", "C10", "bool")
        assert result == {"address": "C10", "register_type": "coil"}

    def test_plugin_name_normalized(self):
        """EdgeLite plugin_name 应被规范为别名后正确翻译。"""
        # modbus_tcp 无 plugin_name 别名，直接透传
        assert _normalize_protocol_alias("modbus_tcp") == "modbus_tcp"
        assert _normalize_protocol_alias("siemens_s7") == "s7"
        assert _normalize_protocol_alias("mqtt_client") == "mqtt"


# ---------------------------------------------------------------------------
#  S7 地址翻译
# ---------------------------------------------------------------------------


class TestS7AddressTranslation:
    """S7 点位地址 ProtoForge→EdgeLite 格式翻译。"""

    @pytest.mark.parametrize(
        "protoforge_addr,expected_edgelite_addr",
        [
            ("DB1.DBD2", "DB1.D2"),       # 双字
            ("DB1.DBX0.0", "DB1.X0.0"),   # 位
            ("DB1.DBB5", "DB1.B5"),       # 字节
            ("DB1.DBW10", "DB1.W10"),     # 字
            ("DB10.DBD100", "DB10.D100"),  # 多位 DB 号
            ("DB1.DBX7.3", "DB1.X7.3"),   # 位偏移保留
        ],
    )
    def test_protoforge_to_edgelite(self, protoforge_addr, expected_edgelite_addr):
        result = _translate_point_address("s7", protoforge_addr, "float32")
        assert result == {"address": expected_edgelite_addr}

    def test_already_edgelite_format_passthrough(self):
        """已是 EdgeLite 格式（DB1.D2）应透传，不被二次修改。"""
        result = _translate_point_address("s7", "DB1.D2", "float32")
        assert result == {"address": "DB1.D2"}

        result2 = _translate_point_address("s7", "DB1.X0.0", "bool")
        assert result2 == {"address": "DB1.X0.0"}

    def test_non_db_address_passthrough(self):
        """非 DB 地址（I0.0/M10.0 等直接 I/O）透传，由 EdgeLite 决定是否支持。"""
        result = _translate_point_address("s7", "M10.0", "bool")
        assert result == {"address": "M10.0"}

    def test_plugin_name_siemens_s7_translates(self):
        """EdgeLite plugin_name 'siemens_s7' 也能正确识别为 S7 协议。"""
        result = _translate_point_address("siemens_s7", "DB1.DBD2", "float32")
        assert result == {"address": "DB1.D2"}

    def test_empty_s7_address(self):
        result = _translate_point_address("s7", "", "float32")
        assert result == {"address": ""}


# ---------------------------------------------------------------------------
#  其他协议透传
# ---------------------------------------------------------------------------


class TestOtherProtocolsPassthrough:
    """OPC-UA/MQTT/HTTP 等协议 address 透传（无协议特定字段）。"""

    def test_opcua_node_id_passthrough(self):
        result = _translate_point_address("opcua", "ns=2;s=Temperature", "float32")
        assert result == {"address": "ns=2;s=Temperature"}
        assert "register_type" not in result

    def test_opcua_device_id_prefix(self):
        """带 device_id 时字符串 NodeId 加设备前缀（与 OPC-UA 服务端命名一致）。"""
        result = _translate_point_address(
            "opcua", "ns=2;s=Temperature", "float32", device_id="plc01"
        )
        assert result == {"address": "ns=2;s=plc01.Temperature"}
        assert "register_type" not in result

    def test_opcua_no_device_id_no_prefix(self):
        result = _translate_point_address("opcua", "ns=2;s=Temperature", "float32")
        assert result == {"address": "ns=2;s=Temperature"}

    def test_opcua_non_string_nodeid_no_prefix(self):
        """数字 NodeId（ns=2;i=5）不加设备前缀。"""
        result = _translate_point_address(
            "opcua", "ns=2;i=5", "float32", device_id="plc01"
        )
        assert result == {"address": "ns=2;i=5"}

    def test_mqtt_topic_passthrough(self):
        result = _translate_point_address("mqtt", "protoforge/data/temp", "float32")
        assert result == {"address": "protoforge/data/temp"}
        assert "register_type" not in result

    def test_http_path_passthrough(self):
        result = _translate_point_address("http", "/points/temp", "float32")
        assert result == {"address": "/points/temp"}

    def test_unknown_protocol_passthrough(self):
        result = _translate_point_address("unknown_proto", "123", "float32")
        assert result == {"address": "123"}


# ---------------------------------------------------------------------------
#  FINS 地址翻译
# ---------------------------------------------------------------------------


class TestFinsAddressTranslation:
    """FINS 地址按点位 data_type 附加 EdgeLite 驱动的类型后缀。

    EdgeLite 的 FINS 驱动 ``_parse_address`` 默认按 word(w) 解析，float/int
    点位不加后缀会拿到原始字节。翻译层需按 data_type 附加 ",r"/",i"/",dw" 等。
    """

    @pytest.mark.parametrize(
        "data_type,expected_suffix",
        [
            ("float32", "r"),
            ("float64", "r"),
            ("int16", "i"),
            ("uint16", "w"),
            ("int32", "dw"),
            ("uint32", "dw"),
            ("bool", "b"),
            ("string", "str"),
        ],
    )
    def test_data_type_suffix_appended(self, data_type, expected_suffix):
        result = _translate_point_address("fins", "D100", data_type)
        assert result == {"address": f"D100,{expected_suffix}"}

    def test_unknown_data_type_no_suffix(self):
        result = _translate_point_address("fins", "D100", "unknown_type")
        assert result == {"address": "D100"}

    def test_existing_suffix_not_duplicated(self):
        """地址已带后缀时透传，不二次追加。"""
        result = _translate_point_address("fins", "D100,r", "float32")
        assert result == {"address": "D100,r"}

    def test_empty_address_passthrough(self):
        result = _translate_point_address("fins", "", "float32")
        assert result == {"address": ""}

    def test_plugin_name_omron_fins(self):
        result = _translate_point_address("omron_fins", "D200", "int16")
        assert result == {"address": "D200,i"}


# ---------------------------------------------------------------------------
#  _build_points 集成
# ---------------------------------------------------------------------------


class TestBuildPointsIntegration:
    """_build_points 端到端：协议感知地构建点位列表。"""

    def test_modbus_bool_point_gets_register_type(self):
        points = [
            {"name": "coolant_on", "data_type": "bool", "address": "4", "access": "rw"},
            {"name": "temperature", "data_type": "float32", "address": "100", "access": "ro"},
        ]
        result = _build_points(points, protocol="modbus_tcp")
        assert len(result) == 2

        # bool + auto → coil（输出带 C 前缀）
        coolant = result[0]
        assert coolant["name"] == "coolant_on"
        assert coolant["address"] == "C4"
        assert coolant["register_type"] == "coil"
        assert coolant["data_type"] == "bool"
        assert coolant["access_mode"] == "rw"

        # float32 + auto → holding（输出带 HR 前缀）
        temp = result[1]
        assert temp["address"] == "HR100"
        assert temp["register_type"] == "holding"

    def test_modbus_explicit_coil_prefix(self):
        points = [{"name": "pump", "data_type": "bool", "address": "C8", "access": "rw"}]
        result = _build_points(points, protocol="modbus_tcp")
        assert result[0]["address"] == "C8"
        assert result[0]["register_type"] == "coil"

    def test_s7_points_translated(self):
        points = [
            {"name": "speed", "data_type": "float32", "address": "DB1.DBD2", "access": "ro"},
            {"name": "running", "data_type": "bool", "address": "DB1.DBX0.0", "access": "ro"},
        ]
        result = _build_points(points, protocol="s7")
        assert result[0]["address"] == "DB1.D2"
        assert result[1]["address"] == "DB1.X0.0"
        # S7 不输出 register_type
        assert "register_type" not in result[0]
        assert "register_type" not in result[1]

    def test_opcua_points_passthrough(self):
        points = [{"name": "temp", "data_type": "float32", "address": "ns=2;s=Temp", "access": "ro"}]
        result = _build_points(points, protocol="opcua")
        assert result[0]["address"] == "ns=2;s=Temp"
        assert "register_type" not in result[0]

    def test_backward_compat_no_protocol(self):
        """未传 protocol 时（向后兼容）退化为透传，不输出 register_type。"""
        points = [{"name": "temp", "data_type": "float32", "address": "100", "access": "rw"}]
        result = _build_points(points)
        assert result[0]["address"] == "100"
        assert "register_type" not in result[0]

    def test_min_max_propagated(self):
        points = [{"name": "p", "data_type": "float32", "address": "10",
                   "access": "rw", "min_value": 0.0, "max_value": 100.0}]
        result = _build_points(points, protocol="modbus_tcp")
        assert result[0]["min"] == 0.0
        assert result[0]["max"] == 100.0
