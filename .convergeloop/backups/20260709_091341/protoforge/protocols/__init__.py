from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

_PROTOCOL_CLASSES: dict[str, str] = {
    "modbus_tcp": "protoforge.protocols.modbus:ModbusTcpServer",
    "modbus_rtu": "protoforge.protocols.modbus:ModbusRtuServer",
    "opcua": "protoforge.protocols.opcua:OpcUaServer",
    "opcua_client": "protoforge.protocols.opcua:OpcUaClientProtocol",
    "s7": "protoforge.protocols.s7:S7Server",
    "fins": "protoforge.protocols.fins:FinsServer",
    "mc": "protoforge.protocols.mc:McServer",
    "mqtt": "protoforge.protocols.mqtt:MqttBroker",
    "http": "protoforge.protocols.http:HttpSimulatorServer",
    "gb28181": "protoforge.protocols.gb28181:GB28181Server",
    "bacnet": "protoforge.protocols.bacnet:BACnetServer",
    "ab": "protoforge.protocols.ab:AbServer",
    "fanuc": "protoforge.protocols.fanuc:FanucServer",
    "opcda": "protoforge.protocols.opcda:OpcDaServer",
    "toledo": "protoforge.protocols.toledo:ToledoServer",
    "mtconnect": "protoforge.protocols.mtconnect:MtConnectServer",
    "ethercat": "protoforge.protocols.ethercat:EtherCATServer",
    "profinet": "protoforge.protocols.profinet:ProfinetServer",
}

PROTOCOL_REGISTRY: dict[str, type[ProtocolServer]] = {}
PROTOCOL_LOAD_ERRORS: dict[str, str] = {}  # FIXED: 记录加载失败的协议及原因，供API查询


def _load_protocols() -> None:
    import importlib
    import logging
    logger = logging.getLogger(__name__)
    for name, qual in _PROTOCOL_CLASSES.items():
        if name in PROTOCOL_REGISTRY:
            continue
        module_path, _, class_name = qual.partition(":")
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            PROTOCOL_REGISTRY[name] = cls
        except Exception as e:
            PROTOCOL_LOAD_ERRORS[name] = str(e)  # FIXED: 记录加载失败原因
            logger.warning("Failed to load protocol %s (%s): %s", name, qual, e)


_load_protocols()

__all__ = [
    "ProtocolServer",
    "ProtocolStatus",
    "DeviceBehavior",
    "PROTOCOL_REGISTRY",
    "PROTOCOL_LOAD_ERRORS",
]
