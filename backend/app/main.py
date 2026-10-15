import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from app.metrics import MetricsResponse, MetricsService, MetricsUnavailable

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "InfraWatch"


def create_app(metrics_service: MetricsService | None = None) -> FastAPI:
    service = metrics_service or MetricsService()

    @asynccontextmanager
    async def lifespan(app):
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(title="InfraWatch", version="0.1.0", lifespan=lifespan)
    app.state.metrics_service = service

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.status_code, "message": exc.detail}},
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled API error")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": 500, "message": "Internal server error"}},
        )

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/api/metrics", response_model=MetricsResponse)
    async def metrics():
        try:
            result = app.state.metrics_service.response()
            return JSONResponse(
                content=result.model_dump(mode="json"),
                headers={"Cache-Control": "no-store"},
            )
        except MetricsUnavailable as exc:
            return JSONResponse(
                status_code=503,
                headers={"Cache-Control": "no-store", "Retry-After": "5"},
                content={
                    "error": {
                        "code": 503,
                        "message": "Metrics unavailable",
                        "reason": exc.reason,
                        "retryable": True,
                    }
                },
            )
        except Exception:
            # Handle at this boundary so ASGI does not re-log private exception details.
            logger.error("Metrics API internal error")
            return JSONResponse(
                status_code=500,
                headers={"Cache-Control": "no-store"},
                content={"error": {"code": 500, "message": "Internal server error"}},
            )

    return app


app = create_app()
