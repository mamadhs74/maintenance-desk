# maintenance-desk

A small ticket desk for machine maintenance, written in Python. One service layer sits on top of **two data stores** (SQL and NoSQL), is exposed as a **JSON API over HTTP**, and has a **desktop client** (Qt). All demo data is invented.

```
 Desktop app (PySide6)  --HTTP/JSON-->  API (FastAPI)  -->  TicketService (rules)  -->  SQLite  or  Redis
```

## What it shows

- **Desktop and web in Python.** `maintdesk.desktop` is a Qt window; `maintdesk.api` is the web API. The window never touches the database. It talks to the API through `ApiClient` (httpx).
- **SQL and NoSQL behind one interface.** `SqliteTicketRepository` and `RedisTicketRepository` follow the same `TicketRepository` protocol. Every contract test runs against both, against a real Redis server (no mock).
- **Changing an existing application safely.** The SQLite file carries a schema version. Version 2 added an `assignee` column and an index; opening a version 1 file upgrades it without losing data (tested). A file from a newer version is refused.
- **Debugging and stability.**
  - Every response carries a request id; slow or failing calls are logged with it.
  - A dead data store gives a clean `503` with a short message, not a crash. An unexpected bug gives `500` with a reference id that is also in the log, and no internals in the answer.
  - The window shows server problems in the status bar and keeps working; long calls run in a background thread so it never freezes.
- **Tests that found real bugs while writing this**: SQLite's `lower()` only handles A-Z, so searching "ÖL" did not find "Öl" (the Redis store did). Qt turned an enum into a plain string in a combo box, so the status filter crashed. Both are fixed and have tests.

## Run it

```bash
pip install -e ".[dev,desktop]"

# 1. API with SQLite (default)
uvicorn maintdesk.api:app_from_env --factory --port 8000

#    ... or with Redis
MAINTDESK_BACKEND=redis MAINTDESK_REDIS_URL=redis://localhost:6379/0 \
  uvicorn maintdesk.api:app_from_env --factory --port 8000

# 2. demo tickets (invented) and the desktop window
python -m maintdesk.seed --url http://127.0.0.1:8000
python -m maintdesk.desktop --url http://127.0.0.1:8000
```

Settings (environment variables): `MAINTDESK_BACKEND` (`sqlite` or `redis`), `MAINTDESK_DB_PATH`, `MAINTDESK_REDIS_URL`, `MAINTDESK_LOG_LEVEL`.

API: `GET /health`, `GET/POST /tickets`, `GET/DELETE /tickets/{id}`, `POST /tickets/{id}/status`. Interactive docs at `/docs`.

Status rules: `open → in_progress → done`, `in_progress → open`, `done → open`. Starting work needs an assignee. Anything else is `409`.

## Tests

```bash
python -m pytest -q      # 126 tests; needs redis-server on the PATH, or MAINTDESK_TEST_REDIS_URL
python -m mypy           # strict
```

The Redis tests start a throw-away `redis-server` process, or use `MAINTDESK_TEST_REDIS_URL` (the CI service). If neither exists they are skipped. The window tests run without a screen (`QT_QPA_PLATFORM=offscreen`) and are skipped if PySide6 is not installed.

## Known limits (on purpose, not hidden)

- **Two people changing the same ticket at the same moment**: the last write wins. A version column (optimistic locking) would fix it; not done yet.
- **No login.** Anyone who can reach the API can change tickets. Fine for a demo, not for production.
- **Redis text search** reads the candidate tickets and filters in Python. Fine for thousands of tickets; for millions, use the SQL store or add a search index.
- **The window was run and checked on a virtual (offscreen) display**, not on Windows or macOS.
- `Dockerfile` and `docker-compose.yml` are included; I could not build them where I wrote this. The CI job builds the image, so a failure would show there.
