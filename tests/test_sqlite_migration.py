from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from maintdesk.models import RepositoryError, Status
from maintdesk.sqlite_repo import MIGRATIONS, SCHEMA_VERSION, SqliteTicketRepository


def make_v1_database(path: Path) -> None:
    """A database as the first release wrote it (no assignee column, no index)."""
    conn = sqlite3.connect(path)
    conn.executescript(MIGRATIONS[1])
    conn.execute(
        "INSERT INTO tickets (title, machine, description, priority, status, created_at, updated_at)"
        " VALUES ('Alt', 'F-3', 'aus Version 1', 'high', 'in_progress', '2025-01-01T08:00:00+00:00',"
        " '2025-01-02T08:00:00+00:00')"
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def test_new_database_gets_current_version(tmp_path: Path) -> None:
    repo = SqliteTicketRepository(tmp_path / "new.sqlite3")
    assert repo.schema_version() == SCHEMA_VERSION == 2


def test_old_database_is_upgraded_and_keeps_its_data(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    make_v1_database(path)
    repo = SqliteTicketRepository(path)
    assert repo.schema_version() == SCHEMA_VERSION
    old = repo.get(1)
    assert (old.title, old.description, old.status, old.assignee) == ("Alt", "aus Version 1", Status.IN_PROGRESS, None)
    conn = sqlite3.connect(path)
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(tickets)")}
    assert "idx_tickets_status" in indexes


def test_upgrading_twice_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    make_v1_database(path)
    SqliteTicketRepository(path).close()
    repo = SqliteTicketRepository(path)
    assert repo.count() == 1 and repo.schema_version() == SCHEMA_VERSION


def test_database_from_the_future_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(RepositoryError, match="schema version"):
        SqliteTicketRepository(path)


def test_unusable_path_is_a_repository_error(tmp_path: Path) -> None:
    with pytest.raises(RepositoryError):
        SqliteTicketRepository(tmp_path / "missing-folder" / "x.sqlite3")
