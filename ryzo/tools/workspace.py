"""Workspace tool: browse the objects in the R global environment."""

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt


class WorkspaceTool(QtWidgets.QWidget):
    title = "Workspace"

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.path = ""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        row = QtWidgets.QHBoxLayout()
        style = self.style()
        self.up = QtWidgets.QToolButton()
        self.up.setIcon(style.standardIcon(QtWidgets.QStyle.SP_ArrowUp))
        self.up.setToolTip("Go up one level")
        self.up.clicked.connect(self.go_up)
        refresh = QtWidgets.QToolButton()
        refresh.setIcon(style.standardIcon(QtWidgets.QStyle.SP_BrowserReload))
        refresh.setToolTip("Refresh")
        refresh.clicked.connect(self.refresh)
        self.path_label = QtWidgets.QLabel("globalenv()")
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("filter")
        self.filter.setMaximumWidth(120)
        self.filter.textChanged.connect(self._apply_filter)
        row.addWidget(self.up)
        row.addWidget(refresh)
        row.addWidget(self.path_label, 1)
        row.addWidget(self.filter)
        layout.addLayout(row)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Name", "Class", "Size", "Value"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        header.resizeSection(0, 110)
        header.resizeSection(1, 90)
        header.resizeSection(2, 60)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tree)
        self.hint = QtWidgets.QLabel("Double-click a list, data frame or environment to look inside.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: gray;")
        layout.addWidget(self.hint)
        self._update_up()

    def refresh(self):
        shell = self.main.current_shell()
        if shell is not None and self.isVisible():
            shell.kernel.workspace(self.path)

    def on_message(self, shell, msg):
        if shell is not self.main.current_shell():
            return
        t = msg.get("type")
        if t == "workspace":
            self._populate(msg)
        elif t == "ready" and self.isVisible():
            QtCore.QTimer.singleShot(50, self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def _populate(self, msg):
        if msg.get("path", "") != self.path:
            return
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for e in msg.get("entries") or []:
            item = QtWidgets.QTreeWidgetItem(
                [e.get("name", ""), e.get("class", ""), e.get("size", ""), e.get("value", "")])
            item.setData(0, Qt.UserRole, e)
            item.setToolTip(3, e.get("value", ""))
            if e.get("expandable"):
                f = item.font(0)
                f.setUnderline(True)
                item.setFont(0, f)
            self.tree.addTopLevelItem(item)
        self.tree.setSortingEnabled(True)
        self._apply_filter()

    def _apply_filter(self):
        text = self.filter.text().lower()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            item.setHidden(bool(text) and text not in item.text(0).lower())

    def _update_up(self):
        self.up.setEnabled(bool(self.path))
        self.path_label.setText(self.path or "globalenv()")

    def set_path(self, path):
        self.path = path
        self._update_up()
        self.refresh()

    def go_up(self):
        p = self.path
        # strip the last accessor: x$a, x[["a"]], x[[1]]
        for sep in ("[[", "$"):
            i = p.rfind(sep)
            if i > 0:
                self.set_path(p[:i])
                return
        self.set_path("")

    def _double_clicked(self, item, _col):
        e = item.data(0, Qt.UserRole)
        if e.get("expandable"):
            self.set_path(e["expr"])
        else:
            self.main.execute_code(f"str({e['expr']})", "block")

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        e = item.data(0, Qt.UserRole)
        expr = e["expr"]
        menu = QtWidgets.QMenu(self)
        if e.get("expandable"):
            menu.addAction("Look inside", lambda: self.set_path(expr))
        menu.addAction("Print", lambda: self.main.execute_code(f"print({expr})", "block"))
        menu.addAction("str()", lambda: self.main.execute_code(f"str({expr})", "block"))
        menu.addAction("summary()", lambda: self.main.execute_code(f"summary({expr})", "block"))
        if e.get("class", "").split("/")[0] in ("data.frame", "tbl_df", "matrix", "data.table") or \
                "data.frame" in e.get("class", ""):
            menu.addAction("View as table", lambda: self.main.execute_code(f"View({expr})", "block"))
        menu.addAction("Help on class", lambda: self.main.show_help(e.get("class", "").split("/")[0]))
        if not self.path:
            menu.addSeparator()
            menu.addAction(f"Delete ({e['name']})",
                           lambda: self.main.execute_code(f"rm({expr})", "block"))
        menu.addAction("Copy name", lambda: QtWidgets.QApplication.clipboard().setText(expr))
        menu.exec(self.tree.viewport().mapToGlobal(pos))
