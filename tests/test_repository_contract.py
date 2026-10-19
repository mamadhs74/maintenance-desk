"""The same behaviour is demanded from the SQL store and the NoSQL store (see the `repo` fixture)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from maintdesk.models import NewTicket, NotFound, Priority, Status
from maintdesk.repository import TicketRepository

NOW = "2026-10-19T10:00:00+00:00"
LATER = "2026-10-19T11:30:00+00:00"


def add(repo: TicketRepository, title: str, machine: str = "Presse P-12", description: str = "") -> int:
    return repo.add(NewTicket(title, machine, description, Priority.HIGH), NOW).id


def test_add_returns_open_ticket_with_increasing_ids(repo: TicketRepository) -> None:
    first = repo.add(NewTicket("A", "M1"), NOW)
    second = repo.add(NewTicket("B", "M1"), NOW)
    assert (first.status, first.assignee, first.created_at) == (Status.OPEN, None, NOW)
    assert second.id > first.id


def test_get_returns_what_was_stored(repo: TicketRepository) -> None:
    ticket_id = add(repo, "Ölstand zu niedrig", description="Umlaute: äöüß, Quote ' und \"")
    ticket = repo.get(ticket_id)
    assert ticket.title == "Ölstand zu niedrig"
    assert ticket.description == "Umlaute: äöüß, Quote ' und \""
    assert ticket.priority is Priority.HIGH


def test_get_unknown_id_raises_not_found(repo: TicketRepository) -> None:
    with pytest.raises(NotFound):
        repo.get(9999)


def test_list_is_sorted_by_id_and_filters_by_status(repo: TicketRepository) -> None:
    a, b, c = add(repo, "A"), add(repo, "B"), add(repo, "C")
    repo.save(replace(repo.get(b), status=Status.IN_PROGRESS, assignee="Anna", updated_at=LATER))
    assert [t.id for t in repo.list()] == [a, b, c]
    assert [t.id for t in repo.list(status=Status.OPEN)] == [a, c]
    assert [t.id for t in repo.list(status=Status.IN_PROGRESS)] == [b]
    assert repo.list(status=Status.DONE) == []


def test_list_filters_by_machine_exactly(repo: TicketRepository) -> None:
    add(repo, "A", machine="Presse P-12")
    b = add(repo, "B", machine="Ofen O-1")
    assert [t.id for t in repo.list(machine="Ofen O-1")] == [b]
    assert repo.list(machine="Ofen") == []


def test_text_search_is_case_insensitive_in_title_and_description(repo: TicketRepository) -> None:
    a = add(repo, "Lager defekt")
    b = add(repo, "Sensor", description="Das LAGER wackelt")
    add(repo, "Sonstiges")
    assert [t.id for t in repo.list(text="lager")] == [a, b]


def test_text_search_ignores_case_of_umlauts_too(repo: TicketRepository) -> None:
    a = add(repo, "Öl nachfüllen")
    add(repo, "Lager")
    assert [t.id for t in repo.list(text="ÖL")] == [a]
    assert [t.id for t in repo.list(text="öl")] == [a]


def test_text_search_treats_special_characters_literally(repo: TicketRepository) -> None:
    a = add(repo, "100% Auslastung")
    add(repo, "Normaler Titel")
    assert [t.id for t in repo.list(text="100%")] == [a]
    assert repo.list(text="_") == []


def test_filters_can_be_combined(repo: TicketRepository) -> None:
    a = add(repo, "Lager", machine="P-12")
    add(repo, "Lager", machine="O-1")
    repo.save(replace(repo.get(a), status=Status.IN_PROGRESS, assignee="Anna", updated_at=LATER))
    result = repo.list(status=Status.IN_PROGRESS, machine="P-12", text="lag")
    assert [t.id for t in result] == [a]


def test_save_replaces_ticket_and_moves_it_between_status_lists(repo: TicketRepository) -> None:
    ticket_id = add(repo, "A")
    saved = repo.save(replace(repo.get(ticket_id), status=Status.IN_PROGRESS, assignee="Anna", updated_at=LATER))
    assert saved.status is Status.IN_PROGRESS
    stored = repo.get(ticket_id)
    assert (stored.assignee, stored.updated_at) == ("Anna", LATER)
    assert repo.list(status=Status.OPEN) == []


def test_save_unknown_ticket_raises_not_found(repo: TicketRepository) -> None:
    ghost = replace(repo.get(add(repo, "A")), id=4242)
    with pytest.raises(NotFound):
        repo.save(ghost)


def test_delete_removes_ticket_everywhere(repo: TicketRepository) -> None:
    ticket_id = add(repo, "A")
    repo.delete(ticket_id)
    assert repo.count() == 0
    assert repo.list(status=Status.OPEN) == []
    with pytest.raises(NotFound):
        repo.get(ticket_id)
    with pytest.raises(NotFound):
        repo.delete(ticket_id)


def test_count(repo: TicketRepository) -> None:
    assert repo.count() == 0
    add(repo, "A")
    add(repo, "B")
    assert repo.count() == 2


def test_hostile_text_is_stored_as_plain_text(repo: TicketRepository) -> None:
    title = "'; DROP TABLE tickets; --"
    ticket_id = add(repo, title)
    assert repo.get(ticket_id).title == title
    assert repo.count() == 1
