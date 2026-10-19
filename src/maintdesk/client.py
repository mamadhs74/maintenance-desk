"""HTTP client for the JSON API. The desktop app talks to the server only through this."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from .models import Priority, Status, Ticket, ValidationError


class ApiError(Exception):
    """The server answered with an error (404, 409, 422, 503 ...)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class ApiUnavailable(Exception):
    """The server could not be reached or did not answer in time."""


class TicketClient(Protocol):
    def list_tickets(
        self, status: Status | None = None, text: str | None = None
    ) -> list[Ticket]: ...

    def create_ticket(
        self, title: str, machine: str, description: str = "", priority: Priority = Priority.NORMAL
    ) -> Ticket: ...

    def set_status(self, ticket_id: int, status: Status, assignee: str | None = None) -> Ticket: ...

    def delete_ticket(self, ticket_id: int) -> None: ...


@dataclass
class ApiClient:
    base_url: str
    http: httpx.Client | None = None
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if self.http is None:
            self.http = httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        assert self.http is not None
        try:
            response = self.http.request(method, path, **kwargs)  # type: ignore[arg-type]
        except httpx.TimeoutException as exc:
            raise ApiUnavailable("The server did not answer in time.") from exc
        except httpx.TransportError as exc:
            raise ApiUnavailable(f"The server cannot be reached ({type(exc).__name__}).") from exc
        if response.status_code >= 400:
            raise self._to_error(response)
        return response

    @staticmethod
    def _to_error(response: httpx.Response) -> ApiError:
        try:
            body = response.json()
            return ApiError(response.status_code, str(body["error"]), str(body["message"]))
        except (ValueError, KeyError, TypeError):
            return ApiError(response.status_code, "http_error", f"Server answered {response.status_code}.")

    @staticmethod
    def _ticket(data: object) -> Ticket:
        if not isinstance(data, dict):
            raise ApiError(502, "bad_response", "The server sent data in an unexpected shape.")
        try:
            return Ticket.from_dict(data)
        except ValidationError as exc:
            raise ApiError(502, "bad_response", str(exc)) from exc

    def list_tickets(self, status: Status | None = None, text: str | None = None) -> list[Ticket]:
        params: dict[str, str] = {}
        if status is not None:
            params["status"] = status.value
        if text:
            params["q"] = text
        data = self._request("GET", "/tickets", params=params).json()
        if not isinstance(data, list):
            raise ApiError(502, "bad_response", "The server sent data in an unexpected shape.")
        return [self._ticket(item) for item in data]

    def create_ticket(
        self, title: str, machine: str, description: str = "", priority: Priority = Priority.NORMAL
    ) -> Ticket:
        body = {"title": title, "machine": machine, "description": description, "priority": priority.value}
        return self._ticket(self._request("POST", "/tickets", json=body).json())

    def set_status(self, ticket_id: int, status: Status, assignee: str | None = None) -> Ticket:
        body: dict[str, str | None] = {"status": status.value, "assignee": assignee}
        return self._ticket(self._request("POST", f"/tickets/{ticket_id}/status", json=body).json())

    def delete_ticket(self, ticket_id: int) -> None:
        self._request("DELETE", f"/tickets/{ticket_id}")

    def close(self) -> None:
        if self.http is not None:
            self.http.close()
