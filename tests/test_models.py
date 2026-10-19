from __future__ import annotations

import pytest

from maintdesk.models import (
    ALLOWED_TRANSITIONS,
    MAX_TITLE,
    NewTicket,
    Status,
    Ticket,
    ValidationError,
    clean_assignee,
    validate_new,
)
from conftest import make_ticket


def test_validate_trims_whitespace() -> None:
    ticket = validate_new(NewTicket("  Lager defekt  ", " F-3 ", "  laut  "))
    assert (ticket.title, ticket.machine, ticket.description) == ("Lager defekt", "F-3", "laut")


@pytest.mark.parametrize("title,machine", [("", "F-3"), ("   ", "F-3"), ("Defekt", ""), ("Defekt", "  ")])
def test_validate_rejects_empty_required_fields(title: str, machine: str) -> None:
    with pytest.raises(ValidationError):
        validate_new(NewTicket(title, machine))


def test_validate_rejects_too_long_title() -> None:
    with pytest.raises(ValidationError):
        validate_new(NewTicket("x" * (MAX_TITLE + 1), "F-3"))


def test_every_status_has_a_rule_and_none_points_to_itself() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(Status)
    for status, targets in ALLOWED_TRANSITIONS.items():
        assert status not in targets


def test_cannot_skip_from_open_to_done() -> None:
    assert Status.DONE not in ALLOWED_TRANSITIONS[Status.OPEN]


def test_ticket_dict_round_trip() -> None:
    ticket = make_ticket(assignee="A. Beispiel", status="in_progress")
    assert Ticket.from_dict(ticket.to_dict()) == ticket


@pytest.mark.parametrize("broken", [{"id": "x"}, {"id": 1}, {"id": 1, "priority": "urgent"}])
def test_from_dict_reports_bad_data_as_validation_error(broken: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Ticket.from_dict(broken)


def test_clean_assignee() -> None:
    assert clean_assignee(None) is None
    assert clean_assignee("   ") is None
    assert clean_assignee(" Anna ") == "Anna"
