import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class APIResponse:
    """统一的 API 响应格式"""

    @staticmethod
    def success(data: Any = None, message: str = "ok") -> dict:
        return {
            "code": 0,
            "data": data,
            "message": message,
            "timestamp": int(time.time() * 1000),
        }

    @staticmethod
    def error(
        message: str = "error",
        code: int = 500,
        data: Any = None,
        error_type: str = "",
        detail: Any = None,
    ) -> dict:
        result = {
            "code": code,
            "message": message,
            "timestamp": int(time.time() * 1000),
        }
        if data is not None:
            result["data"] = data
        if error_type:
            result["error_type"] = error_type
        if detail is not None:
            result["detail"] = detail
        return result

    @staticmethod
    def created(data: Any = None, message: str = "Created successfully") -> dict:
        return APIResponse.success(data=data, message=message)

    @staticmethod
    def updated(data: Any = None, message: str = "Updated successfully") -> dict:
        return APIResponse.success(data=data, message=message)

    @staticmethod
    def deleted(message: str = "Deleted successfully") -> dict:
        return APIResponse.success(message=message)

    @staticmethod
    def not_found(resource: str, identifier: str = "") -> dict:
        msg = f"{resource} not found"
        if identifier:
            msg += f": {identifier}"
        return APIResponse.error(message=msg, code=404, error_type="NotFoundError")

    @staticmethod
    def validation_error(field: str, reason: str = "") -> dict:
        msg = f"Validation failed for '{field}'"
        if reason:
            msg += f": {reason}"
        return APIResponse.error(message=msg, code=400, error_type="ValidationError", detail={"field": field})

    @staticmethod
    def unauthorized(message: str = "Authentication required") -> dict:
        return APIResponse.error(message=message, code=401, error_type="UnauthorizedError")

    @staticmethod
    def forbidden(message: str = "Access denied") -> dict:
        return APIResponse.error(message=message, code=403, error_type="ForbiddenError")


class ProtoForgeException(Exception):
    def __init__(self, message: str = "error", code: int = 500, status_code: int = 400, error_type: str = ""):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.error_type = error_type
        super().__init__(message)


class NotFoundException(ProtoForgeException):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message=message, code=404, status_code=404)


class ValidationException(ProtoForgeException):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message=message, code=400, status_code=400)


class UnauthorizedException(ProtoForgeException):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message=message, code=401, status_code=401)


class ForbiddenException(ProtoForgeException):
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message=message, code=403, status_code=403)


class ConflictException(ProtoForgeException):
    def __init__(self, message: str = "Resource conflict"):
        super().__init__(message=message, code=409, status_code=409)


def setup_exception_handlers(app) -> None:
    from fastapi.exceptions import HTTPException

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=APIResponse.error(message=str(exc.detail), code=exc.status_code),
        )

    @app.exception_handler(ProtoForgeException)
    async def protoforge_exception_handler(request: Request, exc: ProtoForgeException):
        return JSONResponse(
            status_code=exc.status_code,
            content=APIResponse.error(message=exc.message, code=exc.code),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        import logging
        logger = logging.getLogger("protoforge.api")
        logger.warning("ValueError in API: %s", exc)
        raw_msg = str(exc)
        if "invalid literal for int()" in raw_msg:
            friendly_msg = "Invalid parameter value: expected a number but received a non-numeric value"
        elif "could not convert" in raw_msg:
            friendly_msg = "Invalid parameter type: could not convert value to the expected format"
        else:
            friendly_msg = f"Invalid value: {raw_msg}" if len(raw_msg) < 100 else "Invalid parameter value"
        return JSONResponse(
            status_code=400,
            content=APIResponse.error(message=friendly_msg, code=400),
        )

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError):
        import logging
        logger = logging.getLogger("protoforge.api")
        logger.error("RuntimeError in API: %s", exc)
        msg = str(exc)
        if "not initialized" in msg.lower():
            return JSONResponse(
                status_code=503,
                content=APIResponse.error(message="Service is starting up, please try again later", code=503),
            )
        friendly_msg = msg if len(msg) < 100 else "A runtime error occurred"
        return JSONResponse(
            status_code=500,
            content=APIResponse.error(message=friendly_msg, code=500),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        import logging
        logger = logging.getLogger("protoforge.api")
        logger.exception("Unhandled exception in API: %s", exc)
        return JSONResponse(
            status_code=500,
            content=APIResponse.error(message="Internal server error", code=500),
        )
