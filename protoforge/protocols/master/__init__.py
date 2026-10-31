"""主站模式协议实现（v1.9.0）。

与 ``protoforge/protocols`` 下的从站（Slave/Server）实现方向相反：
这里的协议服务器**主动拨出**连接真实从站设备并轮询点位。
"""

from protoforge.protocols.master.base import MasterBase

__all__ = ["MasterBase"]
