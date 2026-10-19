"""SQL store (SQLite) with versioned schema migrations.

The database file carries its own schema version (`PRAGMA user_version`). Opening an
older file upgrades it step by step, inside one transaction per step, without losing data.
Opening a file that is NEWER than this code is refused instead of guessed at.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import NewTicket, NotFound, RepositoryError, Status, Ticket

# Version 1 was the first release. Version 2 added the assignee and an index on status.
MIGRATIONS: dict[int, str] = {
    1: """
        CREATE TABLE tickets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            machine     TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            priority    TEXT NOT NULL,
            status      TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
    """,
    2: """
        ALTER TABLE tickets ADD COLUMN assignee TEXT;
        CREATE INDEX idx_tickets_status ON tickets(status);
    """,
}
SCHEMA_VERSION = max(MIGRATIONS)

_COLUMNS = "id, title, machine, description, priority, status, created_at, updated_at, assignee"


def _lower(value: str | None) -> str | None:
    return value.lower() if value is not None else None


def _row_to_ticket(row: tuple[object, ...]) -> Ticket:
    return Ticket.from_dict(
        {
            "id": row[0],
            "title": row[1],
            "machine": row[2],
            "description": row[3],
            "priority": row[4],
            "status": row[5],
            "created_at": row[6],
            "updated_at": row[7],
            "assignee": row[8],
        }
    )


class SqliteTicketRepository:
    def __init__(self, path: str | Path) -> None:
        self._lock = threading.Lock()
        try:
            # autocommit mode: transactions are opened explicitly in `_tx`
            self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
            self._conn.execute("PRAGMA journal_mode=WAL")
            # SQLite's own lower() only handles A-Z, so "ÖL" would not find "Öl". Use Python's.
            self._conn.create_function("pylower", 1, _lower, deterministic=True)
            self._migrate()
        except sqlite3.Error as exc:
            raise RepositoryError(f"cannot open database {path}: {exc}") from exc

    # -- schema ---------------------------------------------------------
    def schema_version(self) -> int:
        row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def _migrate(self) -> None:
        current = self.schema_version()
        if current > SCHEMA_VERSION:
            raise RepositoryError(
                f"database has schema version {current}, this program only knows up to {SCHEMA_VERSION}"
            )
        for version in range(current + 1, SCHEMA_VERSION + 1):
            self._conn.execute("BEGIN")
            try:
                for statement in MIGRATIONS[version].split(";"):
                    if statement.strip():
                        self._conn.execute(statement)
                self._conn.execute(f"PRAGMA user_version = {int(version)}")
                self._conn.execute("COMMIT")
            except sqlite3.Error:
                self._conn.execute("ROLLBACK")
                raise

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                try:
                    yield self._conn
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                else:
                    self._conn.execute("COMMIT")
            except sqlite3.Error as exc:
                raise RepositoryError(f"database error: {exc}") from exc

    # -- repository interface --------------------------------------------
    def add(self, new: NewTicket, now: str) -> Ticket:
        with self._tx() as conn:
            cursor = conn.execute(
                "INSERT INTO tickets (title, machine, description, priority, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new.title, new.machine, new.description, new.priority.value, Status.OPEN.value, now, now),
            )
            ticket_id = cursor.lastrowid
        if ticket_id is None:  # pragma: no cover - sqlite always sets it after INSERT
            raise RepositoryError("insert returned no id")
        return self.get(ticket_id)

    def get(self, ticket_id: int) -> Ticket:
        with self._tx() as conn:
            row = conn.execute(f"SELECT {_COLUMNS} FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise NotFound(f"ticket {ticket_id} does not exist")
        return _row_to_ticket(row)

    def list(
        self,
        status: Status | None = None,
        machine: str | None = None,
        text: str | None = None,
    ) -> list[Ticket]:
        sql = f"SELECT {_COLUMNS} FROM tickets"
        clauses: list[str] = []
        params: list[str] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if machine is not None:
            clauses.append("machine = ?")
            params.append(machine)
        if text:
            # instr() instead of LIKE: no wildcard characters to escape
            clauses.append("(instr(pylower(title), ?) > 0 OR instr(pylower(description), ?) > 0)")
            params.extend([text.lower(), text.lower()])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        with self._tx() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_ticket(row) for row in rows]

    def save(self, ticket: Ticket) -> Ticket:
        with self._tx() as conn:
            cursor = conn.execute(
                "UPDATE tickets SET title=?, machine=?, description=?, priority=?, status=?,"
                " updated_at=?, assignee=? WHERE id=?",
                (
                    ticket.title,
                    ticket.machine,
                    ticket.description,
                    ticket.priority.value,
                    ticket.status.value,
                    ticket.updated_at,
                    ticket.assignee,
                    ticket.id,
                ),
            )
            if cursor.rowcount == 0:
                raise NotFound(f"ticket {ticket.id} does not exist")
        return self.get(ticket.id)

    def delete(self, ticket_id: int) -> None:
        with self._tx() as conn:
            cursor = conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
            if cursor.rowcount == 0:
                raise NotFound(f"ticket {ticket_id} does not exist")

    def count(self) -> int:
        with self._tx() as conn:
            row = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()
        return int(row[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

