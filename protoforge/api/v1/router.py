import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

from protoforge.api.v1.protocol_routes import router as _protocol_router
from protoforge.api.v1.device_routes import router as _device_router
from protoforge.api.v1.scenario_routes import router as _scenario_router
from protoforge.api.v1.template_routes import router as _template_router
from protoforge.api.v1.log_routes import router as _log_router
from protoforge.api.v1.edgelite_routes import router as _edgelite_router
from protoforge.api.v1.integration import router as _integration_router
from protoforge.api.v1.test_routes import router as _test_router
from protoforge.api.v1.auth_routes import router as _auth_router
from protoforge.api.v1.forward_routes import router as _forward_router
from protoforge.api.v1.recorder_routes import router as _recorder_router
from protoforge.api.v1.webhook_routes import router as _webhook_router
from protoforge.api.v1.system_routes import router as _system_router

router.include_router(_protocol_router)
router.include_router(_device_router)
router.include_router(_scenario_router)
router.include_router(_template_router)
router.include_router(_log_router)
router.include_router(_edgelite_router)
router.include_router(_integration_router)
router.include_router(_test_router)
router.include_router(_auth_router)
router.include_router(_forward_router)
router.include_router(_recorder_router)
router.include_router(_webhook_router)
router.include_router(_system_router)
