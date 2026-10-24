"""Vendor compatibility regression: Inovance EIP 标签通信 Demo (V2.0.2.9).

来源：2026-10-22~23 用户（安无恙）实测抓包，六轮联调定型的厂商兼容行为。
本文件锁定整条链路，防止后续改动把以下任何一环改回导致 Demo 重新连不上：

1. RegisterSession 正常分配会话
2. 0x0E Get_Attribute_Single 扫描必须回状态 0x01（回 0x14 会把 Demo 带进
   空帧握手死分支，v1.6.37）
3. Large Forward Open (transport 0xA3) 正常应答
4. 已连接通道上的 seq=1 空帧（null/null 心跳）必须回送同连接同 seq 的
   空数据帧（静默或错误应答都会让 Demo 卡死，v1.6.38）
5. 0x4B Execute_PCCC 读：点位地址填数字时按点位名（_tag_alias）回退匹配
   命中（v1.6.39），值按类型码尺寸打包（BOOL=1 字节）
6. 不存在的标签回 0xCB/0x04，Demo DLL 收到后不会崩（但会进入中毒状态，
   属 Demo 侧行为，无法在服务端消除）
"""

from __future__ import annotations

import asyncio
import struct

from protoforge.models.device import DataType, PointConfig
from protoforge.protocols.ab.server import AbServer

EIP_HEADER_SIZE = 24


def _eip(cmd: int, payload: bytes, session: int = 0) -> bytes:
    return (struct.pack("<HHII", cmd, len(payload), session, 0)
            + bytes(8) + struct.pack("<I", 0) + payload)


def _rrdata(cip: bytes, session: int = 0) -> bytes:
    body = struct.pack("<IHH", 0, 0, 2) + struct.pack("<HH", 0x0000, 0) \
        + struct.pack("<HH", 0xB2, len(cip)) + cip
    return _eip(0x6F, body, session)


def _unitdata(cip: bytes, conn_id: bytes, seq: int, session: int = 0) -> bytes:
    items = (struct.pack("<HH", 0x00A1, 4) + conn_id
             + struct.pack("<HH", 0x00B1, 2 + len(cip))
             + struct.pack("<H", seq) + cip)
    return _eip(0x70, struct.pack("<IHH", 0, 0, 2) + items, session)


# 用户实测 Large Forward Open 帧（仅连接 ID 每次随机，结构固定）
_LFO = bytes.fromhex(
    "5b0220062401059c"
    "65126232" "64126232" "6612"          # O->T / T->O / serial
    "7c060100000000000000"
    "80841e00cc07004280841e00cc070042"
    "a3073404000000000000000020022401")

# 0x0E 扫描：class 2 inst 0 attr 0x64（Demo 启动即发）
_GAS = bytes.fromhex("0e03200224003064")


class _Cfg:
    id = "ab-inovance-test"
    name = "AB Test"
    protocol_config = {"slot": 0}
    points = [
        # 复现用户真实配置：名称 point_1、地址填数字 0、布尔
        PointConfig(name="point_1", address="0", data_type=DataType.BOOL),
        PointConfig(name="cpu_load", address="1", data_type=DataType.INT16),
        PointConfig(name="f_val", address="2", data_type=DataType.FLOAT32),
    ]


def _pccc_read(tag: str) -> bytes:
    name = tag.encode("utf-8")
    return b"\x4b\x02\x20\x6a\x24\x00" + struct.pack("<H", len(name)) + name


def _pccc_write(tag: str, value_bytes: bytes) -> bytes:
    """Execute_PCCC 写请求：载荷(标签名)后携带写值字节（汇川简化格式）。"""
    return _pccc_read(tag) + value_bytes


class TestInovanceEipDemoChain:
    def setup_method(self):
        self.server = AbServer()
        asyncio.run(self._create())
        r = self.server._process_eip(_eip(0x65, struct.pack("<HH", 1, 0)))
        self.session = struct.unpack("<I", r[4:8])[0]

    async def _create(self):
        await self.server.create_device(_Cfg())

    # -- 环节 1/2/3 -------------------------------------------------------
    def test_register_scan_forward_open(self):
        assert self.session == 1
        # 0x0E 扫描：必须回 8e 01 00 00（状态 0x01；0x14 会让 Demo 卡死）
        resp = self.server._process_eip(_rrdata(_GAS, self.session))
        assert resp[-4:] == bytes.fromhex("8e010000")
        # Large Forward Open：DB 成功应答
        resp = self.server._process_eip(_rrdata(_LFO, self.session))
        assert resp is not None and b"\xdb" in resp

    # -- 环节 4：null/null 心跳回送 ---------------------------------------
    def test_null_frame_heartbeat_echo(self):
        self.server._process_eip(_rrdata(_LFO, self.session))
        conn = bytes.fromhex("65126232")
        req = _unitdata(b"\x00\x00", conn, seq=1, session=self.session)
        resp = self.server._process_eip(req)
        assert resp is not None, "空帧必须有应答（静默会让 Demo 卡死）"
        want = struct.pack("<HH", 0xB1, 4) + struct.pack("<H", 1) + b"\x00\x00"
        assert resp.endswith(want), "必须回送同 seq 空数据帧"
        assert b"\x80\x08" not in resp, "不得回错误帧（Demo 不认）"
        # seq 回显
        resp2 = self.server._process_eip(
            _unitdata(b"\x00\x00", conn, seq=7, session=self.session))
        want7 = struct.pack("<HH", 0xB1, 4) + struct.pack("<H", 7) + b"\x00\x00"
        assert resp2.endswith(want7)

    # -- 环节 5：0x4B 按点位名命中（地址填数字）+ 值按类型尺寸打包 ---------
    def test_pccc_read_hit_by_point_name(self):
        self.server._process_eip(_rrdata(_LFO, self.session))
        conn = bytes.fromhex("65126232")
        resp = self.server._process_eip(
            _unitdata(_pccc_read("point_1"), conn, seq=2, session=self.session))
        cip = resp[resp.find(b"\xcb"):] if resp else b""
        # cb 00 00 00 + 名长 + 名字 + 类型码 C1(BOOL) + 1 字节值
        want = (bytes([0xCB, 0, 0, 0]) + struct.pack("<H", 7) + b"point_1"
                + b"\xc1\x00" + b"\x00")
        assert cip == want, f"BOOL 应答应为 1 字节值: {cip.hex()}"

        resp = self.server._process_eip(
            _unitdata(_pccc_read("cpu_load"), conn, seq=3, session=self.session))
        cip = resp[resp.find(b"\xcb"):] if resp else b""
        want = (bytes([0xCB, 0, 0, 0]) + struct.pack("<H", 8) + b"cpu_load"
                + b"\xc3\x00" + struct.pack("<H", 0))
        assert cip == want, f"INT16 应答应为 2 字节值: {cip.hex()}"

        resp = self.server._process_eip(
            _unitdata(_pccc_read("f_val"), conn, seq=4, session=self.session))
        cip = resp[resp.find(b"\xcb"):] if resp else b""
        want = (bytes([0xCB, 0, 0, 0]) + struct.pack("<H", 5) + b"f_val"
                + b"\xca\x00" + struct.pack("<f", 0.0))
        assert cip == want, f"FLOAT32 应答应为 4 字节值: {cip.hex()}"

    # -- 环节 6：未命中显式拒绝 -------------------------------------------
    def test_pccc_read_miss_rejected(self):
        self.server._process_eip(_rrdata(_LFO, self.session))
        conn = bytes.fromhex("65126232")
        resp = self.server._process_eip(
            _unitdata(_pccc_read("run_status"), conn, seq=2, session=self.session))
        assert resp is not None and resp[-4:] == bytes.fromhex("cb040000")

    # -- 环节 7：Execute_PCCC 写（v1.6.41） --------------------------------
    # 背景：用户 10-24 反馈"写入了但标签值不变"。原实现写判定要求载荷后
    # len>=4 字节且一律 <I 整数解析：BOOL(1 字节)/INT16(2 字节) 最小编码写
    # 请求被当读请求忽略，float32 写 1.5 被解析成 1069547520。
    def _write_and_check(self, tag, value_bytes, expect_value=None, seq=10):
        self.server._process_eip(_rrdata(_LFO, self.session))
        conn = bytes.fromhex("65126232")
        resp = self.server._process_eip(
            _unitdata(_pccc_write(tag, value_bytes), conn, seq=seq, session=self.session))
        assert resp is not None and b"\xcb" in resp, "写应答不能是错误帧"
        name = tag.encode("utf-8")
        # 写应答 = [CB 00 00 00][名字长度 UINT][标签名]，不含值
        assert resp.endswith(struct.pack("<H", len(name)) + name), \
            f"写应答格式异常: {resp.hex()}"
        assert b"\xcb\x04" not in resp, "写请求不得被拒绝（未命中）"
        return resp

    def test_pccc_write_bool_1byte(self):
        """BOOL 最小编码写（1 字节 0x01）必须生效，不再被当读忽略（场景 A）。"""
        self._write_and_check("point_1", b"\x01")
        assert self.server._behaviors["ab-inovance-test"]._values.get("point_1") is True \
            or self.server._behaviors["ab-inovance-test"]._values.get("point_1") == 1, \
            "BOOL 写 0x01 后行为层值必须变 true"

    def test_pccc_write_int16_2byte_and_4byte(self):
        """INT16 最小编码写（2 字节 <H）与 4 字节小端写都要生效。"""
        self._write_and_check("cpu_load", struct.pack("<H", 1234))
        v = self.server._behaviors["ab-inovance-test"]._values.get("cpu_load")
        assert v == 1234, f"INT16 写 2 字节 1234 后值必须为 1234, 实际 {v}"
        self._write_and_check("cpu_load", struct.pack("<I", 4321))
        v = self.server._behaviors["ab-inovance-test"]._values.get("cpu_load")
        assert v == 4321, f"INT16 写 4 字节 4321 后值必须为 4321, 实际 {v}"

    def test_pccc_write_float32(self):
        """FLOAT32 写必须按 <f 解析（1.5 不再变成 1069547520）。"""
        self._write_and_check("f_val", struct.pack("<f", 1.5))
        v = self.server._behaviors["ab-inovance-test"]._values.get("f_val")
        assert abs(float(v) - 1.5) < 1e-6, f"FLOAT32 写 1.5 后值必须为 1.5, 实际 {v}"

    def test_pccc_write_then_read_back(self):
        """写后读回：0x4B 读必须拿到刚写入的值（含 30 秒写入冻结）。"""
        self._write_and_check("cpu_load", struct.pack("<H", 2000))
        conn = bytes.fromhex("65126232")
        resp = self.server._process_eip(
            _unitdata(_pccc_read("cpu_load"), conn, seq=20, session=self.session))
        cip = resp[resp.find(b"\xcb"):] if resp else b""
        want = (bytes([0xCB, 0, 0, 0]) + struct.pack("<H", 8) + b"cpu_load"
                + b"\xc3\x00" + struct.pack("<H", 2000))
        assert cip == want, f"写后读必须返回写入值 2000: {cip.hex()}"
