"""ProtoForge application entry point.

This file provides a standard WSGI/ASGI entry point for ProtoForge.
It can be used with any ASGI server:

    uvicorn app:app --host 0.0.0.0 --port 8000
    gunicorn -k uvicorn.workers.UvicornWorker app:app

Or simply:
    python app.py
"""
from protoforge.main import app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
