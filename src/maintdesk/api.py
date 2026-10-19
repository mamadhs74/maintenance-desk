"""JSON API (FastAPI). Thin: it translates HTTP to service calls and errors to status codes.

Status codes:  201 created, 204 deleted, 404 unknown ticket, 409 status change not allowed,
422 bad input, 503 data store not reachable, 500 anything unexpected (logged with a request id).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import Settings, build_repository
from .models import (
    InvalidTransition,
    MaintDeskError,
    NotFound,
    Priority,
    RepositoryError,
    Status,
    Ticket,
    ValidationError,
)
from .service import TicketService

log = logging.getLogger("maintdesk.api")


class CreateTicketBody(BaseModel):
    title: str = Field(max_length=500)
    machine: str = Field(max_length=500)
    description: str = Field(default="", max_length=5000)
    priority: Priority = Priority.NORMAL


class StatusBody(BaseModel):
    status: Status
    assignee: str | None = Field(default=None, max_length=500)


class TicketOut(BaseModel):
    id: int
    title: str
    machine: str
    description: str
    priority: Priority
    status: Status
    created_at: str
    updated_at: str
    assignee: str | None

    @staticmethod
    def of(ticket: Ticket) -> TicketOut:
        return TicketOut(**ticket.to_dict())  # type: ignore[arg-type]


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": code, "message": message})


def create_app(service: TicketService, backend_name: str = "unknown") -> FastAPI:
    app = FastAPI(title="Maintenance Desk", version="0.1.0")

    @app.middleware("http")
    async def access_log(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:8]
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = request_id
        log.info(
            "%s %s -> %s in %.1f ms [%s]",
            request.method, request.url.path, response.status_code, elapsed_ms, request_id,
        )
        return response

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound) -> JSONResponse:
        return _error(404, "not_found", str(exc))

    @app.exception_handler(InvalidTransition)
    async def _conflict(_: Request, exc: InvalidTransition) -> JSONResponse:
        return _error(409, "invalid_transition", str(exc))

    @app.exception_handler(ValidationError)
    async def _invalid(_: Request, exc: ValidationError) -> JSONResponse:
        return _error(422, "invalid_input", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _invalid_body(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        return _error(422, "invalid_input", f"{where}: {first.get('msg', 'invalid value')}".strip(": "))

    @app.exception_handler(RepositoryError)
    async def _store_down(_: Request, exc: RepositoryError) -> JSONResponse:
        log.error("data store problem: %s", exc)
        return _error(503, "store_unavailable", "The data store is not available right now.")

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        incident = uuid.uuid4().hex[:8]
        log.exception("unexpected error [%s] on %s %s", incident, request.method, request.url.path)
        return _error(500, "internal_error", f"Unexpected error. Reference: {incident}")

    @app.get("/health")
    def health() -> dict[str, object]:
        # counts tickets, so a broken data store shows up here as 503
        return {"status": "ok", "backend": backend_name, "tickets": service.count()}

    @app.post("/tickets", status_code=201, response_model=TicketOut)
    def create_ticket(body: CreateTicketBody) -> TicketOut:
        return TicketOut.of(service.create(body.title, body.machine, body.description, body.priority))

    @app.get("/tickets", response_model=list[TicketOut])
    def list_tickets(
        status: Status | None = None,
        machine: str | None = None,
        q: str | None = Query(default=None, max_length=200),
    ) -> list[TicketOut]:
        return [TicketOut.of(t) for t in service.list(status=status, machine=machine, text=q)]

    @app.get("/tickets/{ticket_id}", response_model=TicketOut)
    def get_ticket(ticket_id: int) -> TicketOut:
        return TicketOut.of(service.get(ticket_id))

    @app.post("/tickets/{ticket_id}/status", response_model=TicketOut)
    def change_status(ticket_id: int, body: StatusBody) -> TicketOut:
        return TicketOut.of(service.set_status(ticket_id, body.status, body.assignee))

    @app.delete("/tickets/{ticket_id}", status_code=204)
    def delete_ticket(ticket_id: int) -> Response:
        service.delete(ticket_id)
        return Response(status_code=204)

    return app


def app_from_env() -> FastAPI:
    """Factory for uvicorn: `uvicorn maintdesk.api:app_from_env --factory`."""
    settings = Settings.from_env()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        repo = build_repository(settings)
    except MaintDeskError:
        log.exception("cannot start: data store is not usable")
        raise
    return create_app(TicketService(repo), backend_name=settings.backend)
