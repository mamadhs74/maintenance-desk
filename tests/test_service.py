from __future__ import annotations

import pytest

from maintdesk.models import InvalidTransition, NotFound, Priority, Status, ValidationError
from maintdesk.repository import TicketRepository
from maintdesk.service import TicketService


class Clock:
    def __init__(self) -> None:
        self.minute = 0

    def __call__(self) -> str:
        self.minute += 1
        return f"2026-10-19T10:{self.minute:02d}:00+00:00"


@pytest.fixture
def service(repo: TicketRepository) -> TicketService:
    return TicketService(repo, clock=Clock())


def test_create_validates_and_stamps_time(service: TicketService) -> None:
    ticket = service.create("  Lager defekt ", "F-3", priority=Priority.HIGH)
    assert (ticket.title, ticket.status, ticket.created_at) == ("Lager defekt", Status.OPEN, "2026-10-19T10:01:00+00:00")
    with pytest.raises(ValidationError):
        service.create("", "F-3")


def test_normal_life_of_a_ticket(service: TicketService) -> None:
    ticket = service.create("Lager defekt", "F-3")
    started = service.set_status(ticket.id, Status.IN_PROGRESS, "Anna")
    assert (started.status, started.assignee) == (Status.IN_PROGRESS, "Anna")
    assert started.updated_at > ticket.updated_at
    done = service.set_status(ticket.id, Status.DONE)
    assert (done.status, done.assignee) == (Status.DONE, "Anna")
    reopened = service.set_status(ticket.id, Status.OPEN)
    assert reopened.status is Status.OPEN


def test_cannot_skip_a_step(service: TicketService) -> None:
    ticket = service.create("Lager defekt", "F-3")
    with pytest.raises(InvalidTransition):
        service.set_status(ticket.id, Status.DONE)
    assert service.get(ticket.id).status is Status.OPEN


def test_same_status_is_not_a_transition(service: TicketService) -> None:
    ticket = service.create("Lager defekt", "F-3")
    with pytest.raises(InvalidTransition):
        service.set_status(ticket.id, Status.OPEN)


def test_starting_work_needs_an_assignee(service: TicketService) -> None:
    ticket = service.create("Lager defekt", "F-3")
    for missing in (None, "", "   "):
        with pytest.raises(ValidationError):
            service.set_status(ticket.id, Status.IN_PROGRESS, missing)
    assert service.get(ticket.id).status is Status.OPEN


def test_previous_assignee_is_kept_when_work_restarts(service: TicketService) -> None:
    ticket = service.create("Lager defekt", "F-3")
    service.set_status(ticket.id, Status.IN_PROGRESS, "Anna")
    service.set_status(ticket.id, Status.OPEN)
    restarted = service.set_status(ticket.id, Status.IN_PROGRESS)
    assert restarted.assignee == "Anna"


def test_unknown_ticket(service: TicketService) -> None:
    with pytest.raises(NotFound):
        service.set_status(77, Status.IN_PROGRESS, "Anna")
    with pytest.raises(NotFound):
        service.delete(77)
