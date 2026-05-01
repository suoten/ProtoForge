from protoforge.protocols.base import ProtocolServer, ProtocolStatus, DeviceBehavior
from protoforge.protocols.modbus import ModbusTcpServer, ModbusRtuServer
from protoforge.protocols.opcua import OpcUaServer
from protoforge.protocols.s7 import S7Server
from protoforge.protocols.fins import FinsServer
from protoforge.protocols.mc import McServer
from protoforge.protocols.mqtt import MqttBroker
from protoforge.protocols.http import HttpSimulatorServer
from protoforge.protocols.gb28181 import GB28181Server
from protoforge.protocols.bacnet import BACnetServer
from protoforge.protocols.ab import AbServer
from protoforge.protocols.fanuc import FanucServer
from protoforge.protocols.opcda import OpcDaServer
from protoforge.protocols.toledo import ToledoServer
from protoforge.protocols.mtconnect import MtConnectServer
from protoforge.protocols.ethercat import EtherCATServer
from protoforge.protocols.profinet import ProfinetServer

PROTOCOL_REGISTRY: dict[str, type[ProtocolServer]] = {
    "modbus_tcp": ModbusTcpServer,
    "modbus_rtu": ModbusRtuServer,
    "opcua": OpcUaServer,
    "s7": S7Server,
    "fins": FinsServer,
    "mc": McServer,
    "mqtt": MqttBroker,
    "http": HttpSimulatorServer,
    "gb28181": GB28181Server,
    "bacnet": BACnetServer,
    "ab": AbServer,
    "fanuc": FanucServer,
    "opcda": OpcDaServer,
    "toledo": ToledoServer,
    "mtconnect": MtConnectServer,
    "ethercat": EtherCATServer,
    "profinet": ProfinetServer,
}

__all__ = [
    "ProtocolServer",
    "ProtocolStatus",
    "DeviceBehavior",
    "PROTOCOL_REGISTRY",
    "ModbusTcpServer",
    "ModbusRtuServer",
    "OpcUaServer",
    "S7Server",
    "FinsServer",
    "McServer",
    "MqttBroker",
    "HttpSimulatorServer",
    "GB28181Server",
    "BACnetServer",
    "AbServer",
    "FanucServer",
    "OpcDaServer",
    "ToledoServer",
    "MtConnectServer",
    "EtherCATServer",
    "ProfinetServer",
]
