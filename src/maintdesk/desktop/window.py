"""Qt window (PySide6). It only displays the view model and starts its actions in a worker thread,
so the window stays responsive while the server answers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..client import TicketClient
from ..models import Priority, Status
from .viewmodel import PRIORITY_LABELS, STATUS_LABELS, TicketListViewModel

log = logging.getLogger("maintdesk.desktop")

COLUMNS = ["Nr.", "Titel", "Maschine", "Priorität", "Status", "Bearbeiter", "Geändert"]


class _Done(QObject):
    finished = Signal()


class _Task(QRunnable):
    """Runs one view-model action outside the window thread and tells the window when it is done."""

    def __init__(self, action: Callable[[], object]) -> None:
        super().__init__()
        self._action = action
        self.signals = _Done()
        self.crashed: str | None = None

    def run(self) -> None:
        try:
            self._action()
        except Exception as exc:  # the view model handles API errors; this is the safety net
            log.exception("unexpected error in background task")
            self.crashed = f"Unerwarteter Fehler: {type(exc).__name__}"
        finally:
            self.signals.finished.emit()


class NewTicketDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neuer Auftrag")
        self.title_edit = QLineEdit()
        self.machine_edit = QLineEdit()
        self.description_edit = QPlainTextEdit()
        self.priority_box = QComboBox()
        for priority in Priority:
            self.priority_box.addItem(PRIORITY_LABELS[priority], priority.value)
        self.priority_box.setCurrentIndex(list(Priority).index(Priority.NORMAL))
        form = QFormLayout(self)
        form.addRow("Titel", self.title_edit)
        form.addRow("Maschine", self.machine_edit)
        form.addRow("Beschreibung", self.description_edit)
        form.addRow("Priorität", self.priority_box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[str, str, str, Priority]:
        return (
            self.title_edit.text(),
            self.machine_edit.text(),
            self.description_edit.toPlainText(),
            Priority(self.priority_box.currentData()),
        )


class MainWindow(QMainWindow):
    def __init__(self, client: TicketClient) -> None:
        super().__init__()
        self.setWindowTitle("Wartungsaufträge")
        self.resize(980, 520)
        self.vm = TicketListViewModel(client)
        self._busy = False
        self._tasks: list[_Task] = []

        self.filter_box = QComboBox()
        self.filter_box.addItem("Alle", None)
        for status in Status:
            self.filter_box.addItem(STATUS_LABELS[status], status.value)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Suchen in Titel und Beschreibung")
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        for column, width in enumerate([50, 300, 150, 80, 90, 120]):
            self.table.setColumnWidth(column, width)

        self.refresh_button = QPushButton("Aktualisieren")
        self.new_button = QPushButton("Neuer Auftrag…")
        self.start_button = QPushButton("In Arbeit setzen…")
        self.done_button = QPushButton("Erledigt")
        self.reopen_button = QPushButton("Wieder öffnen")
        self.delete_button = QPushButton("Löschen")
        self._action_buttons = [
            self.refresh_button, self.new_button, self.start_button,
            self.done_button, self.reopen_button, self.delete_button,
        ]

        top = QHBoxLayout()
        top.addWidget(self.filter_box)
        top.addWidget(self.search_edit, 1)
        top.addWidget(self.refresh_button)
        bottom = QHBoxLayout()
        for button in self._action_buttons[1:]:
            bottom.addWidget(button)
        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.filter_box.currentIndexChanged.connect(lambda _: self.apply_filter())
        self.search_edit.returnPressed.connect(self.apply_filter)
        self.refresh_button.clicked.connect(self.refresh)
        self.new_button.clicked.connect(self._ask_new_ticket)
        self.start_button.clicked.connect(self._ask_start)
        self.done_button.clicked.connect(lambda: self.change_status(Status.DONE))
        self.reopen_button.clicked.connect(lambda: self.change_status(Status.OPEN))
        self.delete_button.clicked.connect(self._confirm_delete)

    # -- public actions (also what the tests call) ---------------------------
    def refresh(self) -> None:
        self._start(self.vm.refresh)

    def apply_filter(self) -> None:
        # Qt turns enum data into plain strings, so store the value and convert back
        chosen = self.filter_box.currentData()
        self.vm.status_filter = Status(chosen) if chosen else None
        self.vm.search_text = self.search_edit.text().strip()
        self.refresh()

    def create_ticket(self, title: str, machine: str, description: str, priority: Priority) -> None:
        self._start(lambda: self.vm.create(title, machine, description, priority))

    def change_status(self, status: Status, assignee: str | None = None) -> None:
        ticket_id = self.selected_id()
        if ticket_id is None:
            self.statusBar().showMessage("Bitte zuerst einen Auftrag auswählen.")
            return
        self._start(lambda: self.vm.set_status(ticket_id, status, assignee))

    def delete_selected(self) -> None:
        ticket_id = self.selected_id()
        if ticket_id is None:
            self.statusBar().showMessage("Bitte zuerst einen Auftrag auswählen.")
            return
        self._start(lambda: self.vm.delete(ticket_id))

    def selected_id(self) -> int | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return int(item.text()) if item is not None else None

    # -- dialogs --------------------------------------------------------------
    def _ask_new_ticket(self) -> None:
        dialog = NewTicketDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.create_ticket(*dialog.values())

    def _ask_start(self) -> None:
        name, ok = QInputDialog.getText(self, "In Arbeit setzen", "Wer bearbeitet den Auftrag?")
        if ok:
            self.change_status(Status.IN_PROGRESS, name)

    def _confirm_delete(self) -> None:
        if self.selected_id() is None:
            self.delete_selected()
            return
        answer = QMessageBox.question(self, "Löschen", "Diesen Auftrag wirklich löschen?")
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_selected()

    # -- background work --------------------------------------------------------
    def _start(self, action: Callable[[], object]) -> None:
        if self._busy:
            return
        self._set_busy(True)
        task = _Task(action)
        task.signals.finished.connect(lambda: self._finished(task))
        self._tasks.append(task)
        QThreadPool.globalInstance().start(task)

    def _finished(self, task: _Task) -> None:
        self._tasks.remove(task)
        if task.crashed:
            self.vm.error = task.crashed
        self._show()
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button in self._action_buttons:
            button.setEnabled(not busy)

    def _show(self) -> None:
        selected = self.selected_id()
        rows = self.vm.rows
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [str(row.id), row.title, row.machine, row.priority, row.status, row.assignee, row.updated]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if c == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)
            if row.id == selected:
                self.table.selectRow(r)
        self.statusBar().showMessage(self.vm.error or self.vm.summary())
