from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from maintdesk.api import create_app
from maintdesk.models import NewTicket, RepositoryError, Status, Ticket
from maintdesk.repository import TicketRepository
from maintdesk.service import TicketService


@pytest.fixture
def client(repo: TicketRepository) -> Iterator[TestClient]:
    with TestClient(create_app(TicketService(repo), backend_name="test")) as test_client:
        yield test_client


def create(client: TestClient, title: str = "Lager defekt", machine: str = "F-3", **extra: object) -> dict[str, object]:
    response = client.post("/tickets", json={"title": title, "machine": machine, **extra})
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_health_reports_backend_and_count(client: TestClient) -> None:
    create(client)
    assert client.get("/health").json() == {"status": "ok", "backend": "test", "tickets": 1}


def test_create_and_read_back(client: TestClient) -> None:
    created = create(client, priority="high", description="laut")
    assert created["status"] == "open" and created["priority"] == "high" and created["assignee"] is None
    assert client.get(f"/tickets/{created['id']}").json() == created


def test_list_with_filters(client: TestClient) -> None:
    first = create(client, "Lager defekt", "F-3")
    create(client, "Öl nachfüllen", "P-12")
    client.post(f"/tickets/{first['id']}/status", json={"status": "in_progress", "assignee": "Anna"})
    assert len(client.get("/tickets").json()) == 2
    assert [t["id"] for t in client.get("/tickets", params={"status": "in_progress"}).json()] == [first["id"]]
    assert [t["machine"] for t in client.get("/tickets", params={"machine": "P-12"}).json()] == ["P-12"]
    assert [t["title"] for t in client.get("/tickets", params={"q": "ÖL"}).json()] == ["Öl nachfüllen"]


def test_status_flow_over_http(client: TestClient) -> None:
    ticket_id = create(client)["id"]
    started = client.post(f"/tickets/{ticket_id}/status", json={"status": "in_progress", "assignee": "Anna"})
    assert started.status_code == 200 and started.json()["assignee"] == "Anna"
    done = client.post(f"/tickets/{ticket_id}/status", json={"status": "done"})
    assert done.json()["status"] == "done"


def test_delete_returns_204_then_404(client: TestClient) -> None:
    ticket_id = create(client)["id"]
    assert client.delete(f"/tickets/{ticket_id}").status_code == 204
    assert client.delete(f"/tickets/{ticket_id}").status_code == 404
    assert client.get(f"/tickets/{ticket_id}").json()["error"] == "not_found"


def test_unknown_ticket_is_404(client: TestClient) -> None:
    response = client.post("/tickets/999/status", json={"status": "in_progress", "assignee": "Anna"})
    assert response.status_code == 404 and response.json()["error"] == "not_found"


def test_forbidden_transition_is_409(client: TestClient) -> None:
    ticket_id = create(client)["id"]
    response = client.post(f"/tickets/{ticket_id}/status", json={"status": "done"})
    assert response.status_code == 409 and response.json()["error"] == "invalid_transition"


@pytest.mark.parametrize(
    "body",
    [
        {"title": "", "machine": "F-3"},                       # business rule (service)
        {"title": "x", "machine": "  "},                        # business rule (service)
        {"machine": "F-3"},                                    # missing field (pydantic)
        {"title": "x", "machine": "F-3", "priority": "urgent"},  # unknown value (pydantic)
        {"title": "x" * 600, "machine": "F-3"},                  # too long (pydantic)
    ],
)
def test_bad_input_is_422_with_a_message(client: TestClient, body: dict[str, object]) -> None:
    response = client.post("/tickets", json=body)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_input" and response.json()["message"]


def test_starting_work_without_assignee_is_422(client: TestClient) -> None:
    ticket_id = create(client)["id"]
    assert client.post(f"/tickets/{ticket_id}/status", json={"status": "in_progress"}).status_code == 422


def test_non_numeric_id_is_422(client: TestClient) -> None:
    assert client.get("/tickets/abc").status_code == 422


def test_every_answer_has_a_request_id_and_it_is_passed_through(client: TestClient) -> None:
    assert client.get("/health").headers["x-request-id"]
    assert client.get("/health", headers={"x-request-id": "abc123"}).headers["x-request-id"] == "abc123"


class BrokenRepository:
    """Every call fails the way a dead database server would."""

    def __getattr__(self, name: str) -> object:
        def fail(*args: object, **kwargs: object) -> object:
            raise RepositoryError("connection refused")

        return fail


def test_dead_data_store_gives_503_not_a_crash(caplog: pytest.LogCaptureFixture) -> None:
    broken: TicketRepository = BrokenRepository()  # type: ignore[assignment]
    with TestClient(create_app(TicketService(broken))) as client:
        with caplog.at_level(logging.ERROR, logger="maintdesk.api"):
            for response in (client.get("/health"), client.get("/tickets"), client.post("/tickets", json={"title": "a", "machine": "b"})):
                assert response.status_code == 503
                assert response.json()["error"] == "store_unavailable"
    assert "connection refused" in caplog.text


def test_unexpected_bug_gives_500_with_reference_and_no_internals(caplog: pytest.LogCaptureFixture) -> None:
    class Exploding(BrokenRepository):
        def __getattr__(self, name: str) -> object:
            def boom(*args: object, **kwargs: object) -> object:
                raise ZeroDivisionError("secret internal detail")

            return boom

    service = TicketService(Exploding())  # type: ignore[arg-type]
    with TestClient(create_app(service), raise_server_exceptions=False) as client:
        with caplog.at_level(logging.ERROR, logger="maintdesk.api"):
            response = client.get("/tickets")
    body = response.json()
    assert response.status_code == 500 and body["error"] == "internal_error"
    assert "secret" not in response.text and "Reference:" in body["message"]
    reference = body["message"].split("Reference: ")[1]
    assert reference in caplog.text and "ZeroDivisionError" in caplog.text


def test_response_never_contains_a_ticket_object_type_error(client: TestClient) -> None:
    """The JSON uses plain strings for enums, so any client can read it."""
    created = create(client)
    assert created["priority"] in {"low", "normal", "high"}
    assert created["status"] in {s.value for s in Status}
    assert isinstance(created["id"], int)


def test_service_unused_imports_are_not_needed() -> None:
    assert Ticket and NewTicket
