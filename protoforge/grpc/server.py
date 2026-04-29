import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

try:
    import grpc
    from grpc import aio as grpc_aio

    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    logger.debug("grpcio not installed, gRPC server will not be available")

try:
    from protoforge.grpc import protoforge_pb2 as pb2
    from protoforge.grpc import protoforge_pb2_grpc as pb2_grpc
    PB2_AVAILABLE = True
except ImportError:
    PB2_AVAILABLE = False
    logger.debug("ProtoForge protobuf modules not generated. Run: python -m grpc_tools.protoc")


def _get_engine():
    try:
        from protoforge.main import get_engine
        return get_engine()
    except RuntimeError:
        return None


def _get_database():
    try:
        from protoforge.main import get_database
        return get_database()
    except RuntimeError:
        return None


class ProtoForgeServicer(pb2_grpc.ProtoForgeServiceServicer if PB2_AVAILABLE else object):
    async def GetHealth(self, request, context):
        engine = _get_engine()
        db = _get_database()
        device_count = 0
        if engine:
            try:
                device_count = len(engine.list_devices())
            except Exception:
                pass
        db_status = "unknown"
        if db:
            try:
                await db.load_all_devices()
                db_status = "ok"
            except Exception:
                db_status = "error"
        return pb2.HealthResponse(
            status="ok",
            uptime=int(time.time()),
            device_count=device_count,
            database=db_status,
        )

    async def ListDevices(self, request, context):
        engine = _get_engine()
        if not engine:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Engine not initialized")
            return pb2.ListDevicesResponse()
        devices = engine.list_devices()
        limit = request.limit or 100
        offset = request.offset or 0
        sliced = devices[offset : offset + limit]
        device_infos = []
        for d in sliced:
            device_infos.append(pb2.DeviceInfo(
                id=d.get("id", ""),
                name=d.get("name", ""),
                protocol=d.get("protocol", ""),
                status=d.get("status", "unknown"),
                point_count=len(d.get("points", [])),
            ))
        return pb2.ListDevicesResponse(devices=device_infos, total=len(devices))

    async def GetDevice(self, request, context):
        engine = _get_engine()
        if not engine:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.DeviceResponse(ok=False, error="Engine not initialized")
        try:
            device = engine.get_device(request.device_id)
            info = pb2.DeviceInfo(
                id=device.get("id", ""),
                name=device.get("name", ""),
                protocol=device.get("protocol", ""),
                status=device.get("status", "unknown"),
                point_count=len(device.get("points", [])),
            )
            return pb2.DeviceResponse(device=info, ok=True)
        except ValueError as e:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            return pb2.DeviceResponse(ok=False, error=str(e))

    async def CreateDevice(self, request, context):
        engine = _get_engine()
        if not engine:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.DeviceResponse(ok=False, error="Engine not initialized")
        try:
            from protoforge.models.device import DeviceConfig
            config = DeviceConfig(
                name=request.name,
                protocol=request.protocol,
                template_id=request.template_id or None,
                protocol_config=dict(request.protocol_config) if request.protocol_config else {},
                points=[],
            )
            device_id = await engine.create_device(config)
            return pb2.DeviceResponse(
                device=pb2.DeviceInfo(id=device_id, name=request.name, protocol=request.protocol),
                ok=True,
            )
        except Exception as e:
            return pb2.DeviceResponse(ok=False, error=str(e))

    async def DeleteDevice(self, request, context):
        engine = _get_engine()
        if not engine:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.DeleteDeviceResponse(ok=False, error="Engine not initialized")
        try:
            await engine.remove_device(request.device_id)
            return pb2.DeleteDeviceResponse(ok=True)
        except Exception as e:
            return pb2.DeleteDeviceResponse(ok=False, error=str(e))

    async def StartDevice(self, request, context):
        engine = _get_engine()
        if not engine:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.OperationResponse(ok=False, error="Engine not initialized")
        try:
            await engine.start_device(request.device_id)
            return pb2.OperationResponse(ok=True)
        except Exception as e:
            return pb2.OperationResponse(ok=False, error=str(e))

    async def StopDevice(self, request, context):
        engine = _get_engine()
        if not engine:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.OperationResponse(ok=False, error="Engine not initialized")
        try:
            await engine.stop_device(request.device_id)
            return pb2.OperationResponse(ok=True)
        except Exception as e:
            return pb2.OperationResponse(ok=False, error=str(e))

    async def ReadPoints(self, request, context):
        engine = _get_engine()
        if not engine:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.ReadPointsResponse(error="Engine not initialized")
        try:
            points = await engine.read_device_points(request.device_id)
            pb_points = []
            for p in points:
                pb_points.append(pb2.PointValue(
                    name=p.name,
                    value=str(p.value),
                    timestamp=p.timestamp,
                ))
            return pb2.ReadPointsResponse(points=pb_points)
        except Exception as e:
            return pb2.ReadPointsResponse(error=str(e))

    async def WritePoint(self, request, context):
        engine = _get_engine()
        if not engine:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.OperationResponse(ok=False, error="Engine not initialized")
        try:
            await engine.write_device_point(request.device_id, request.point_name, request.value)
            return pb2.OperationResponse(ok=True)
        except Exception as e:
            return pb2.OperationResponse(ok=False, error=str(e))

    async def ListScenarios(self, request, context):
        db = _get_database()
        if not db:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.ListScenariosResponse()
        try:
            scenarios = await db.load_all_scenarios()
            limit = request.limit or 100
            offset = request.offset or 0
            sliced = scenarios[offset : offset + limit]
            scenario_infos = []
            for s in sliced:
                scenario_infos.append(pb2.ScenarioInfo(
                    id=s.id if hasattr(s, 'id') else s.get("id", ""),
                    name=s.name if hasattr(s, 'name') else s.get("name", ""),
                    status="stopped",
                    device_count=len(s.devices) if hasattr(s, 'devices') else len(s.get("devices", [])),
                ))
            return pb2.ListScenariosResponse(scenarios=scenario_infos, total=len(scenarios))
        except Exception as e:
            logger.warning("ListScenarios failed: %s", e)
            context.set_code(grpc.StatusCode.INTERNAL)
            return pb2.ListScenariosResponse()

    async def StartScenario(self, request, context):
        engine = _get_engine()
        if not engine:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.OperationResponse(ok=False, error="Engine not initialized")
        try:
            await engine.start_scenario(request.scenario_id)
            return pb2.OperationResponse(ok=True)
        except Exception as e:
            return pb2.OperationResponse(ok=False, error=str(e))

    async def StopScenario(self, request, context):
        engine = _get_engine()
        if not engine:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.OperationResponse(ok=False, error="Engine not initialized")
        try:
            await engine.stop_scenario(request.scenario_id)
            return pb2.OperationResponse(ok=True)
        except Exception as e:
            return pb2.OperationResponse(ok=False, error=str(e))

    async def GetSettings(self, request, context):
        db = _get_database()
        if not db:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.SettingsResponse()
        try:
            data = await db.export_all()
            settings = {}
            for table, rows in data.items():
                settings[table] = len(rows) if isinstance(rows, list) else 0
            return pb2.SettingsResponse(settings=settings)
        except Exception as e:
            logger.debug("GetSettings failed: %s", e)
            return pb2.SettingsResponse()

    async def UpdateSettings(self, request, context):
        db = _get_database()
        if not db:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return pb2.OperationResponse(ok=False, error="Database not initialized")
        try:
            settings = dict(request.settings)
            await db.import_all(settings)
            return pb2.OperationResponse(ok=True)
        except Exception as e:
            return pb2.OperationResponse(ok=False, error=str(e))


async def start_grpc_server(port: int = 50051) -> Any:
    if not GRPC_AVAILABLE or not PB2_AVAILABLE:
        logger.warning("gRPC dependencies not available. Install: pip install grpcio grpcio-tools")
        return None
    server = grpc_aio.server()
    pb2_grpc.add_ProtoForgeServiceServicer_to_server(ProtoForgeServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    await server.start()
    logger.info("gRPC server started on port %d", port)
    return server
