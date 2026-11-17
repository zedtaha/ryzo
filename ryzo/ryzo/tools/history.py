"""History tool: commands typed in the shells."""

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from ryzo.config import get_config


class HistoryTool(QtWidgets.QWidget):
    title = "History"

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("search history")
        self.filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter)
        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda item: self.main.execute_code(item.text(), "block"))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self.list)
        for cmd in get_config().history[-1000:]:
            self.list.addItem(cmd)
        self.list.scrollToBottom()

    def add(self, command):
        if not command.strip():
            return
        if self.list.count() and self.list.item(self.list.count() - 1).text() == command:
            return
        self.list.addItem(command)
        while self.list.count() > 1000:
            self.list.takeItem(0)
        self._apply_filter()
        self.list.scrollToBottom()

    def _apply_filter(self):
        text = self.filter.text().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _selected(self):
        return "\n".join(i.text() for i in self.list.selectedItems())

    def _menu(self, pos):
        if not self.list.selectedItems():
            return
        menu = QtWidgets.QMenu(self)
        menu.addAction("Run", lambda: self.main.execute_code(self._selected(), "block"))
        menu.addAction("Copy", lambda: QtWidgets.QApplication.clipboard().setText(self._selected()))
        menu.addAction("Insert in editor", self._insert)
        menu.addSeparator()
        menu.addAction("Remove", self._remove)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _insert(self):
        ed = self.main.editors.current_editor() or self.main.editors.new_file()
        ed.textCursor().insertText(self._selected() + "\n")
        ed.setFocus()

    def _remove(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        get_config().history = [self.list.item(i).text() for i in range(self.list.count())]
