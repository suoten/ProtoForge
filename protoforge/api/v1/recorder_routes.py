import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_log_bus, _get_engine

router = APIRouter()
logger = logging.getLogger(__name__)

_recorder = None


def _get_recorder():
    global _recorder
    if _recorder is None:
        from protoforge.core.recorder import Recorder
        _recorder = Recorder(_get_log_bus())
    return _recorder


@router.post("/recorder/start")
async def start_recording(config: Optional[dict[str, Any]] = None, _user: dict = Depends(require_operator)):
    try:
        cfg = config or {}
        recorder = _get_recorder()
        rec = await recorder.start_recording(
            name=cfg.get("name", "Untitled"),
            protocol=cfg.get("protocol"),
            device_id=cfg.get("device_id"),
            metadata=cfg.get("metadata"),
        )
        return rec.to_dict()
    except Exception as e:
        logger.error("Failed to start recording: %s", e)
        raise HTTPException(status_code=500, detail=f"开始录制失败: {e}") from e


@router.post("/recorder/stop")
async def stop_recording(_user: dict = Depends(require_operator)):
    try:
        recorder = _get_recorder()
        rec = await recorder.stop_recording()
        if not rec:
            raise HTTPException(status_code=400, detail="No active recording")
        return rec.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to stop recording: %s", e)
        raise HTTPException(status_code=500, detail=f"停止录制失败: {e}") from e


@router.get("/recorder/recordings")
async def list_recordings(_user: dict = Depends(require_viewer)):
    try:
        recorder = _get_recorder()
        return {"recordings": recorder.list_recordings()}
    except Exception as e:
        logger.error("Failed to list recordings: %s", e)
        raise HTTPException(status_code=500, detail=f"获取录制列表失败: {e}") from e


@router.get("/recorder/recordings/{rec_id}")
async def get_recording(rec_id: str, _user: dict = Depends(require_viewer)):
    try:
        recorder = _get_recorder()
        rec = recorder.get_recording(rec_id)

        if not rec:
            raise HTTPException(status_code=404, detail="Recording not found")
        return rec.to_full_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get recording %s: %s", rec_id, e)
        raise HTTPException(status_code=500, detail=f"获取录制详情失败: {e}") from e


@router.delete("/recorder/recordings/{rec_id}")
async def delete_recording(rec_id: str, _user: dict = Depends(require_operator)):
    recorder = _get_recorder()
    if not recorder.get_recording(rec_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    try:
        await recorder.delete_recording_persisted(rec_id)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除录制失败: {str(e)}")


@router.post("/recorder/recordings/{rec_id}/replay")
async def replay_recording(rec_id: str, config: Optional[dict[str, Any]] = None, _user: dict = Depends(require_operator)):
    recorder = _get_recorder()
    cfg = config or {}
    speed = cfg.get("speed", 1.0)

    if not isinstance(speed, (int, float)) or speed <= 0 or speed > 100:
        raise HTTPException(status_code=400, detail="speed 必须是 0-100 之间的正数")

    try:
        result = await recorder.replay_recording(rec_id, speed=speed, target_engine=_get_engine())
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to replay recording %s: %s", rec_id, e)
        raise HTTPException(status_code=500, detail=f"回放录制失败: {e}") from e


@router.get("/recorder/recordings/{rec_id}/export")
async def export_recording(rec_id: str, _user: dict = Depends(require_viewer)):
    try:
        recorder = _get_recorder()
        rec = recorder.get_recording(rec_id)

        if not rec:
            raise HTTPException(status_code=404, detail="Recording not found")
        from fastapi.responses import JSONResponse
        return JSONResponse(content=rec.to_full_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to export recording %s: %s", rec_id, e)
        raise HTTPException(status_code=500, detail=f"导出录制失败: {e}") from e


@router.get("/recorder/stats")
async def recorder_stats(_user: dict = Depends(require_viewer)):
    try:
        recorder = _get_recorder()
        return recorder.get_stats()
    except Exception as e:
        logger.error("Failed to get recorder stats: %s", e)
        raise HTTPException(status_code=500, detail=f"获取录制统计失败: {e}") from e
