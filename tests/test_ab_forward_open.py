"""Regression tests for AB/EtherNet-IP CIP response framing.

Focus: ``_wrap_cip_response`` must emit a spec-compliant SendRRData response
where the Null Address Item has Length=0 and NO trailing data. The previous
implementation wrote Length=4 plus 4 zero bytes, shifting the whole CIP
payload by +4 bytes — pylogix then read GeneralStatus at fixed offset 42 from
misaligned bytes and Forward Open always failed.
"""

from __future__ import annotations

import struct

from protoforge.protocols.ab.server import AbServer

EIP_HEADER_SIZE = 24  # cmd(2)+len(2)+session(4)+status(4)+context(8)+options(4)


def _parse_items(resp: bytes) -> list[tuple[int, bytes]]:
    """Parse the SendRRData item list exactly like a client (pylogix) does."""
    offset = EIP_HEADER_SIZE + 4 + 2  # Interface Handle + Timeout
    item_count = struct.unpack("<H", resp[offset:offset + 2])[0]
    offset += 2
    items = []
    for _ in range(item_count):
        item_type = struct.unpack("<H", resp[offset:offset + 2])[0]
        item_len = struct.unpack("<H", resp[offset + 2:offset + 4])[0]
        offset += 4
        items.append((item_type, resp[offset:offset + item_len]))
        offset += item_len
    return items


class TestWrapCipResponseFraming:
    """Null Address Item 结构回归（原 bug：Length=4 + 4 字节零，CIP 整体偏移 +4）。"""

    def setup_method(self):
        self.server = AbServer()

    def test_null_address_item_has_no_data(self):
        cip_data = bytes(range(20))
        resp = self.server._wrap_cip_response(1, cip_data)
        items = _parse_items(resp)

        assert len(items) == 2
        item1_type, item1_data = items[0]
        assert item1_type == 0x0000          # Null Address
        assert item1_data == b""             # Length = 0, no data（回归点）

    def test_cip_data_starts_at_offset_40(self):
        """CIP 数据必须紧跟 Item2 头部（offset 40），不得有 +4 空隙。"""
        cip_data = b"\xAB\xCD\xEF\x01" * 3
        resp = self.server._wrap_cip_response(1, cip_data)
        items = _parse_items(resp)

        item2_type, item2_data = items[1]
        assert item2_type == 0x00B2          # Unconnected Data
        assert item2_data == cip_data        # 内容逐字节一致
        # Item2 在 resp 中的起始位置 = 36（40-4 header）之后紧跟数据
        assert resp[40:40 + len(cip_data)] == cip_data

    def test_total_length_has_no_extra_padding(self):
        """响应总长 = 24(EIP头) + 8(接口句柄+超时+项数) + 8(两个 Item 头) + CIP 长度。"""
        cip_data = bytes(12)
        resp = self.server._wrap_cip_response(1, cip_data)
        assert len(resp) == 40 + len(cip_data)

        eip_len = struct.unpack("<H", resp[2:4])[0]
        assert eip_len == len(resp) - 24

    def test_forward_open_echo_fields_at_fixed_offsets(self):
        """Forward Open 应答中 O->T Connection ID 必须出现在 offset 44
        （CIP 数据 offset 40 + 应答内偏移 4）。旧实现因 +4 偏移会落在 48。"""
        session = 0x11223344
        o_t_conn_id = 0xDEADBEEF
        # Service(1)+PathSize(1)+Priority(1)+TimeoutTicks(1)+O->T ConnID(4)，
        # 处理器跳过 4 字节后从 offset 4 读 ConnID
        request = bytes([0x54, 0x00, 0x00, 0x00]) + struct.pack("<I", o_t_conn_id)
        request += b"\x00" * 16  # 其余字段填充
        resp = self.server._handle_cip_forward_open(session, request)

        # CIP 应答布局: service(1)+reserved(1)+status(1)+extra(1)+O->T ConnID(4)
        assert struct.unpack("<I", resp[44:48])[0] == o_t_conn_id
        # pylogix 固定在 offset 42 读 GeneralStatus —— 必须是应答的 status 字节
        assert resp[42] == 0x00              # Success

    def test_session_and_sender_context_echoed(self):
        cip_data = bytes(8)
        context = bytes(range(8))
        resp = self.server._wrap_cip_response(0x55667788, cip_data, context)

        assert struct.unpack("<I", resp[4:8])[0] == 0x55667788
        assert resp[12:20] == context   # EIP 头: cmd(2)+len(2)+session(4)+status(4)+context(8)

    def test_large_forward_open_5b(self):
        """0x5B Large Forward Open（pylogix>=1.1 ConnectionSize>511）：
        响应 Service=0xDB，Params 按 4 字节解析与回显。"""
        o_t_conn_id = 0x00000033
        request_cip = (
            bytes([0x5B, 0x00])                       # Large Forward Open + PathSize=0
            + bytes([0x00, 0x00])                     # Priority + TimeoutTicks
            + struct.pack("<I", o_t_conn_id)          # O->T ConnID
            + struct.pack("<I", 0x00000002)           # T->O ConnID
            + struct.pack("<H", 0x0001)               # Conn Serial
            + struct.pack("<H", 0x0001)               # Vendor ID
            + struct.pack("<I", 0x00000001)           # Orig Serial
            + struct.pack("<I", 0x00010000)           # O->T RPI
            + struct.pack("<I", 0x00010000)           # T->O RPI
            + struct.pack("<I", 0x00004302)           # O->T Params (4 bytes)
            + struct.pack("<I", 0x00004302)           # T->O Params (4 bytes)
            + bytes([0xA3, 0x00])                     # TransportType + ConnPathSize
        )
        server = AbServer()
        resp = server._handle_cip_forward_open(7, request_cip, large=True)

        items = _parse_items(resp)
        assert items[0] == (0x0000, b"")
        cip_reply = items[1][1]
        assert cip_reply[0] == 0xDB           # Large Forward Open Response (0x5B|0x80)
        assert cip_reply[2] == 0x00           # GeneralStatus = Success
        assert struct.unpack("<I", cip_reply[4:8])[0] == o_t_conn_id
        # CIP 应答布局: svc(1)+res(1)+status(1)+extra(1)+O->T(4)+T->O(4)
        #              +serial(2)+vendor(2)+orig(4)+RPI(4)+RPI(4)+Params(4)
        assert struct.unpack("<I", cip_reply[28:32])[0] == 0x00004302

    def test_send_rr_data_dispatches_large_forward_open(self):
        """SendRRData 请求的 Service=0x5B 应路由到 Large Forward Open 处理。"""
        request_cip = (
            bytes([0x5B, 0x00, 0x00, 0x00])
            + struct.pack("<I", 0x00000009)
            + b"\x00" * 20
        )
        req = bytearray()
        req += struct.pack("<H", 0x006F) + struct.pack("<H", 0)
        req += struct.pack("<I", 7) + struct.pack("<I", 0) + bytes(8)
        req += struct.pack("<I", 0)          # Options (EIP header 24 字节收尾)
        req += struct.pack("<I", 0)          # Interface Handle
        req += struct.pack("<H", 0)          # Timeout
        req += struct.pack("<H", 2)
        req += struct.pack("<H", 0x0000) + struct.pack("<H", 0)
        req += struct.pack("<H", 0x00B2) + struct.pack("<H", len(request_cip))
        req += request_cip
        req[2:4] = struct.pack("<H", len(req) - 24)

        server = AbServer()
        resp = server._handle_send_rr_data(bytes(req))
        items = _parse_items(resp)
        assert items[1][1][0] == 0xDB

    def test_roundtrip_through_send_rr_data_handler(self):
        """端到端：构造 SendRRData 请求 → Forward Open → 应答可被同一 Item
        解析逻辑还原出合法 CIP 应答（无错位）。"""
        o_t_conn_id = 0x0000002A
        request_cip = (
            bytes([0x54, 0x00])                       # Forward Open + PathSize=0
            + bytes([0x00, 0x00])                     # Priority + TimeoutTicks
            + struct.pack("<I", o_t_conn_id)          # O->T ConnID
            + struct.pack("<I", 0x00000002)           # T->O ConnID
            + struct.pack("<H", 0x0001)               # Conn Serial
            + struct.pack("<H", 0x0001)               # Vendor ID
            + struct.pack("<I", 0x00000001)           # Orig Serial
            + struct.pack("<I", 0x00010000)           # O->T RPI
            + struct.pack("<I", 0x00010000)           # T->O RPI
            + struct.pack("<H", 0x4302)               # O->T Params
            + struct.pack("<H", 0x4302)               # T->O Params
            + bytes([0xA3, 0x00])                     # TransportType + ConnPathSize
        )
        # 组 SendRRData 请求: EIP 头 + Interface Handle + Timeout + ItemCount + Items
        req = bytearray()
        req += struct.pack("<H", 0x006F)
        req += struct.pack("<H", 0)
        req += struct.pack("<I", 7)
        req += struct.pack("<I", 0)
        req += bytes(8)
        req += struct.pack("<I", 0)
        req += struct.pack("<I", 0)          # Interface Handle
        req += struct.pack("<H", 0)          # Timeout
        req += struct.pack("<H", 2)          # Item Count
        req += struct.pack("<H", 0x0000) + struct.pack("<H", 0)   # Null Address, len 0
        req += struct.pack("<H", 0x00B2) + struct.pack("<H", len(request_cip))
        req += request_cip
        req[2:4] = struct.pack("<H", len(req) - 24)

        server = AbServer()
        resp = server._handle_send_rr_data(bytes(req), sender_context=bytes(8))

        items = _parse_items(resp)
        assert items[0] == (0x0000, b"")      # Null Address 无数据（回归点）
        assert items[1][0] == 0x00B2
        cip_reply = items[1][1]
        assert cip_reply[0] == 0xD4           # Forward Open Response (0x54|0x80)
        assert cip_reply[2] == 0x00           # GeneralStatus = Success
        assert struct.unpack("<I", cip_reply[4:8])[0] == o_t_conn_id
