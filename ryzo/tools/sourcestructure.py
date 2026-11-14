"""Source structure tool: cells, functions and classes of the current file."""

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ryzo.core.rsyntax import parse_structure

ICONS = {"cell": "■", "function": "ƒ", "class": "C", "method": "m", "import": "→"}


class SourceStructureTool(QtWidgets.QWidget):
    title = "Source structure"

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self._editor = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        row = QtWidgets.QHBoxLayout()
        self.show_imports = QtWidgets.QCheckBox("libraries")
        self.show_imports.setChecked(True)
        self.show_imports.toggled.connect(self.update_structure)
        row.addWidget(QtWidgets.QLabel("Show:"))
        row.addWidget(self.show_imports)
        row.addStretch(1)
        layout.addLayout(row)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemActivated.connect(self._clicked)
        layout.addWidget(self.tree)
        self._timer = QtCore.QTimer(self, singleShot=True, interval=400)
        self._timer.timeout.connect(self.update_structure)
        main.editors.currentEditorChanged.connect(self.set_editor)
        self.set_editor(main.editors.current_editor())

    def set_editor(self, editor):
        if self._editor is not None:
            try:
                self._editor.textChanged.disconnect(self._timer.start)
                self._editor.cursorPositionChanged.disconnect(self._sync_selection)
            except (RuntimeError, TypeError):
                pass
        self._editor = editor
        if editor is not None:
            editor.textChanged.connect(self._timer.start)
            editor.cursorPositionChanged.connect(self._sync_selection)
        self.update_structure()

    def update_structure(self):
        self.tree.clear()
        ed = self._editor
        if ed is None:
            return
        try:
            items = parse_structure(ed.toPlainText())
        except Exception:  # never break the UI on odd input
            return
        bold = QtGui.QFont(self.font())
        bold.setBold(True)

        def add(parent, item):
            if item.kind == "import" and not self.show_imports.isChecked():
                return
            w = QtWidgets.QTreeWidgetItem(parent, [f"{ICONS.get(item.kind, '')}  {item.name}"])
            w.setData(0, Qt.UserRole, item.line)
            w.setToolTip(0, f"{item.kind} - line {item.line + 1}")
            if item.kind == "cell":
                w.setFont(0, bold)
            for child in item.children:
                add(w, child)

        for item in items:
            add(self.tree, item)
        self.tree.expandAll()
        self._sync_selection()

    def _sync_selection(self):
        ed = self._editor
        if ed is None:
            return
        line = ed.textCursor().blockNumber()
        best = None
        it = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            if item.data(0, Qt.UserRole) <= line:
                best = item
            it += 1
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(best) if best else self.tree.clearSelection()
        self.tree.blockSignals(False)

    def _clicked(self, item, _col=0):
        if self._editor is not None:
            self._editor.go_to_line(item.data(0, Qt.UserRole))
