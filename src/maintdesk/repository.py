"""The one interface every data store has to follow. The service only knows this."""

from __future__ import annotations

from typing import Protocol

from .models import NewTicket, Status, Ticket


class TicketRepository(Protocol):
    def add(self, new: NewTicket, now: str) -> Ticket:
        """Store a new (already validated) ticket as open and return it with its new id."""

    def get(self, ticket_id: int) -> Ticket:
        """Return the ticket or raise NotFound."""

    def list(
        self,
        status: Status | None = None,
        machine: str | None = None,
        text: str | None = None,
    ) -> list[Ticket]:
        """Tickets sorted by id. `machine` must match exactly. `text` is a case-insensitive
        search in title and description."""

    def save(self, ticket: Ticket) -> Ticket:
        """Replace the stored ticket with the same id or raise NotFound."""

    def delete(self, ticket_id: int) -> None:
        """Remove the ticket or raise NotFound."""

    def count(self) -> int: ...

    def close(self) -> None: ...
