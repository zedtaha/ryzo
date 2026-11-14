"""Editor list tool: all open files at a glance."""

from PySide6 import QtWidgets
from PySide6.QtCore import Qt


class EditorListTool(QtWidgets.QWidget):
    title = "Editor list"

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.list = QtWidgets.QListWidget()
        self.list.itemClicked.connect(self._clicked)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self.list)
        tabs = main.editors
        tabs.editorsChanged.connect(self.refresh)
        tabs.currentEditorChanged.connect(lambda _e: self.refresh())
        tabs.tabs.tabBar().tabMoved.connect(lambda *_: self.refresh())
        self.refresh()

    def refresh(self):
        self.list.clear()
        tabs = self.main.editors
        current = tabs.current_editor()
        for ed in tabs.editors():
            name = ed.name + (" *" if ed.document().isModified() else "")
            item = QtWidgets.QListWidgetItem(name)
            item.setToolTip(ed.filename or "not saved")
            item.setData(Qt.UserRole, ed)
            self.list.addItem(item)
            if ed is current:
                item.setSelected(True)
                f = item.font()
                f.setBold(True)
                item.setFont(f)

    def _clicked(self, item):
        ed = item.data(Qt.UserRole)
        self.main.editors.tabs.setCurrentWidget(ed)
        ed.setFocus()

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        ed = item.data(Qt.UserRole)
        menu = QtWidgets.QMenu(self)
        menu.addAction("Save", lambda: self.main.editors.save(ed))
        menu.addAction("Close", lambda: self.main.editors.close_editor(ed))
        menu.exec(self.list.viewport().mapToGlobal(pos))
