from protoforge.core.integration.manager import IntegrationManager
from protoforge.core.integration.channel import ChannelBase, ChannelFactory
from protoforge.core.integration.protocol import ProtocolMapper, DataTypeMapper
from protoforge.core.integration.state import ConnectionStateMachine, ConnectionState
from protoforge.core.integration.retry import RetryPolicy, IntegrationError, NetworkError, AuthError, ValidationError, ServerError
from protoforge.core.integration.auth import IntegrationAuth
from protoforge.core.integration.metrics import IntegrationMetrics
from protoforge.core.integration.validator import MappingValidator, CompatibilityReport


def import_edgelite_config(config_data):
    from protoforge.core._integration_legacy import import_edgelite_config as _impl
    return _impl(config_data)


def import_edgelite_file(file_path):
    from protoforge.core._integration_legacy import import_edgelite_file as _impl
    return _impl(file_path)


def import_pygbsentry_config(config_data):
    from protoforge.core._integration_legacy import import_pygbsentry_config as _impl
    return _impl(config_data)


__all__ = [
    "IntegrationManager",
    "ChannelBase",
    "ChannelFactory",
    "ProtocolMapper",
    "DataTypeMapper",
    "ConnectionStateMachine",
    "ConnectionState",
    "RetryPolicy",
    "IntegrationError",
    "NetworkError",
    "AuthError",
    "ValidationError",
    "ServerError",
    "IntegrationAuth",
    "IntegrationMetrics",
    "MappingValidator",
    "CompatibilityReport",
    "import_edgelite_config",
    "import_edgelite_file",
    "import_pygbsentry_config",
]
