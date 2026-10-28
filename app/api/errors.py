import sqlite3
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from app.schemas.api import ErrorOutput
from app.llm.errors import ModelSelectionError

ERROR_RESPONSES = {code: {"model": ErrorOutput, "description": description} for code, description in (
    (400, "Invalid request"), (401, "Login required"), (403, "Administrator access required"), (404, "Resource not found"),
    (409, "Version or idempotency conflict"), (503, "Database unavailable"))}


def business_responses(model):
    responses = {code: dict(value) for code, value in ERROR_RESPONSES.items()}
    for code in (400, 404, 409, 503):
        responses[code]["model"] = ErrorOutput | model
    return responses


class ApiError(Exception):
    def __init__(self, status, error, message=None, *, details=None):
        self.status, self.error, self.message = status, error, message
        self.details = details


def install_handlers(app):
    @app.exception_handler(ModelSelectionError)
    async def model_error(request, exc):
        return JSONResponse({"error": exc.code, "message": str(exc)}, status_code=exc.status)

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        body = {"error": exc.error}
        if exc.message:
            body["message"] = exc.message
        if exc.details is not None:
            body["details"] = exc.details
        return JSONResponse(body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Do not echo user inputs (particularly passwords) in validation responses.
        issues = [{"loc": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]
        code = "INVALID_JSON" if any(e["type"] == "json_invalid" for e in exc.errors()) else "INVALID_FIELDS"
        return JSONResponse({"error": code, "details": issues}, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse({"error": code}, status_code=exc.status_code, headers=exc.headers)

    async def database_error(request, exc):
        return JSONResponse({"error": "DB_ERROR"}, status_code=503)

    app.add_exception_handler(sqlite3.Error, database_error)
    app.add_exception_handler(OSError, database_error)
