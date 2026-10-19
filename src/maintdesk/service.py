"""Business rules. Works with any TicketRepository."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from .models import (
    ALLOWED_TRANSITIONS,
    InvalidTransition,
    NewTicket,
    Priority,
    Status,
    Ticket,
    ValidationError,
    clean_assignee,
    utc_now_iso,
    validate_new,
)
from .repository import TicketRepository


class TicketService:
    def __init__(self, repo: TicketRepository, clock: Callable[[], str] = utc_now_iso) -> None:
        self._repo = repo
        self._clock = clock

    @property
    def repo(self) -> TicketRepository:
        return self._repo

    def create(
        self,
        title: str,
        machine: str,
        description: str = "",
        priority: Priority = Priority.NORMAL,
    ) -> Ticket:
        new = validate_new(NewTicket(title, machine, description, priority))
        return self._repo.add(new, self._clock())

    def get(self, ticket_id: int) -> Ticket:
        return self._repo.get(ticket_id)

    def list(
        self,
        status: Status | None = None,
        machine: str | None = None,
        text: str | None = None,
    ) -> list[Ticket]:
        return self._repo.list(status=status, machine=machine, text=text)

    def set_status(self, ticket_id: int, new_status: Status, assignee: str | None = None) -> Ticket:
        """Move a ticket to a new status. Starting work needs somebody who does it.

        Note: this is read-then-write. Two people changing the same ticket at the same moment
        can overwrite each other; the last write wins (see README, "Known limits").
        """
        ticket = self._repo.get(ticket_id)
        if new_status not in ALLOWED_TRANSITIONS[ticket.status]:
            raise InvalidTransition(f"cannot go from {ticket.status.value} to {new_status.value}")
        who = clean_assignee(assignee) or ticket.assignee
        if new_status is Status.IN_PROGRESS and not who:
            raise ValidationError("an assignee is required to start work")
        return self._repo.save(replace(ticket, status=new_status, assignee=who, updated_at=self._clock()))

    def delete(self, ticket_id: int) -> None:
        self._repo.delete(ticket_id)

    def count(self) -> int:
        return self._repo.count()
