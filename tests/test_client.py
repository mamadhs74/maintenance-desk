from __future__ import annotations

import json
from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from maintdesk.api import create_app
from maintdesk.client import ApiClient, ApiError, ApiUnavailable
from maintdesk.models import Priority, Status
from maintdesk.repository import TicketRepository
from maintdesk.service import TicketService


def mocked(handler: Callable[[httpx.Request], httpx.Response]) -> ApiClient:
    http = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    return ApiClient("http://test", http=http)


TICKET = {
    "id": 3, "title": "Lager defekt", "machine": "F-3", "description": "", "priority": "high",
    "status": "open", "created_at": "2026-10-19T10:00:00+00:00", "updated_at": "2026-10-19T10:00:00+00:00",
    "assignee": None,
}


def test_list_sends_filters_as_query_parameters() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json=[TICKET])

    tickets = mocked(handler).list_tickets(Status.OPEN, "lager")
    assert [t.id for t in tickets] == [3]
    assert seen[0].params["status"] == "open" and seen[0].params["q"] == "lager"


def test_create_sends_json_body() -> None:
    bodies: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json=TICKET)

    mocked(handler).create_ticket("Lager defekt", "F-3", "", Priority.HIGH)
    assert bodies == [{"title": "Lager defekt", "machine": "F-3", "description": "", "priority": "high"}]


def test_error_body_becomes_api_error() -> None:
    client = mocked(lambda r: httpx.Response(409, json={"error": "invalid_transition", "message": "nope"}))
    with pytest.raises(ApiError) as info:
        client.set_status(1, Status.DONE)
    assert (info.value.status_code, info.value.code, info.value.message) == (409, "invalid_transition", "nope")


def test_error_without_json_body_still_becomes_api_error() -> None:
    with pytest.raises(ApiError) as info:
        mocked(lambda r: httpx.Response(502, text="<html>Bad Gateway</html>")).list_tickets()
    assert info.value.status_code == 502 and info.value.code == "http_error"


def test_unreachable_server_becomes_api_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ApiUnavailable, match="cannot be reached"):
        mocked(handler).list_tickets()


def test_timeout_becomes_api_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ApiUnavailable, match="in time"):
        mocked(handler).list_tickets()


@pytest.mark.parametrize("payload", [{"not": "a list"}, ["not a ticket"], [{"id": 1}]])
def test_answer_in_the_wrong_shape_is_reported_not_crashed(payload: object) -> None:
    with pytest.raises(ApiError) as info:
        mocked(lambda r: httpx.Response(200, json=payload)).list_tickets()
    assert info.value.code == "bad_response"


@pytest.fixture
def live(repo: TicketRepository) -> Iterator[ApiClient]:
    """The real client against the real API and a real store, in one process."""
    with TestClient(create_app(TicketService(repo)), base_url="http://testserver") as http:
        yield ApiClient("http://testserver", http=http)


def test_client_against_real_api(live: ApiClient) -> None:
    created = live.create_ticket("Lager defekt", "F-3", "laut", Priority.HIGH)
    assert created.status is Status.OPEN
    started = live.set_status(created.id, Status.IN_PROGRESS, "Anna")
    assert started.assignee == "Anna"
    assert [t.id for t in live.list_tickets(Status.IN_PROGRESS)] == [created.id]
    with pytest.raises(ApiError) as info:
        live.set_status(created.id, Status.OPEN if False else Status.IN_PROGRESS, "Anna")
    assert info.value.code == "invalid_transition"
    live.delete_ticket(created.id)
    assert live.list_tickets() == []
