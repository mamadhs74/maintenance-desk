from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import redis

from maintdesk.models import Ticket
from maintdesk.redis_repo import RedisTicketRepository
from maintdesk.repository import TicketRepository
from maintdesk.sqlite_repo import SqliteTicketRepository


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    """A real Redis server: from MAINTDESK_TEST_REDIS_URL (CI service) or a throw-away local process."""
    external = os.environ.get("MAINTDESK_TEST_REDIS_URL")
    if external:
        yield external
        return
    binary = shutil.which("redis-server")
    if binary is None:
        pytest.skip("no redis-server available (set MAINTDESK_TEST_REDIS_URL or install redis)")
    port = _free_port()
    process = subprocess.Popen(
        [binary, "--port", str(port), "--save", "", "--appendonly", "no", "--bind", "127.0.0.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"redis://127.0.0.1:{port}/0"
    client = redis.Redis.from_url(url)
    for _ in range(50):
        try:
            client.ping()
            break
        except redis.ConnectionError:
            time.sleep(0.1)
    else:
        process.kill()
        pytest.skip("redis-server did not start")
    try:
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.fixture(params=["sqlite", "redis"])
def repo(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[TicketRepository]:
    """Every test that uses `repo` runs once against SQL and once against NoSQL."""
    if request.param == "sqlite":
        store: TicketRepository = SqliteTicketRepository(tmp_path / "t.sqlite3")
    else:
        url = request.getfixturevalue("redis_url")
        store = RedisTicketRepository.from_url(url, prefix=f"test{time.monotonic_ns()}")
    try:
        yield store
    finally:
        store.close()


def make_ticket(**overrides: object) -> Ticket:
    base: dict[str, object] = {
        "id": 1,
        "title": "Ölstand zu niedrig",
        "machine": "Presse P-12",
        "description": "",
        "priority": "normal",
        "status": "open",
        "created_at": "2026-10-19T10:00:00+00:00",
        "updated_at": "2026-10-19T10:00:00+00:00",
        "assignee": None,
    }
    base.update(overrides)
    return Ticket.from_dict(base)
