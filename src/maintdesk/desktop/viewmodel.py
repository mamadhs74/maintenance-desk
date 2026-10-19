"""Logic of the desktop window, without any Qt code, so it can be tested without a screen.

The window only shows what is in here and calls these methods. Every method returns True or False
and puts a readable German message into `error` when something went wrong.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..client import ApiError, ApiUnavailable, TicketClient
from ..models import Priority, Status, Ticket

STATUS_LABELS = {Status.OPEN: "Offen", Status.IN_PROGRESS: "In Arbeit", Status.DONE: "Erledigt"}
PRIORITY_LABELS = {Priority.LOW: "Niedrig", Priority.NORMAL: "Normal", Priority.HIGH: "Hoch"}

_ERROR_TEXT = {
    "not_found": "Dieser Auftrag existiert nicht mehr. Die Liste wird neu geladen.",
    "invalid_transition": "Dieser Statuswechsel ist nicht erlaubt.",
    "store_unavailable": "Der Server hat gerade keinen Zugriff auf die Datenbank. Bitte später erneut versuchen.",
}


@dataclass(frozen=True)
class Row:
    id: int
    title: str
    machine: str
    priority: str
    status: str
    assignee: str
    updated: str


def to_row(ticket: Ticket) -> Row:
    return Row(
        id=ticket.id,
        title=ticket.title,
        machine=ticket.machine,
        priority=PRIORITY_LABELS[ticket.priority],
        status=STATUS_LABELS[ticket.status],
        assignee=ticket.assignee or "",
        updated=ticket.updated_at.replace("T", " ")[:16],
    )


class TicketListViewModel:
    def __init__(self, client: TicketClient) -> None:
        self._client = client
        self.tickets: list[Ticket] = []
        self.error: str | None = None
        self.status_filter: Status | None = None
        self.search_text: str = ""

    # -- what the window shows ---------------------------------------------
    @property
    def rows(self) -> list[Row]:
        return [to_row(ticket) for ticket in self.tickets]

    def summary(self) -> str:
        counts = {status: 0 for status in Status}
        for ticket in self.tickets:
            counts[ticket.status] += 1
        return (
            f"{len(self.tickets)} Aufträge: {counts[Status.OPEN]} offen, "
            f"{counts[Status.IN_PROGRESS]} in Arbeit, {counts[Status.DONE]} erledigt"
        )

    def ticket(self, ticket_id: int) -> Ticket | None:
        return next((t for t in self.tickets if t.id == ticket_id), None)

    # -- actions ----------------------------------------------------------
    def refresh(self) -> bool:
        return self._run(self._load)

    def create(self, title: str, machine: str, description: str, priority: Priority) -> bool:
        def action() -> None:
            self._client.create_ticket(title, machine, description, priority)
            self._load()

        return self._run(action)

    def set_status(self, ticket_id: int, status: Status, assignee: str | None = None) -> bool:
        def action() -> None:
            self._client.set_status(ticket_id, status, assignee)
            self._load()

        return self._run(action)

    def delete(self, ticket_id: int) -> bool:
        def action() -> None:
            self._client.delete_ticket(ticket_id)
            self._load()

        return self._run(action)

    # -- internals ----------------------------------------------------------
    def _load(self) -> None:
        self.tickets = self._client.list_tickets(self.status_filter, self.search_text or None)

    def _run(self, action: Callable[[], None]) -> bool:
        self.error = None
        try:
            action()
            return True
        except ApiUnavailable as exc:
            self.error = f"Server nicht erreichbar: {exc}"
        except ApiError as exc:
            self.error = _ERROR_TEXT.get(exc.code) or f"Fehler: {exc.message}"
            if exc.code == "not_found":
                try:
                    self._load()
                except (ApiError, ApiUnavailable):
                    pass
        return False
