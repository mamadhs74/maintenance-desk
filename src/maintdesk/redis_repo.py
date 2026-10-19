"""NoSQL store (Redis).

Layout, with prefix `maintdesk`:
  maintdesk:seq              counter, INCR gives the next id
  maintdesk:ticket:<id>      hash with the ticket fields
  maintdesk:ids              set of all ids
  maintdesk:status:<status>  set of ids per status (so "show all open tickets" needs no full scan)

Writes that touch several keys run in one MULTI/EXEC block, so the sets never disagree with the hashes.
Text search and the machine filter read the candidate tickets and filter in Python. That is fine for
thousands of tickets; for millions you would add a search index (RediSearch) or use the SQL store.
"""

from __future__ import annotations

from typing import Any, cast

import redis

from .models import NewTicket, NotFound, RepositoryError, Status, Ticket


class RedisTicketRepository:
    def __init__(self, client: redis.Redis, prefix: str = "maintdesk") -> None:
        self._r = client
        self._p = prefix

    @classmethod
    def from_url(cls, url: str, prefix: str = "maintdesk") -> RedisTicketRepository:
        client: redis.Redis = redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3
        )
        return cls(client, prefix)

    # -- key names --------------------------------------------------------
    def _seq(self) -> str:
        return f"{self._p}:seq"

    def _key(self, ticket_id: int) -> str:
        return f"{self._p}:ticket:{ticket_id}"

    def _ids(self) -> str:
        return f"{self._p}:ids"

    def _status_key(self, status: Status) -> str:
        return f"{self._p}:status:{status.value}"

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _to_mapping(ticket: Ticket) -> dict[Any, Any]:
        # typed loosely because the redis stubs expect a very wide key/value union
        data = ticket.to_dict()
        # Redis hashes only hold strings; None becomes an empty string
        return {key: "" if value is None else str(value) for key, value in data.items()}

    def _load(self, ticket_ids: list[int]) -> list[Ticket]:
        pipe = self._r.pipeline(transaction=False)
        for ticket_id in ticket_ids:
            pipe.hgetall(self._key(ticket_id))
        raw = cast("list[dict[str, str]]", pipe.execute())
        return [Ticket.from_dict(item) for item in raw if item]

    # -- repository interface ----------------------------------------------
    def add(self, new: NewTicket, now: str) -> Ticket:
        try:
            ticket_id = int(cast(Any, self._r.incr(self._seq())))
            ticket = Ticket(
                id=ticket_id,
                title=new.title,
                machine=new.machine,
                description=new.description,
                priority=new.priority,
                status=Status.OPEN,
                created_at=now,
                updated_at=now,
            )
            pipe = self._r.pipeline(transaction=True)
            pipe.hset(self._key(ticket_id), mapping=self._to_mapping(ticket))
            pipe.sadd(self._ids(), str(ticket_id))
            pipe.sadd(self._status_key(Status.OPEN), str(ticket_id))
            pipe.execute()
            return ticket
        except redis.RedisError as exc:
            raise RepositoryError(f"redis error: {exc}") from exc

    def get(self, ticket_id: int) -> Ticket:
        try:
            raw = cast("dict[str, str]", self._r.hgetall(self._key(ticket_id)))
        except redis.RedisError as exc:
            raise RepositoryError(f"redis error: {exc}") from exc
        if not raw:
            raise NotFound(f"ticket {ticket_id} does not exist")
        return Ticket.from_dict(raw)

    def list(
        self,
        status: Status | None = None,
        machine: str | None = None,
        text: str | None = None,
    ) -> list[Ticket]:
        try:
            source = self._status_key(status) if status is not None else self._ids()
            members = cast("set[str]", self._r.smembers(source))
            tickets = self._load(sorted(int(member) for member in members))
        except redis.RedisError as exc:
            raise RepositoryError(f"redis error: {exc}") from exc
        if machine is not None:
            tickets = [t for t in tickets if t.machine == machine]
        if text:
            needle = text.lower()
            tickets = [t for t in tickets if needle in t.title.lower() or needle in t.description.lower()]
        return sorted(tickets, key=lambda t: t.id)

    def save(self, ticket: Ticket) -> Ticket:
        key = self._key(ticket.id)
        try:
            old_status = cast("str | None", self._r.hget(key, "status"))
            if old_status is None:
                raise NotFound(f"ticket {ticket.id} does not exist")
            pipe = self._r.pipeline(transaction=True)
            pipe.hset(key, mapping=self._to_mapping(ticket))
            if old_status != ticket.status.value:
                pipe.srem(f"{self._p}:status:{old_status}", str(ticket.id))
                pipe.sadd(self._status_key(ticket.status), str(ticket.id))
            pipe.execute()
        except redis.RedisError as exc:
            raise RepositoryError(f"redis error: {exc}") from exc
        return ticket

    def delete(self, ticket_id: int) -> None:
        key = self._key(ticket_id)
        try:
            old_status = cast("str | None", self._r.hget(key, "status"))
            if old_status is None:
                raise NotFound(f"ticket {ticket_id} does not exist")
            pipe = self._r.pipeline(transaction=True)
            pipe.delete(key)
            pipe.srem(self._ids(), str(ticket_id))
            pipe.srem(f"{self._p}:status:{old_status}", str(ticket_id))
            pipe.execute()
        except redis.RedisError as exc:
            raise RepositoryError(f"redis error: {exc}") from exc

    def count(self) -> int:
        try:
            return int(cast(Any, self._r.scard(self._ids())))
        except redis.RedisError as exc:
            raise RepositoryError(f"redis error: {exc}") from exc

    def close(self) -> None:
        self._r.close()
