import logging
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1.auth import require_operator, require_viewer

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/webhooks")
async def list_webhooks(_user: dict = Depends(require_viewer)):
    from protoforge.core.webhook import webhook_manager
    return webhook_manager.list_webhooks()


@router.post("/webhooks")
async def add_webhook(config: dict[str, Any], _user: dict = Depends(require_operator)):
    from protoforge.core.webhook import webhook_manager

    if "url" not in config:
        raise HTTPException(status_code=400, detail="url is required")

    url = config.get("url", "")
    if not re.match(r'^https?://', url):
        raise HTTPException(status_code=400, detail="url 必须以 http:// 或 https:// 开头")

    webhook = webhook_manager.add_webhook(config)
    return webhook.to_dict()


@router.put("/webhooks/{wh_id}")
async def update_webhook(wh_id: str, config: dict[str, Any], _user: dict = Depends(require_operator)):
    from protoforge.core.webhook import webhook_manager
    webhook = webhook_manager.update_webhook(wh_id, config)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook.to_dict()


@router.delete("/webhooks/{wh_id}")
async def delete_webhook(wh_id: str, _user: dict = Depends(require_operator)):
    from protoforge.core.webhook import webhook_manager
    if not webhook_manager.remove_webhook(wh_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"status": "ok"}


@router.post("/webhooks/{wh_id}/test")
async def test_webhook(wh_id: str, _user: dict = Depends(require_operator)):
    from protoforge.core.webhook import webhook_manager
    webhook = webhook_manager.get_webhook(wh_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    try:
        await webhook_manager._send_single(webhook, {"event": "test", "message": "Test webhook from ProtoForge", "webhook_id": wh_id, "timestamp": time.time()})
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Webhook test failed: {str(e)}")


@router.get("/webhooks/stats")
async def webhook_stats(_user: dict = Depends(require_viewer)):
    from protoforge.core.webhook import webhook_manager
    return webhook_manager.get_stats()
