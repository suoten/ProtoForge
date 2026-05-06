import logging

logger = logging.getLogger(__name__)


def _get_engine():
    from protoforge.main import get_engine
    return get_engine()


def _get_template_manager():
    from protoforge.main import get_template_manager
    return get_template_manager()


def _get_log_bus():
    from protoforge.main import get_log_bus
    return get_log_bus()


def _get_database():
    from protoforge.main import get_database
    return get_database()
