"""报文字段级解析器（v1.9.0）— Wireshark 式逐字段展开。

输入协议名 + 原始报文字节，输出字段树（名称/偏移/长度/原文/可读值/子字段），
用于排查"线上到底发了什么"：联调排障、驱动开发、教学演示。

覆盖 9 种协议（与 ProtoForge 自身实现严格一致，黄金用例门禁背书）：
modbus_tcp / modbus_rtu / s7 / iec104 / dlt645 / cjt188 / fins / mc / mewtocol。

所有解码器对截断帧容错：能解多少解多少，剩余部分记入 errors。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class FrameField:
    """帧内一个字段：偏移/长度/原文/可读值，可嵌套子字段。"""

    name: str
    offset: int
    length: int
    raw: str            # 原文字节 hex
    value: str          # 人类可读值
    note: str = ""      # 语义注解（功能码含义等）
    children: list["FrameField"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "offset": self.offset, "length": self.length,
            "raw": self.raw, "value": self.value, "note": self.note,
            "children": [c.to_dict() for c in self.children],
        }


def decode_frame(protocol: str, data: bytes) -> dict[str, Any]:
    """解析单帧报文。未知协议抛 ValueError，坏帧返回 errors 列表。"""
    decoder = _DECODERS.get(str(protocol).lower())
    if decoder is None:
        raise ValueError(
            f"Unsupported protocol for frame decoding: {protocol}. "
            f"Supported: {', '.join(sorted(_DECODERS))}")
    fields, summary, errors = decoder(data)
    return {
        "protocol": protocol.lower(),
        "length": len(data),
        "hex": data.hex(" "),
        "summary": summary,
        "fields": [f.to_dict() for f in fields],
        "errors": errors,
    }


def supported_protocols() -> list[str]:
    return sorted(_DECODERS.keys())


def _f(name: str, data: bytes, offset: int, length: int, value: str,
       note: str = "", children: list[FrameField] | None = None) -> FrameField:
    chunk = data[offset:offset + length]
    return FrameField(name=name, offset=offset, length=length,
                      raw=chunk.hex(" "), value=value, note=note,
                      children=children or [])


# ---------------------------------------------------------------------------
#  Modbus TCP
# ---------------------------------------------------------------------------

_MB_FC_NAMES = {
    1: "Read Coils", 2: "Read Discrete Inputs", 3: "Read Holding Registers",
    4: "Read Input Registers", 5: "Write Single Coil", 6: "Write Single Register",
    15: "Write Multiple Coils", 16: "Write Multiple Registers",
}


def _decode_modbus_pdu(data: bytes, offset: int, length: int) -> tuple[str, list[FrameField], list[str]]:
    """解析 Modbus PDU（功能码 + 数据），返回 (summary, fields, errors)。"""
    errors: list[str] = []
    if length < 1:
        return "空 PDU", [], ["PDU 为空"]
    fc = data[offset]
    fc_name = _MB_FC_NAMES.get(fc, "Exception" if fc & 0x80 else f"FC {fc}")
    fields = [_f("Function Code", data, offset, 1, f"0x{fc:02X}", fc_name)]
    body = data[offset + 1:offset + length]
    if fc & 0x80 and body:
        fields.append(_f("Exception Code", data, offset + 1, 1, f"0x{body[0]:02X}",
                         f"异常码 {body[0]}"))
        return f"Modbus 异常响应 {fc_name}", fields, errors
    if fc in (1, 2, 3, 4) and body:
        # 请求体 = addr(2)+count(2)（恒 4 字节）；响应体 = byte_count(1)+数据
        # （长度 1+2n 恒为奇数，与请求长度 4 不可能撞车，可无歧义判定）。
        if len(body) == 4:
            addr = struct.unpack(">H", body[0:2])[0]
            count = struct.unpack(">H", body[2:4])[0]
            fields.append(_f("Start Address", data, offset + 1, 2, str(addr)))
            fields.append(_f("Quantity", data, offset + 3, 2, str(count)))
            return f"{fc_name} addr={addr} count={count}", fields, errors
        if body[0] == len(body) - 1:
            bc = body[0]
            fields.append(_f("Byte Count", data, offset + 1, 1, str(bc)))
            return f"{fc_name} 响应 {bc} 字节数据", fields, errors
        if len(body) >= 4:
            addr = struct.unpack(">H", body[0:2])[0]
            count = struct.unpack(">H", body[2:4])[0]
            fields.append(_f("Start Address", data, offset + 1, 2, str(addr)))
            fields.append(_f("Quantity", data, offset + 3, 2, str(count)))
            return f"{fc_name} addr={addr} count={count}", fields, errors
        return f"{fc_name}（数据段不完整）", fields, errors
    if fc in (5, 6) and len(body) >= 4:
        addr = struct.unpack(">H", body[0:2])[0]
        val = struct.unpack(">H", body[2:4])[0]
        fields.append(_f("Address", data, offset + 1, 2, str(addr)))
        fields.append(_f("Value", data, offset + 3, 2,
                         str(val) if fc == 6 else ("ON" if val else "OFF")))
        return f"{fc_name} addr={addr} value={val}", fields, errors
    if fc in (15, 16) and len(body) >= 5:
        addr = struct.unpack(">H", body[0:2])[0]
        count = struct.unpack(">H", body[2:4])[0]
        bc = body[4]
        fields.append(_f("Start Address", data, offset + 1, 2, str(addr)))
        fields.append(_f("Quantity", data, offset + 3, 2, str(count)))
        fields.append(_f("Byte Count", data, offset + 5, 1, str(bc)))
        return f"{fc_name} addr={addr} count={count}", fields, errors
    return f"FC 0x{fc:02X}", fields, errors


def _decode_modbus_tcp(data: bytes) -> tuple[list[FrameField], str, list[str]]:
    errors: list[str] = []
    fields: list[FrameField] = []
    if len(data) < 7:
        return fields, "MBAP 头不完整", [f"帧长 {len(data)} < 7"]
    tx = struct.unpack(">H", data[0:2])[0]
    proto = struct.unpack(">H", data[2:4])[0]
    length = struct.unpack(">H", data[4:6])[0]
    unit = data[6]
    if proto != 0:
        errors.append(f"Protocol ID 应为 0，实际 {proto}")
    if length != len(data) - 6:
        errors.append(f"MBAP length 声明 {length}，实际 {len(data) - 6}")
    pdu_summary, pdu_fields, pdu_errors = _decode_modbus_pdu(data, 7, length - 1)
    errors.extend(pdu_errors)
    fields += [
        _f("Transaction ID", data, 0, 2, f"0x{tx:04X}"),
        _f("Protocol ID", data, 2, 2, str(proto)),
        _f("Length", data, 4, 2, str(length)),
        _f("Unit ID", data, 6, 1, str(unit)),
        FrameField(name="PDU", offset=7, length=length - 1,
                   raw=data[7:7 + length - 1].hex(" "), value=pdu_summary,
                   children=pdu_fields),
    ]
    return fields, f"Modbus TCP {pdu_summary} (unit={unit}, tx={tx})", errors


# ---------------------------------------------------------------------------
#  Modbus RTU
# ---------------------------------------------------------------------------

def _crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def _decode_modbus_rtu(data: bytes) -> tuple[list[FrameField], str, list[str]]:
    errors: list[str] = []
    fields: list[FrameField] = []
    if len(data) < 4:
        return fields, "RTU 帧不完整", [f"帧长 {len(data)} < 4"]
    addr = data[0]
    pdu_summary, pdu_fields, pdu_errors = _decode_modbus_pdu(data, 1, len(data) - 3)
    errors.extend(pdu_errors)
    fields.append(_f("Slave Address", data, 0, 1, str(addr)))
    fields.append(FrameField(name="PDU", offset=1, length=len(data) - 3,
                             raw=data[1:len(data) - 2].hex(" "), value=pdu_summary,
                             children=pdu_fields))
    crc_calc = _crc16_modbus(data[:-2])
    crc_recv = struct.unpack("<H", data[-2:])[0]
    fields.append(_f("CRC16", data, len(data) - 2, 2, f"0x{crc_recv:04X}",
                     "低字节在前"))
    if crc_calc != crc_recv:
        errors.append(f"CRC 校验失败: 计算 0x{crc_calc:04X} ≠ 帧内 0x{crc_recv:04X}")
    else:
        fields[-1].note = "低字节在前 ✓ 校验通过"
    return fields, f"Modbus RTU {pdu_summary} (addr={addr})", errors


# ---------------------------------------------------------------------------
#  S7 (ISO-on-TCP)
# ---------------------------------------------------------------------------

_COTP_TYPES = {0xE0: "CR (Connection Request)", 0xD0: "CC (Connection Confirm)",
               0xF0: "DT (Data)", 0x08: "DR (Disconnect Request)"}


def _decode_s7(data: bytes) -> tuple[list[FrameField], str, list[str]]:
    errors: list[str] = []
    if len(data) < 7:
        return [], "TPKT 不完整", [f"帧长 {len(data)} < 7"]
    tpkt_len = struct.unpack(">H", data[2:4])[0]
    fields = [_f("TPKT Version", data, 0, 1, f"0x{data[0]:02X}"),
              _f("TPKT Reserved", data, 1, 1, f"0x{data[1]:02X}"),
              _f("TPKT Length", data, 2, 2, str(tpkt_len))]
    if tpkt_len != len(data):
        errors.append(f"TPKT length 声明 {tpkt_len}，实际 {len(data)}")
    li = data[4]
    cotp_type = data[5]
    fields.append(_f("COTP LI", data, 4, 1, str(li)))
    fields.append(_f("COTP PDU Type", data, 5, 1, f"0x{cotp_type:02X}",
                     _COTP_TYPES.get(cotp_type, "未知")))
    if cotp_type != 0xF0:
        return fields, f"S7 COTP {_COTP_TYPES.get(cotp_type, hex(cotp_type))}", errors
    if len(data) < 17:
        return fields, "S7 头不完整", ["TPKT+COTP 之后不足 10 字节"]
    s7_fields = [
        _f("Protocol ID", data, 7, 1, f"0x{data[7]:02X}", "应为 0x32"),
        _f("ROSCTR", data, 8, 1, str(data[8]),
           {1: "Job", 2: "Ack", 3: "Ack_Data", 7: "Userdata"}.get(data[8], "未知")),
        _f("Redundancy", data, 9, 2, "0x0000"),
        _f("PDU Reference", data, 11, 2, f"0x{struct.unpack('>H', data[11:13])[0]:04X}"),
        _f("Param Length", data, 13, 2, str(struct.unpack(">H", data[13:15])[0])),
        _f("Data Length", data, 15, 2, str(struct.unpack(">H", data[15:17])[0])),
    ]
    if data[8] == 3 and len(data) >= 19:  # Ack_Data 带 err class/code
        s7_fields.append(_f("Error Class", data, 17, 1, str(data[17])))
        s7_fields.append(_f("Error Code", data, 18, 1, str(data[18])))
    func = data[17] if data[8] == 1 else (data[19] if len(data) > 19 else 0)
    func_note = {0xF0: "Setup Communication", 0x04: "Read Var",
                 0x05: "Write Var"}.get(func, f"0x{func:02X}")
    s7_fields.append(_f("Function", data, 17 if data[8] == 1 else 19, 1, func_note))
    summary = f"S7 {func_note} ({ {1: 'Job', 3: 'Ack_Data'}.get(data[8], 'ROSCTR=' + str(data[8])) })"
    fields.append(FrameField(name="S7 PDU", offset=7, length=len(data) - 7,
                             raw=data[7:].hex(" "), value=summary, children=s7_fields))
    return fields, summary, errors


# ---------------------------------------------------------------------------
#  IEC 60870-5-104
# ---------------------------------------------------------------------------

_TI104_NAMES = {1: "M_SP_NA_1 单点遥信", 3: "M_DP_NA_1 双点遥信",
                9: "M_ME_NA_1 归一化遥测", 11: "M_ME_NB_1 标度化遥测",
                13: "M_ME_NC_1 短浮点遥测", 45: "C_SC_NA_1 单点遥控",
                46: "C_DC_NA_1 双点遥控", 49: "C_SE_NB_1 标度化遥调",
                50: "C_SE_NC_1 浮点遥调", 100: "C_IC_NA_1 总召",
                103: "C_CS_NA_1 时钟同步"}
_OBJ_SIZES = {1: 1, 3: 1, 9: 3, 11: 3, 13: 5, 45: 1, 46: 1, 49: 3, 50: 5,
              100: 1, 103: 7}
_COT_NAMES = {1: "周期", 2: "背景扫", 3: "突发", 6: "激活", 7: "激活确认",
              8: "停止激活", 9: "停止激活确认", 10: "激活终止", 20: "响应总召",
              44: "未知类型", 45: "未知原因", 46: "未知 CA"}


def _decode_iec104(data: bytes) -> tuple[list[FrameField], str, list[str]]:
    errors: list[str] = []
    if len(data) < 6 or data[0] != 0x68:
        return [], "非 104 APDU", ([] if not data else [f"起始字节 0x{data[0]:02X} ≠ 0x68"])
    apdu_len = data[1]
    fields = [_f("Start", data, 0, 1, "0x68"),
              _f("APDU Length", data, 1, 1, str(apdu_len))]
    if apdu_len != len(data) - 2:
        errors.append(f"APDU length 声明 {apdu_len}，实际 {len(data) - 2}")
    c1 = data[2]
    if c1 & 0x03 == 0x03:  # U-格式
        u_names = {0x07: "STARTDT_ACT", 0x0B: "STARTDT_CON", 0x13: "STOPDT_ACT",
                   0x23: "STOPDT_CON", 0x43: "TESTFR_ACT", 0x83: "TESTFR_CON"}
        fields.append(_f("Control (U-format)", data, 2, 4,
                         u_names.get(c1, f"0x{c1:02X}")))
        return fields, f"104 U-格式 {u_names.get(c1, hex(c1))}", errors
    if c1 & 0x01:  # S-格式
        vr = struct.unpack("<H", data[4:6])[0] >> 1
        fields.append(_f("Control (S-format)", data, 2, 4, f"确认接收序号 VR={vr}"))
        return fields, f"104 S-格式 (VR={vr})", errors
    # I-格式
    vs = struct.unpack("<H", data[2:4])[0] >> 1
    vr = struct.unpack("<H", data[4:6])[0] >> 1
    fields.append(_f("Control (I-format)", data, 2, 4, f"VS={vs} VR={vr}"))
    if len(data) < 10:
        return fields, "104 I-格式（无 ASDU）", errors
    asdu = data[6:]
    ti = asdu[0]
    vsq = asdu[1]
    cot = asdu[2] & 0x3F
    ca = struct.unpack("<H", asdu[4:6])[0]
    num = vsq & 0x7F
    asdu_fields = [
        _f("TI 类型标识", asdu, 0, 1, str(ti), _TI104_NAMES.get(ti, "未知")),
        _f("VSQ", asdu, 1, 1, f"n={num} sq={bool(vsq & 0x80)}"),
        _f("COT 传送原因", asdu, 2, 1, str(cot), _COT_NAMES.get(cot, "")),
        _f("OA 源发地址", asdu, 3, 1, str(asdu[3])),
        _f("CA 公共地址", asdu, 4, 2, str(ca), "小端"),
    ]
    offset = 6
    obj_size = _OBJ_SIZES.get(ti)
    shown = 0
    while offset < len(asdu) and shown < 8:
        ioa = asdu[offset] | asdu[offset + 1] << 8 | (asdu[offset + 2] << 16 if offset + 2 < len(asdu) else 0)
        obj_fields = [_f("IOA", asdu, offset, 3, str(ioa), "3 字节小端")]
        if obj_size and offset + 3 + obj_size <= len(asdu):
            val_off = offset + 3
            payload = asdu[val_off:val_off + obj_size]
            if ti == 1:
                obj_fields.append(_f("SPI 单点信息", asdu, val_off, 1,
                                     "合" if payload[0] & 1 else "分"))
            elif ti == 3:
                obj_fields.append(_f("DPI 双点信息", asdu, val_off, 1,
                                     {0: "不确定", 1: "分", 2: "合", 3: "不确定"}.get(payload[0] & 3, "?")))
            elif ti in (9, 11):
                obj_fields.append(_f("值", asdu, val_off, 2,
                                     str(struct.unpack("<h", payload[0:2])[0])))
                obj_fields.append(_f("QDS 品质", asdu, val_off + 2, 1, f"0x{payload[2]:02X}"))
            elif ti == 13:
                obj_fields.append(_f("浮点值", asdu, val_off, 4,
                                     f"{struct.unpack('<f', payload[0:4])[0]:g}"))
                obj_fields.append(_f("QDS 品质", asdu, val_off + 4, 1, f"0x{payload[4]:02X}"))
            elif ti == 100:
                obj_fields.append(_f("QOI", asdu, val_off, 1, str(payload[0])))
            elif ti == 45:
                obj_fields.append(_f("SCO", asdu, val_off, 1,
                                     ("选择+执行" if payload[0] & 0x80 else "执行")
                                     + (" 合" if payload[0] & 1 else " 分")))
        asdu_fields.append(FrameField(
            name=f"信息对象 {shown + 1}" if num > 1 else "信息对象",
            offset=6 + offset, length=min(3 + (obj_size or 0), len(asdu) - offset),
            raw=asdu[offset:offset + 3 + (obj_size or 0)].hex(" "),
            value=f"IOA={ioa}", children=obj_fields))
        offset += 3 + (obj_size or 0)
        shown += 1
    if obj_size and offset < len(asdu):
        errors.append("ASDU 尾部有剩余字节（SQ 压缩编址或多对象未展开）")
    cot_txt = _COT_NAMES.get(cot, str(cot))
    summary = f"104 I-格式 {_TI104_NAMES.get(ti, f'TI={ti}')} COT={cot_txt} CA={ca} n={num}"
    fields.append(FrameField(name="ASDU", offset=6, length=len(asdu),
                             raw=asdu.hex(" "), value=summary, children=asdu_fields))
    return fields, summary, errors


# ---------------------------------------------------------------------------
#  DL/T 645-2007
# ---------------------------------------------------------------------------

def _decode_dlt645(data: bytes) -> tuple[list[FrameField], str, list[str]]:
    errors: list[str] = []
    fields: list[FrameField] = []
    if len(data) < 12 or data[0] != 0x68:
        return fields, "非 645 帧", ([] if not data else [f"起始字节 0x{data[0]:02X} ≠ 0x68"])
    # 地址变体检测（与服务端一致）：6 字节地址后第二个 0x68；或 A6=~A5 后再 0x68
    if data[7] == 0x68:
        has_a6, ctrl_off = False, 8
    elif len(data) >= 10 and data[8] == 0x68:
        has_a6, ctrl_off = True, 9
    else:
        return fields, "DL/T 645 帧（缺第二起始符）", ["偏移 7/8 处均无 0x68"]
    addr_bcd = data[1:7]
    addr_str = "".join(f"{b >> 4}{b & 0xF}" for b in reversed(addr_bcd))
    ctrl = data[ctrl_off]
    length = data[ctrl_off + 1]
    fields += [
        _f("帧起始符", data, 0, 1, "0x68"),
        _f("地址域 A0~A5", data, 1, 6, addr_str, "BCD 小端（表号低位在前）"),
    ]
    if has_a6:
        fields.append(_f("地址补码 A6", data, 7, 1, f"0x{data[7]:02X}",
                         "~A5（7 字节地址变体）"))
    else:
        fields.append(_f("帧起始符 2", data, 7, 1, "0x68"))
    fields += [
        _f("控制码 C", data, ctrl_off, 1, f"0x{ctrl:02X}",
           f"{'从站应答' if ctrl >> 7 else '主站请求'} 功能 {ctrl & 0x1F}"),
        _f("数据域长度 L", data, ctrl_off + 1, 1, str(length)),
    ]
    data_start = ctrl_off + 2
    cs_off = data_start + length
    end_off = cs_off + 1
    if len(data) < end_off + 1:
        errors.append("帧长不足（数据域/校验/结束符不完整）")
        return fields, "DL/T 645 帧（截断）", errors
    if length >= 2:
        di_raw = data[data_start:data_start + 2]
        di = di_raw[::-1].hex().upper()  # DI 小端 → 正序
        fields.append(_f("数据标识 DI", data, data_start, 2, di,
                         {"00010000": "当前正向有功总电能", "02010100": "A相电压",
                          "02020100": "A相电流", "04000101": "当前正向有功功率"}.get(di, "")))
    if length > 2:
        fields.append(_f("数据内容", data, data_start + 2, length - 2,
                         data[data_start + 2:cs_off].hex(" "),
                         "传输时字节 +0x33 隐藏"))
    cs_calc = sum(data[1:cs_off]) & 0xFF
    cs_recv = data[cs_off]
    fields.append(_f("校验和 CS", data, cs_off, 1, f"0x{cs_recv:02X}"))
    fields.append(_f("帧结束符", data, end_off, 1, f"0x{data[end_off]:02X}",
                     "应为 0x16"))
    if data[end_off] != 0x16:
        errors.append(f"结束符 0x{data[end_off]:02X} ≠ 0x16")
    if cs_calc != cs_recv:
        errors.append(f"CS 校验失败: 计算 0x{cs_calc:02X} ≠ 帧内 0x{cs_recv:02X}")
    return fields, f"DL/T 645 表号 {addr_str} 控制码 0x{ctrl:02X}", errors


# ---------------------------------------------------------------------------
#  CJ/T 188-2004
# ---------------------------------------------------------------------------

def _decode_cjt188(data: bytes) -> tuple[list[FrameField], str, list[str]]:
    errors: list[str] = []
    fields: list[FrameField] = []
    if len(data) < 15 or data[0] != 0x68:
        return fields, "非 188 帧", ([] if not data else [f"起始字节 0x{data[0]:02X} ≠ 0x68"])
    addr_bcd = data[1:8]
    addr_str = "".join(f"{b >> 4}{b & 0xF}" for b in reversed(addr_bcd))
    ctrl = data[8]
    length = data[9]
    fields += [
        _f("帧起始符", data, 0, 1, "0x68"),
        _f("表号地址域", data, 1, 7, addr_str, "BCD 小端"),
        _f("控制码 C", data, 8, 1, f"0x{ctrl:02X}",
           f"D={ctrl >> 7} {'应答' if ctrl >> 7 else '请求'} 功能码 {ctrl & 0x1F}"),
        _f("数据域长度 L", data, 9, 1, str(length)),
    ]
    if len(data) < 10 + length + 2:
        errors.append("帧长不足")
        return fields, "CJ/T 188 帧（截断）", errors
    di_raw = data[10:12]
    di = di_raw[::-1].hex().upper()
    fields.append(_f("数据标识 DI0~DI1", data, 10, 2, di,
                     {"10010090": "水表", "01010090": "当前累计流量"}.get(di, "")))
    if length > 2:
        fields.append(_f("序号/状态等附加", data, 12, length - 2,
                         data[12:10 + length].hex(" ")))
    cs_calc = sum(data[1:10 + length]) & 0xFF
    cs_recv = data[10 + length]
    fields.append(_f("校验和 CS", data, 10 + length, 1, f"0x{cs_recv:02X}"))
    fields.append(_f("帧结束符", data, 11 + length, 1, f"0x{data[11 + length]:02X}"))
    if data[11 + length] != 0x16:
        errors.append(f"结束符 0x{data[11 + length]:02X} ≠ 0x16")
    if cs_calc != cs_recv:
        errors.append(f"CS 校验失败: 计算 0x{cs_calc:02X} ≠ 帧内 0x{cs_recv:02X}")
    return fields, f"CJ/T 188 表号 {addr_str} 控制码 0x{ctrl:02X}", errors


# ---------------------------------------------------------------------------
#  FINS (TCP)
# ---------------------------------------------------------------------------

def _decode_fins(data: bytes) -> tuple[list[FrameField], str, list[str]]:
    errors: list[str] = []
    fields: list[FrameField] = []
    if len(data) < 8 or data[:4] != b"FINS":
        return fields, "非 FINS/TCP 帧", (["缺少 FINS magic"] if data else [])
    body_len = struct.unpack(">I", data[4:8])[0]
    fields += [
        _f("Magic", data, 0, 4, "FINS"),
        _f("Body Length", data, 4, 4, str(body_len)),
    ]
    if body_len != len(data) - 8:
        errors.append(f"body length 声明 {body_len}，实际 {len(data) - 8}")
    body = data[8:]
    if len(body) < 4:
        return fields, "FINS/TCP 帧（body 截断）", errors
    cmd = struct.unpack(">I", body[0:4])[0]
    cmd_names = {0: "节点地址发送 (Client→Server)", 1: "节点地址应答",
                 2: "FINS 帧发送", 3: "FINS 帧应答"}
    fields.append(_f("Command", body, 0, 4, f"0x{cmd:08X}",
                     cmd_names.get(cmd, "未知")))
    if cmd in (0, 1) and len(body) >= 8:
        fields.append(_f("Error Code", body, 4, 4, str(struct.unpack(">I", body[4:8])[0])))
        if len(body) >= 12:
            fields.append(_f("节点地址", body, 8, 4, str(struct.unpack(">I", body[8:12])[0])))
        return fields, f"FINS/TCP {cmd_names.get(cmd, hex(cmd))}", errors
    if cmd in (2, 3):
        if len(body) >= 8:
            fields.append(_f("Error Code", body, 4, 4, str(struct.unpack(">I", body[4:8])[0])))
        frame = body[8:]
        return _decode_fins_datagram(fields, frame, errors)
    # EdgeLite 非标准握手：body 直接是 FINS 帧
    return _decode_fins_datagram(fields, body, errors)


def _decode_fins_datagram(fields: list[FrameField], frame: bytes,
                          errors: list[str]) -> tuple[list[FrameField], str, list[str]]:
    if len(frame) < 12:
        errors.append("FINS 数据报不足 12 字节")
        return fields, "FINS 数据报（截断）", errors
    mrc, src = frame[10], frame[11]
    end_code = struct.unpack(">H", frame[12:14])[0] if len(frame) >= 14 else -1
    dg_fields = [
        _f("ICF", frame, 0, 1, f"0x{frame[0]:02X}", "控制标志"),
        _f("RSV", frame, 1, 1, f"0x{frame[1]:02X}"),
        _f("GCT", frame, 2, 1, str(frame[2])),
        _f("DNA 目标网络", frame, 3, 1, str(frame[3])),
        _f("DA1 目标节点", frame, 4, 1, str(frame[4])),
        _f("DA2 目标单元", frame, 5, 1, str(frame[5])),
        _f("SNA 源网络", frame, 6, 1, str(frame[6])),
        _f("SA1 源节点", frame, 7, 1, str(frame[7])),
        _f("SA2 源单元", frame, 8, 1, str(frame[8])),
        _f("SID 服务号", frame, 9, 1, f"0x{frame[9]:02X}"),
        _f("MRC 主码", frame, 10, 1, f"0x{mrc:02X}",
           {0x01: "内存区读写", 0x05: "控制器状态"}.get(mrc, "")),
        _f("SRC 子码", frame, 11, 1, f"0x{src:02X}",
           {0x01: "读", 0x02: "写"}.get(src, "") if mrc == 0x01 else ""),
    ]
    if end_code >= 0:
        dg_fields.append(_f("End Code", frame, 12, 2, f"0x{end_code:04X}",
                            "0x0000=正常" if end_code == 0 else "异常结束码"))
    dg = FrameField(name="FINS 数据报", offset=0, length=len(frame),
                    raw=frame.hex(" "), value=f"MRC=0x{mrc:02X} SRC=0x{src:02X}",
                    children=dg_fields)
    fields.append(dg)
    action = "读" if (mrc == 0x01 and src == 0x01) else ("写" if (mrc == 0x01 and src == 0x02) else "命令")
    return fields, f"FINS {action}命令 MRC=0x{mrc:02X}/SRC=0x{src:02X}", errors


# ---------------------------------------------------------------------------
#  MC Protocol (SLMP 3E binary)
# ---------------------------------------------------------------------------

_MC_DEVICE_CODES = {0x00: "X", 0x10: "W", 0x90: "D", 0x91: "W(shifted)",
                    0x9B: "SD", 0xA0: "Z", 0xA8: "SW", 0xB0: "TN", 0xB4: "TS",
                    0xC0: "ZN", 0xC2: "CN", 0xE0: "M", 0xE8: "SM"}


def _decode_mc(data: bytes) -> tuple[list[FrameField], str, list[str]]:
    errors: list[str] = []
    fields: list[FrameField] = []
    if len(data) < 11:
        return fields, "MC 3E 帧不完整", [f"帧长 {len(data)} < 11"]
    subheader = struct.unpack(">H", data[0:2])[0]
    if subheader != 0x5000:
        return fields, "MC 非 3E 二进制帧", [f"子头 0x{subheader:04X} ≠ 0x5000"]
    data_len = struct.unpack("<H", data[9:11])[0]
    fields += [
        _f("子头", data, 0, 2, "0x5000", "SLMP 3E 二进制"),
        _f("网络编号", data, 2, 1, str(data[2])),
        _f("PC 编号", data, 3, 1, str(data[3])),
        _f("目标模块 IO", data, 4, 2, f"0x{struct.unpack('<H', data[4:6])[0]:04X}"),
        _f("目标站号", data, 6, 1, str(data[6])),
        _f("请求数据长", data, 7, 2, str(struct.unpack("<H", data[7:9])[0])),
        _f("监视定时器", data, 9, 2, str(struct.unpack("<H", data[9:11])[0])),
    ]
    if len(data) < 15:
        errors.append("帧不足 15 字节，缺命令段")
        return fields, "MC 3E 帧（截断）", errors
    cmd = struct.unpack("<H", data[11:13])[0]
    subcmd = struct.unpack("<H", data[13:15])[0]
    cmd_names = {0x0401: "批量读 (BR)", 0x0402: "随机读 (RR)", 0x1401: "批量写 (BW)",
                 0x1402: "随机写 (RW)", 0x0001: "自环测试"}
    fields.append(_f("命令", data, 11, 2, f"0x{cmd:04X}", cmd_names.get(cmd, "未知")))
    fields.append(_f("子命令", data, 13, 2, f"0x{subcmd:04X}",
                     "iQ-R 模式" if subcmd in (2, 3) else "Q 模式"))
    if cmd in (0x0401, 0x1401) and len(data) >= 19:
        # Q 模式设备字段: 设备号 3B LE + 设备码 1B；iQ-R: 4B + 2B
        if subcmd in (0x0002, 0x0003):
            start_addr = int.from_bytes(data[15:19], "little")
            dev_code = int.from_bytes(data[19:21], "little") if len(data) >= 21 else 0
            dev_note = f"设备号={start_addr} 设备码=0x{dev_code:04X}"
        else:
            start_addr = int.from_bytes(data[15:18], "little")
            dev_code = data[18] if len(data) > 18 else 0
            dev_note = f"设备号={start_addr} 设备码=0x{dev_code:02X}"
        fields.append(_f("设备字段", data, 15, 6 if subcmd in (2, 3) else 4, dev_note,
                         _MC_DEVICE_CODES.get(dev_code, "")))
        if cmd == 0x0401:
            cnt_off = 21 if subcmd in (0x0002, 0x0003) else 19
            if len(data) >= cnt_off + 2:
                cnt = struct.unpack("<H", data[cnt_off:cnt_off + 2])[0]
                fields.append(_f("点数", data, cnt_off, 2, str(cnt)))
    summary = f"MC 3E {cmd_names.get(cmd, hex(cmd))} 子命令 0x{subcmd:04X}"
    return fields, summary, errors


# ---------------------------------------------------------------------------
#  MEWTOCOL (ASCII)
# ---------------------------------------------------------------------------

def _decode_mewtocol(data: bytes) -> tuple[list[FrameField], str, list[str]]:
    errors: list[str] = []
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        return [], "非 MEWTOCOL（含非 ASCII 字节）", ["帧不是 ASCII"]
    fields: list[FrameField] = []
    if not text.startswith("%"):
        return fields, "非 MEWTOCOL 帧", ["起始符应为 '%'"]
    if not text.endswith("\r"):
        errors.append("帧未以 CR(0x0D) 结尾")
    body = text.rstrip("\r")
    bcc_recv = body[-2:]
    bcc_calc = 0
    for ch in body[:-2]:
        bcc_calc ^= ord(ch)
    bcc_ok = f"{bcc_calc:02X}" == bcc_recv.upper()
    if not bcc_ok:
        errors.append(f"BCC 校验失败: 计算 {bcc_calc:02X} ≠ 帧内 {bcc_recv}")
    head = body[0]
    stn = body[1:3]
    kind = body[3]
    kind_names = {"#": "请求", "$": "正常应答", "!": "错误应答"}
    fields += [
        _f("起始符", data, 0, 1, "%"),
        _f("站号", data, 1, 2, stn),
        _f("帧类型", data, 3, 1, kind, kind_names.get(kind, "未知")),
    ]
    cmd = body[4:6]
    cmd_names = {"RD": "读取 DT/WR 数据区", "WD": "写入 DT/WR 数据区",
                 "RC": "读取接点区(X/Y/R/T/C/L)", "WC": "写入接点区",
                 "RT": "读取定时/计数经过值", "WT": "写入定时/计数经过值",
                 "#": "自诊断"}
    if kind == "!":
        fields.append(_f("错误码", data, 4, 2, cmd, "21=BCC 22=格式 40=未定义"))
    else:
        fields.append(_f("命令", data, 4, 2, cmd, cmd_names.get(cmd, "")))
    rest_len = len(body) - 6
    if rest_len > 0:
        fields.append(_f("参数/数据", data, 6, rest_len, body[6:-2]))
    fields.append(_f("BCC", data, len(body) - 2, 2, bcc_recv,
                     "XOR 校验 " + ("✓" if bcc_ok else "✗")))
    return fields, f"MEWTOCOL 站号 {stn} {kind_names.get(kind, '')} {cmd}", errors


# ---------------------------------------------------------------------------
#  注册表
# ---------------------------------------------------------------------------

_DECODERS: dict[str, Callable[[bytes], tuple[list[FrameField], str, list[str]]]] = {
    "modbus_tcp": _decode_modbus_tcp,
    "modbus_rtu": _decode_modbus_rtu,
    "s7": _decode_s7,
    "iec104": _decode_iec104,
    "dlt645": _decode_dlt645,
    "cjt188": _decode_cjt188,
    "fins": _decode_fins,
    "mc": _decode_mc,
    "mewtocol": _decode_mewtocol,
}
