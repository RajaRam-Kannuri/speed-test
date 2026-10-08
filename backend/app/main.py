"""LorvenLax AI Testing Platform - HTTP API."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .routers import (
    api_testing,
    assistant,
    auth,
    dashboard,
    organizations,
    projects,
    runs,
    system,
    tests,
    website,
)

logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
log = logging.getLogger("lorvenlax.api")

settings = get_settings()
app = FastAPI(
    title="LorvenLax AI Testing Platform API",
    version="0.1.0",
    description="Projects, tests, AI generation, executions and reports. Authenticate with the session cookie "
    "(browser) or a project API token (`Authorization: Bearer llx_...`) for CI/CD.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001
        log.exception("unhandled error request_id=%s path=%s", request_id, request.url.path)
        response = JSONResponse({"detail": "Something went wrong on our side. Try again, and contact support with this id if it continues.",
                                 "request_id": request_id}, status_code=500)
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["referrer-policy"] = "same-origin"
    log.info("request id=%s method=%s path=%s status=%s ms=%d", request_id, request.method, request.url.path,
             response.status_code, (time.perf_counter() - started) * 1000)
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    problems = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", []) if x not in ("body", "query", "path"))
        problems.append(f"{loc}: {err.get('msg')}" if loc else err.get("msg"))
    return JSONResponse({"detail": "; ".join(problems) or "Invalid request", "errors": problems}, status_code=422)


for module in (system, auth, organizations, projects, tests, runs, website, api_testing, assistant, dashboard):
    app.include_router(module.router, prefix="/api")
