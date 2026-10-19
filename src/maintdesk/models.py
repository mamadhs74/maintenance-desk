"""Data types and business rules. No database code and no web code in this file."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

MAX_TITLE = 120
MAX_TEXT = 2000


class MaintDeskError(Exception):
    """Base class for all errors of this package."""


class ValidationError(MaintDeskError):
    """The input is not acceptable (empty title, too long, assignee missing ...)."""


class NotFound(MaintDeskError):
    """No ticket with this id."""


class InvalidTransition(MaintDeskError):
    """The status change is not allowed (for example open -> done)."""


class RepositoryError(MaintDeskError):
    """The data store cannot be used (server down, database file locked, wrong version)."""


class Status(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


# Which status may follow which. A finished ticket can be reopened, but not skip a step.
ALLOWED_TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.OPEN: frozenset({Status.IN_PROGRESS}),
    Status.IN_PROGRESS: frozenset({Status.DONE, Status.OPEN}),
    Status.DONE: frozenset({Status.OPEN}),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class NewTicket:
    title: str
    machine: str
    description: str = ""
    priority: Priority = Priority.NORMAL


@dataclass(frozen=True)
class Ticket:
    id: int
    title: str
    machine: str
    description: str
    priority: Priority
    status: Status
    created_at: str
    updated_at: str
    assignee: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "machine": self.machine,
            "description": self.description,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "assignee": self.assignee,
        }

    @staticmethod
    def from_dict(data: Mapping[str, object]) -> Ticket:
        """Build a ticket from a JSON-like dict. Raises ValidationError for bad data."""
        try:
            assignee = data.get("assignee")
            return Ticket(
                id=int(str(data["id"])),
                title=str(data["title"]),
                machine=str(data["machine"]),
                description=str(data.get("description") or ""),
                priority=Priority(str(data["priority"])),
                status=Status(str(data["status"])),
                created_at=str(data["created_at"]),
                updated_at=str(data["updated_at"]),
                assignee=str(assignee) if assignee else None,
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError(f"ticket data is not valid: {exc!r}") from exc


def clean_text(value: str, *, field: str, required: bool, limit: int) -> str:
    text = value.strip()
    if required and not text:
        raise ValidationError(f"{field} must not be empty")
    if len(text) > limit:
        raise ValidationError(f"{field} is too long (max {limit} characters)")
    return text


def validate_new(new: NewTicket) -> NewTicket:
    return NewTicket(
        title=clean_text(new.title, field="title", required=True, limit=MAX_TITLE),
        machine=clean_text(new.machine, field="machine", required=True, limit=MAX_TITLE),
        description=clean_text(new.description, field="description", required=False, limit=MAX_TEXT),
        priority=new.priority,
    )


def clean_assignee(value: str | None) -> str | None:
    if value is None:
        return None
    text = clean_text(value, field="assignee", required=False, limit=MAX_TITLE)
    return text or None
