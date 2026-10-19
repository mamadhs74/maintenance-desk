from __future__ import annotations

from dataclasses import replace

from maintdesk.client import ApiError, ApiUnavailable
from maintdesk.desktop.viewmodel import TicketListViewModel, to_row
from maintdesk.models import Priority, Status, Ticket
from conftest import make_ticket


class FakeClient:
    def __init__(self) -> None:
        self.tickets: list[Ticket] = [
            make_ticket(id=1, title="A", status="open"),
            make_ticket(id=2, title="B", status="in_progress", assignee="Anna"),
            make_ticket(id=3, title="C", status="done"),
        ]
        self.fail_with: Exception | None = None
        self.calls: list[tuple[str, object]] = []

    def _maybe_fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    def list_tickets(self, status: Status | None = None, text: str | None = None) -> list[Ticket]:
        self.calls.append(("list", (status, text)))
        self._maybe_fail()
        return [t for t in self.tickets if (status is None or t.status is status) and (not text or text in t.title)]

    def create_ticket(self, title: str, machine: str, description: str = "", priority: Priority = Priority.NORMAL) -> Ticket:
        self._maybe_fail()
        ticket = make_ticket(id=len(self.tickets) + 1, title=title, machine=machine, priority=priority.value)
        self.tickets.append(ticket)
        return ticket

    def set_status(self, ticket_id: int, status: Status, assignee: str | None = None) -> Ticket:
        self._maybe_fail()
        index = next(i for i, t in enumerate(self.tickets) if t.id == ticket_id)
        self.tickets[index] = replace(self.tickets[index], status=status)
        return self.tickets[index]

    def delete_ticket(self, ticket_id: int) -> None:
        self._maybe_fail()
        self.tickets = [t for t in self.tickets if t.id != ticket_id]


def test_refresh_fills_rows_with_german_labels() -> None:
    vm = TicketListViewModel(FakeClient())
    assert vm.refresh() is True
    assert [r.status for r in vm.rows] == ["Offen", "In Arbeit", "Erledigt"]
    assert vm.rows[1].assignee == "Anna" and vm.rows[0].priority == "Normal"
    assert vm.summary() == "3 Aufträge: 1 offen, 1 in Arbeit, 1 erledigt"


def test_filter_and_search_are_sent_to_the_server() -> None:
    client = FakeClient()
    vm = TicketListViewModel(client)
    vm.status_filter, vm.search_text = Status.DONE, "C"
    vm.refresh()
    assert client.calls[-1] == ("list", (Status.DONE, "C"))
    assert [t.title for t in vm.tickets] == ["C"]


def test_create_set_status_and_delete_reload_the_list() -> None:
    vm = TicketListViewModel(FakeClient())
    assert vm.create("Neu", "F-3", "", Priority.HIGH) and len(vm.tickets) == 4
    assert vm.set_status(1, Status.IN_PROGRESS, "Anna") and vm.ticket(1) is not None
    assert vm.ticket(1).status is Status.IN_PROGRESS  # type: ignore[union-attr]
    assert vm.delete(4) and len(vm.tickets) == 3


def test_server_down_shows_a_message_and_keeps_old_rows() -> None:
    client = FakeClient()
    vm = TicketListViewModel(client)
    vm.refresh()
    client.fail_with = ApiUnavailable("The server cannot be reached (ConnectError).")
    assert vm.refresh() is False
    assert vm.error is not None and vm.error.startswith("Server nicht erreichbar")
    assert len(vm.tickets) == 3


def test_known_errors_get_friendly_german_text_and_unknown_ones_the_server_message() -> None:
    client = FakeClient()
    vm = TicketListViewModel(client)
    client.fail_with = ApiError(409, "invalid_transition", "cannot go from open to done")
    assert vm.set_status(1, Status.DONE) is False and vm.error == "Dieser Statuswechsel ist nicht erlaubt."
    client.fail_with = ApiError(422, "invalid_input", "title must not be empty")
    assert vm.create("", "F-3", "", Priority.NORMAL) is False and vm.error == "Fehler: title must not be empty"


def test_not_found_reloads_the_list() -> None:
    client = FakeClient()
    vm = TicketListViewModel(client)
    vm.refresh()
    client.tickets = client.tickets[:1]
    client.fail_with = ApiError(404, "not_found", "gone")
    # the reload inside the error path would also fail; simulate a server that works for list only
    original = client.list_tickets

    def list_ok(status: Status | None = None, text: str | None = None) -> list[Ticket]:
        client.fail_with, saved = None, client.fail_with
        try:
            return original(status, text)
        finally:
            client.fail_with = saved

    client.list_tickets = list_ok  # type: ignore[method-assign]
    assert vm.delete(3) is False
    assert vm.error is not None and "existiert nicht mehr" in vm.error
    assert len(vm.tickets) == 1


def test_error_is_cleared_by_the_next_success() -> None:
    client = FakeClient()
    vm = TicketListViewModel(client)
    client.fail_with = ApiUnavailable("x")
    vm.refresh()
    client.fail_with = None
    assert vm.refresh() is True and vm.error is None


def test_to_row_formats_the_time() -> None:
    row = to_row(make_ticket(updated_at="2026-10-19T14:05:33+00:00"))
    assert row.updated == "2026-10-19 14:05"
