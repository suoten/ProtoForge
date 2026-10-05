"""Cross-check MEWTOCOL frames against hiroeorz/mewtocol-go README vectors.

The mewtocol-go serial example documents (verbatim):
  request : %01#RCSX00001D   (RCS X0, BCC=1D)
  response: %01$RC021        (contact off, body "0", BCC=21)

These vectors exercise the exact BCC scope (XOR including '%') and the
response layout ('$' + cmd + 1-digit contact data, 2-digit... here body '0').
"""
import os

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_DB_PATH", "sqlite:///./data/test_mewtocol_xcheck.db")

import asyncio

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.mewtocol.server import MewtocolServer, bcc


def test_go_readme_request_vector_bcc():
    """mewtocol-go README 的请求帧 BCC 向量：XOR 含 '%'。"""
    assert bcc("%01#RCSX0000") == "1D"


def test_go_readme_response_vector_bcc():
    """mewtocol-go README 的响应帧 BCC 向量：'%01$RC0' -> BCC 21。"""
    assert bcc("%01$RC0") == "21"


@pytest.mark.asyncio
async def test_go_readme_vector_end_to_end():
    """发 README 的原始请求帧（逐字节），服务端必须逐字节复现 README 的响应。"""
    server = MewtocolServer()
    await server.create_device(DeviceConfig(
        id="go-x", name="gox", protocol="mewtocol", protocol_config={"station_number": 1},
        points=[PointConfig(name="x0", address="X0", data_type="bool")],
    ))
    request = "%01#RCSX00001D\r"          # README 原始帧（含其 BCC）
    response = server._process_frame(request.rstrip("\r"))
    assert response == "%01$RC021\r", f"got {response!r}"
    await server.stop()
