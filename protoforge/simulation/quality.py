"""数据质量系统。

实现 OPC UA 兼容的数据质量码（QualityCode）和自动质量计算系统
（QualitySystem），用于根据设备状态、通信状态和故障情况自动确定
数据质量。

OPC UA 质量码采用 32 位整数编码，高 2 位表示大类（Good/Uncertain/Bad），
低位表示子状态。本模块覆盖了 OPC UA 规范中最常用的质量码子状态。

质量码层级::

    Good (0x00)          ─── Good_LocalOverride (0x00010000)
    Uncertain (0x40)     ─── Uncertain_LastUsable (0x40440000)
                         ─── Uncertain_SensorNotAccurate (0x40500000)
    Bad (0x80)           ─── Bad_ConfigurationError (0x80080000)
                         ─── Bad_NotConnected (0x800C0000)
                         ─── Bad_DeviceFailure (0x80100000)
                         ─── Bad_SensorFailure (0x80140000)
                         ─── Bad_OutOfService (0x801C0000)
                         ─── Bad_CommunicationError (0x80180000)
"""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


class QualityCode(IntEnum):
    """OPC UA 数据质量码。

    编码规则遵循 OPC UA 规范 Part 4 / Part 8:
      - Bit 31-30: 大类 (00=Good, 01=Uncertain, 10=Bad)
      - Bit 29-27: 子类 (子状态描述)
      - Bit 26-25: 信息源 (0=Device/Source, 1=Local Override)
      - Bit 24-16: 局限码
      - Bit 15-0: 供应商特定扩展
    """

    # Good
    GOOD = 0x00000000
    GOOD_LOCAL_OVERRIDE = 0x00010000

    # Uncertain
    UNCERTAIN = 0x40000000
    UNCERTAIN_LAST_USABLE = 0x40440000
    UNCERTAIN_SENSOR_NOT_ACCURATE = 0x40500000

    # Bad
    BAD = 0x80000000
    BAD_CONFIGURATION_ERROR = 0x80080000
    BAD_NOT_CONNECTED = 0x800C0000
    BAD_DEVICE_FAILURE = 0x80100000
    BAD_SENSOR_FAILURE = 0x80140000
    BAD_OUT_OF_SERVICE = 0x801C0000
    BAD_COMMUNICATION_ERROR = 0x80180000


class QualitySystem:
    """数据质量自动计算系统。

    提供字符串质量标记与 OPC UA QualityCode 之间的双向转换，
    以及基于设备状态、通信状态和故障情况的质量自动计算。

    使用方式::

        # 从设备状态计算质量
        code = QualitySystem.compute(device_state="run", comm_status="ok")

        # 转换为字符串
        qstr = QualitySystem.to_string(code)

        # 转换为字典（API 响应）
        info = QualitySystem.to_dict(code)
    """

    # 字符串 → QualityCode 映射
    _STR_TO_CODE: dict[str, QualityCode] = {
        "good": QualityCode.GOOD,
        "bad": QualityCode.BAD,
        "uncertain": QualityCode.UNCERTAIN,
        "out_of_service": QualityCode.BAD_OUT_OF_SERVICE,
    }

    # QualityCode → 字符串映射（反向查找时取最佳匹配）
    _CODE_TO_STR: dict[QualityCode, str] = {
        QualityCode.GOOD: "good",
        QualityCode.GOOD_LOCAL_OVERRIDE: "good",
        QualityCode.UNCERTAIN: "uncertain",
        QualityCode.UNCERTAIN_LAST_USABLE: "uncertain",
        QualityCode.UNCERTAIN_SENSOR_NOT_ACCURATE: "uncertain",
        QualityCode.BAD: "bad",
        QualityCode.BAD_CONFIGURATION_ERROR: "bad",
        QualityCode.BAD_NOT_CONNECTED: "bad",
        QualityCode.BAD_DEVICE_FAILURE: "bad",
        QualityCode.BAD_SENSOR_FAILURE: "bad",
        QualityCode.BAD_OUT_OF_SERVICE: "out_of_service",
        QualityCode.BAD_COMMUNICATION_ERROR: "bad",
    }

    # 质量码严重程度排序（用于取最严重质量）
    _SEVERITY: dict[str, int] = {
        "good": 0,
        "uncertain": 1,
        "out_of_service": 2,
        "bad": 3,
    }

    # QualityCode 的中文描述
    _DESCRIPTIONS: dict[QualityCode, str] = {
        QualityCode.GOOD: "数据有效",
        QualityCode.GOOD_LOCAL_OVERRIDE: "数据有效（本地覆盖）",
        QualityCode.UNCERTAIN: "数据不确定",
        QualityCode.UNCERTAIN_LAST_USABLE: "数据不确定（最后可用值）",
        QualityCode.UNCERTAIN_SENSOR_NOT_ACCURATE: "数据不确定（传感器精度不足）",
        QualityCode.BAD: "数据无效",
        QualityCode.BAD_CONFIGURATION_ERROR: "配置错误",
        QualityCode.BAD_NOT_CONNECTED: "设备未连接",
        QualityCode.BAD_DEVICE_FAILURE: "设备故障",
        QualityCode.BAD_SENSOR_FAILURE: "传感器故障",
        QualityCode.BAD_OUT_OF_SERVICE: "设备停止服务",
        QualityCode.BAD_COMMUNICATION_ERROR: "通信错误",
    }

    # ------------------------------------------------------------------
    #  字符串 / QualityCode 双向转换
    # ------------------------------------------------------------------

    @staticmethod
    def from_string(quality_str: str) -> QualityCode:
        """将字符串质量标记映射为 QualityCode。

        支持的字符串: "good", "bad", "uncertain", "out_of_service"

        :param quality_str: 质量标记字符串
        :return: 对应的 QualityCode，未知字符串返回 GOOD
        """
        return QualitySystem._STR_TO_CODE.get(quality_str, QualityCode.GOOD)

    @staticmethod
    def to_string(code: QualityCode) -> str:
        """将 QualityCode 映射回字符串质量标记。

        :param code: OPC UA 质量码
        :return: 质量标记字符串 ("good"/"uncertain"/"bad"/"out_of_service")
        """
        # 精确匹配
        if code in QualitySystem._CODE_TO_STR:
            return QualitySystem._CODE_TO_STR[code]
        # 按大类匹配
        if QualitySystem.is_good(code):
            return "good"
        if QualitySystem.is_uncertain(code):
            return "uncertain"
        if QualitySystem.is_bad(code):
            # 检查是否为 out_of_service
            if code == QualityCode.BAD_OUT_OF_SERVICE:
                return "out_of_service"
            return "bad"
        return "uncertain"

    # ------------------------------------------------------------------
    #  质量码分类查询
    # ------------------------------------------------------------------

    @staticmethod
    def is_good(code: QualityCode) -> bool:
        """判断质量码是否属于 Good 大类。"""
        return (int(code) & 0xC0000000) == 0x00000000

    @staticmethod
    def is_uncertain(code: QualityCode) -> bool:
        """判断质量码是否属于 Uncertain 大类。"""
        return (int(code) & 0xC0000000) == 0x40000000

    @staticmethod
    def is_bad(code: QualityCode) -> bool:
        """判断质量码是否属于 Bad 大类。"""
        return (int(code) & 0xC0000000) == 0x80000000

    @staticmethod
    def get_description(code: QualityCode) -> str:
        """获取质量码的中文描述。"""
        return QualitySystem._DESCRIPTIONS.get(code, "未知质量码")

    # ------------------------------------------------------------------
    #  质量自动计算
    # ------------------------------------------------------------------

    @staticmethod
    def compute(
        device_state: str,
        comm_status: str = "ok",
        fault_active: bool = False,
        sensor_stuck: bool = False,
    ) -> QualityCode:
        """根据设备状态、通信状态、故障情况自动计算质量码。

        计算优先级（高→低）::

            1. 设备故障 (device_state == "error")      → BAD_DEVICE_FAILURE
            2. 通信超时 (comm_status == "timeout")      → BAD_NOT_CONNECTED
            3. 通信错误 (comm_status == "error")        → BAD_COMMUNICATION_ERROR
            4. 维护模式 (device_state == "maintenance") → BAD_OUT_OF_SERVICE
            5. 传感器卡死 (sensor_stuck)                 → UNCERTAIN_LAST_USABLE
            6. 故障激活 (fault_active)                   → UNCERTAIN_SENSOR_NOT_ACCURATE
            7. 正常运行 (device_state == "run")          → GOOD
            8. 其他状态                                  → UNCERTAIN

        :param device_state: 设备状态字符串 ("run"/"stop"/"error"/"starting"/
                             "stopping"/"maintenance"/"program")
        :param comm_status: 通信状态 ("ok"/"timeout"/"error")
        :param fault_active: 是否有活跃故障
        :param sensor_stuck: 传感器是否卡死
        :return: 计算得出的 QualityCode
        """
        if device_state == "error":
            return QualityCode.BAD_DEVICE_FAILURE
        if comm_status == "timeout":
            return QualityCode.BAD_NOT_CONNECTED
        if comm_status == "error":
            return QualityCode.BAD_COMMUNICATION_ERROR
        if device_state == "maintenance":
            return QualityCode.BAD_OUT_OF_SERVICE
        if sensor_stuck:
            return QualityCode.UNCERTAIN_LAST_USABLE
        if fault_active:
            return QualityCode.UNCERTAIN_SENSOR_NOT_ACCURATE
        if device_state == "run":
            return QualityCode.GOOD
        return QualityCode.UNCERTAIN  # stop, starting, stopping, program

    # ------------------------------------------------------------------
    #  质量比较
    # ------------------------------------------------------------------

    @staticmethod
    def worst(q1: QualityCode, q2: QualityCode) -> QualityCode:
        """取两个质量码中更严重的一个。

        严重程度: Bad > OutOfService > Uncertain > Good

        :param q1: 质量码 1
        :param q2: 质量码 2
        :return: 更严重的质量码
        """
        s1 = QualitySystem._SEVERITY.get(QualitySystem.to_string(q1), 0)
        s2 = QualitySystem._SEVERITY.get(QualitySystem.to_string(q2), 0)
        return q1 if s1 >= s2 else q2

    @staticmethod
    def worst_str(q1: str, q2: str) -> str:
        """取两个字符串质量标记中更严重的一个。

        严重程度: bad > out_of_service > uncertain > good

        :param q1: 质量标记字符串 1
        :param q2: 质量标记字符串 2
        :return: 更严重的质量标记字符串
        """
        s1 = QualitySystem._SEVERITY.get(q1, 0)
        s2 = QualitySystem._SEVERITY.get(q2, 0)
        return q1 if s1 >= s2 else q2

    # ------------------------------------------------------------------
    #  序列化
    # ------------------------------------------------------------------

    @staticmethod
    def to_dict(code: QualityCode) -> dict[str, Any]:
        """将质量码序列化为字典（用于 API 响应）。

        :param code: OPC UA 质量码
        :return: 包含 code、string、description 的字典
        """
        return {
            "code": int(code),
            "string": QualitySystem.to_string(code),
            "description": QualitySystem.get_description(code),
            "is_good": QualitySystem.is_good(code),
            "is_uncertain": QualitySystem.is_uncertain(code),
            "is_bad": QualitySystem.is_bad(code),
        }
