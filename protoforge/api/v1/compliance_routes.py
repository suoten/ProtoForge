"""Protocol compliance checking API routes."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from protoforge.api.v1._helpers import _get_database
from protoforge.api.v1.auth import require_user, require_viewer

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/compliance/protocols")
async def list_compliance_protocols(_user: dict[str, Any] = Depends(require_viewer)):
    """List protocols that support compliance checking."""
    from protoforge.testing.compliance import get_supported_protocols
    return {"protocols": get_supported_protocols()}


@router.get("/compliance/rules/{protocol}")
async def get_compliance_rules(protocol: str, _user: dict[str, Any] = Depends(require_viewer)):
    """Get compliance rules for a specific protocol."""
    from protoforge.testing.compliance import get_rules_for_protocol
    rules = get_rules_for_protocol(protocol)
    if not rules:
        raise HTTPException(status_code=404, detail=f"No compliance rules for protocol: {protocol}")
    return {"protocol": protocol, "rules": rules}


@router.post("/compliance/decode-frame")
async def decode_frame(body: dict[str, Any], _user: dict[str, Any] = Depends(require_viewer)):
    """报文字段级解析（v1.9.0，Wireshark 式逐字段展开）。

    Request body::

        {"protocol": "modbus_tcp", "hex": "01 02 03...", "data_base64": "..."}

    ``hex``（空格/冒号/无分隔均可）或 ``data_base64`` 二选一。
    返回字段树（name/offset/length/raw/value/note/children）与解析告警。
    """
    import base64
    import binascii

    from protoforge.testing.frame_decoder import decode_frame, supported_protocols

    protocol = body.get("protocol", "")
    if not protocol:
        raise HTTPException(status_code=400, detail="protocol is required")
    raw: bytes | None = None
    hex_text = body.get("hex", "")
    if hex_text:
        cleaned = "".join(ch for ch in str(hex_text) if ch not in " \t\r\n:-")
        try:
            raw = binascii.unhexlify(cleaned)
        except (binascii.Error, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"hex 解析失败: {e}") from e
    elif body.get("data_base64"):
        try:
            raw = base64.b64decode(body["data_base64"])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"base64 解析失败: {e}") from e
    if not raw:
        raise HTTPException(status_code=400, detail="hex 或 data_base64 必须提供其一")
    try:
        return decode_frame(protocol, raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # 解码器兜底：单帧解析失败不炸服务
        logger.exception("decode_frame unexpected error: %s", e)
        raise HTTPException(status_code=500, detail=f"解码器内部错误: {e}") from e


@router.get("/compliance/decode-frame/protocols")
async def list_decodable_protocols(_user: dict[str, Any] = Depends(require_viewer)):
    """列出支持字段级解析的协议（v1.9.0）。"""
    from protoforge.testing.frame_decoder import supported_protocols
    return {"protocols": supported_protocols()}


@router.post("/compliance/check")
async def run_compliance_check(
    body: dict[str, Any],
    _user: dict[str, Any] = Depends(require_user),
):
    """Run compliance check on a recording.

    Request body:
    {
        "protocol": "modbus_tcp",
        "recording_id": "abc123"  // optional, if not provided will check recent messages
    }
    """
    from protoforge.testing.compliance import get_compliance_checker

    protocol = body.get("protocol", "")
    recording_id = body.get("recording_id", "")

    if not protocol:
        raise HTTPException(status_code=400, detail="protocol is required")

    checker = get_compliance_checker(protocol)
    if not checker:
        from protoforge.testing.compliance import get_supported_protocols as _get_supported
        raise HTTPException(
            status_code=400,
            detail=f"Compliance checking not supported for protocol: {protocol}. "
                  f"Supported: {_get_supported()}"
        )

    # Load messages from recording
    messages = []
    if recording_id:
        from protoforge.api.v1._helpers import _get_log_bus
        try:
            from protoforge.api.v1.recorder_routes import _get_recorder
            recorder = _get_recorder()
            rec = recorder.get_recording(recording_id)
            if rec:
                messages = [m.to_dict() for m in rec.messages]
            else:
                # Try loading from DB
                db = _get_database()
                rec_data = await db.load_recording(recording_id)
                if rec_data:
                    messages = rec_data.get("messages", [])
                else:
                    raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load recording: {e}") from e
    else:
        # Use recent log messages from log_bus entries
        from protoforge.api.v1._helpers import _get_log_bus
        log_bus = _get_log_bus()
        all_entries = list(log_bus._entries)
        # Filter to protocol-specific messages if possible
        messages = [
            {
                "direction": e.direction,
                "message_type": e.message_type,
                "summary": e.summary,
                "detail": e.detail,
                "device_id": e.device_id,
                "protocol": e.protocol,
            }
            for e in all_entries[-200:]  # last 200 messages
        ]

    if not messages:
        return {
            "status": "ok",
            "message": "No messages to check",
            "report": None,
        }

    # Run compliance check
    report = checker.check_messages(messages)
    report.recording_id = recording_id if isinstance(recording_id, str) else str(recording_id) if recording_id else ""

    # Persist to DB
    db = _get_database()
    try:
        await db.save_compliance_report(report.to_dict())
    except Exception as e:
        logger.warning("Failed to persist compliance report: %s", e)

    return report.to_dict()


@router.get("/compliance/reports")
async def list_compliance_reports(
    protocol: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    _user: dict[str, Any] = Depends(require_viewer),
):
    """List compliance reports."""
    db = _get_database()
    try:
        reports = await db.load_all_compliance_reports(limit=limit)
        if protocol:
            reports = [r for r in reports if r["protocol"] == protocol]
        return {"reports": reports}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load reports: {e}") from e


@router.get("/compliance/reports/{report_id}")
async def get_compliance_report(report_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    """Get a specific compliance report."""
    db = _get_database()
    try:
        report = await db.load_compliance_report(report_id)
        if not report:
            raise HTTPException(status_code=404, detail=f"Compliance report not found: {report_id}")
        return report
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load report: {e}") from e
