"""Window tests. They run without a screen (Qt "offscreen") and are skipped if PySide6 is not installed."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastapi.testclient import TestClient  # noqa: E402
from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from maintdesk.api import create_app  # noqa: E402
from maintdesk.client import ApiClient, ApiUnavailable  # noqa: E402
from maintdesk.desktop.window import MainWindow  # noqa: E402
from maintdesk.models import Priority, Status  # noqa: E402
from maintdesk.repository import TicketRepository  # noqa: E402
from maintdesk.service import TicketService  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


def settle(app: QApplication) -> None:
    """Wait for background tasks, then let their 'finished' signals reach the window."""
    QThreadPool.globalInstance().waitForDone(5000)
    for _ in range(5):
        app.processEvents()


@pytest.fixture
def window(qapp: QApplication, repo: TicketRepository) -> Iterator[MainWindow]:
    http = TestClient(create_app(TicketService(repo)), base_url="http://testserver")
    win = MainWindow(ApiClient("http://testserver", http=http))
    yield win
    settle(qapp)
    win.close()
    http.close()


def titles(win: MainWindow) -> list[str]:
    return [win.table.item(r, 1).text() for r in range(win.table.rowCount())]  # type: ignore[union-attr]


def test_full_workflow_through_the_window(qapp: QApplication, window: MainWindow) -> None:
    window.refresh()
    settle(qapp)
    assert window.table.rowCount() == 0
    assert window.statusBar().currentMessage() == "0 Aufträge: 0 offen, 0 in Arbeit, 0 erledigt"

    window.create_ticket("Lager defekt", "F-3", "laut", Priority.HIGH)
    settle(qapp)
    assert titles(window) == ["Lager defekt"]
    assert window.table.item(0, 4).text() == "Offen"  # type: ignore[union-attr]

    window.table.selectRow(0)
    window.change_status(Status.IN_PROGRESS, "Anna")
    settle(qapp)
    assert window.table.item(0, 4).text() == "In Arbeit" and window.table.item(0, 5).text() == "Anna"  # type: ignore[union-attr]
    assert window.table.currentRow() == 0, "the selection should survive a reload"

    window.change_status(Status.DONE)
    settle(qapp)
    assert window.statusBar().currentMessage().endswith("1 erledigt")

    window.delete_selected()
    settle(qapp)
    assert window.table.rowCount() == 0


def test_filter_and_search(qapp: QApplication, window: MainWindow) -> None:
    window.create_ticket("Lager defekt", "F-3", "", Priority.NORMAL)
    settle(qapp)
    window.create_ticket("Ölstand", "P-12", "", Priority.NORMAL)
    settle(qapp)
    window.table.selectRow(0)
    window.change_status(Status.IN_PROGRESS, "Anna")
    settle(qapp)

    window.filter_box.setCurrentIndex(window.filter_box.findText("In Arbeit"))
    settle(qapp)
    assert titles(window) == ["Lager defekt"]

    window.filter_box.setCurrentIndex(0)
    window.search_edit.setText("öl")
    window.apply_filter()
    settle(qapp)
    assert titles(window) == ["Ölstand"]


def test_no_selection_gives_a_hint_instead_of_an_error(qapp: QApplication, window: MainWindow) -> None:
    window.change_status(Status.DONE)
    assert "auswählen" in window.statusBar().currentMessage()


def test_server_error_is_shown_in_the_status_bar(qapp: QApplication, window: MainWindow) -> None:
    window.create_ticket("", "F-3", "", Priority.NORMAL)  # the server refuses an empty title
    settle(qapp)
    assert window.statusBar().currentMessage().startswith("Fehler:")


def test_unreachable_server_is_shown_and_buttons_work_again(qapp: QApplication, window: MainWindow) -> None:
    def down(*args: object, **kwargs: object) -> list[object]:
        raise ApiUnavailable("The server cannot be reached (ConnectError).")

    window.vm._client.list_tickets = down  # type: ignore[method-assign,attr-defined]
    window.refresh()
    settle(qapp)
    assert window.statusBar().currentMessage().startswith("Server nicht erreichbar")
    assert all(button.isEnabled() for button in window._action_buttons)


def test_unexpected_crash_in_a_task_does_not_freeze_the_window(qapp: QApplication, window: MainWindow) -> None:
    def explode() -> None:
        raise RuntimeError("bug")

    window._start(explode)
    settle(qapp)
    assert window.statusBar().currentMessage() == "Unerwarteter Fehler: RuntimeError"
    assert window.refresh_button.isEnabled()
