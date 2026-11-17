"""Tabbed editors with a find/replace bar, file handling and session restore."""

import os

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ryzo.config import get_config
from ryzo.core.editor import CodeEditor

R_FILTER = ("R files (*.R *.r *.Rmd *.rmd *.qmd *.Rprofile);;"
            "Text files (*.txt *.md *.csv *.tsv *.json *.yml *.yaml);;All files (*)")


class FindReplaceBar(QtWidgets.QFrame):
    def __init__(self, tabs):
        super().__init__(tabs)
        self.tabs = tabs
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(4, 3, 4, 3)
        grid.setSpacing(4)
        self.find_edit = QtWidgets.QLineEdit()
        self.find_edit.setPlaceholderText("Find")
        self.replace_edit = QtWidgets.QLineEdit()
        self.replace_edit.setPlaceholderText("Replace with")
        self.case = QtWidgets.QCheckBox("Match case")
        self.regex = QtWidgets.QCheckBox("Regexp")
        self.whole = QtWidgets.QCheckBox("Whole words")
        self.status = QtWidgets.QLabel("")
        prev_b = QtWidgets.QPushButton("Previous")
        next_b = QtWidgets.QPushButton("Next")
        repl_b = QtWidgets.QPushButton("Replace")
        all_b = QtWidgets.QPushButton("Replace all")
        close_b = QtWidgets.QToolButton()
        close_b.setText("✕")
        close_b.setAutoRaise(True)
        grid.addWidget(self.find_edit, 0, 0)
        grid.addWidget(prev_b, 0, 1)
        grid.addWidget(next_b, 0, 2)
        grid.addWidget(self.case, 0, 3)
        grid.addWidget(self.whole, 0, 4)
        grid.addWidget(self.status, 0, 5)
        grid.addWidget(close_b, 0, 6)
        grid.addWidget(self.replace_edit, 1, 0)
        grid.addWidget(repl_b, 1, 1)
        grid.addWidget(all_b, 1, 2)
        grid.addWidget(self.regex, 1, 3)
        grid.setColumnStretch(0, 1)
        prev_b.clicked.connect(lambda: self.find(backward=True))
        next_b.clicked.connect(lambda: self.find())
        repl_b.clicked.connect(self.replace)
        all_b.clicked.connect(self.replace_all)
        close_b.clicked.connect(self.hide_bar)
        self.find_edit.returnPressed.connect(self.find)
        self.find_edit.textChanged.connect(self._incremental)
        self.replace_edit.returnPressed.connect(self.replace)
        for cb in (self.case, self.regex, self.whole):
            cb.toggled.connect(self.highlight_all)
        self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide_bar()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ShiftModifier:
            self.find(backward=True)
            return
        super().keyPressEvent(event)

    def show_bar(self, replace=False):
        ed = self.tabs.current_editor()
        if ed is not None:
            sel = ed.textCursor().selectedText()
            if sel and " " not in sel:
                self.find_edit.setText(sel)
        self.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        if replace:
            self.replace_edit.setFocus()
        self.highlight_all()

    def hide_bar(self):
        self.hide()
        ed = self.tabs.current_editor()
        if ed is not None:
            ed.set_extra("find", [])
            ed.setFocus()

    def _pattern(self):
        text = self.find_edit.text()
        if not text:
            return None
        if not self.regex.isChecked():
            text = QtCore.QRegularExpression.escape(text)
        if self.whole.isChecked():
            text = r"\b" + text + r"\b"
        opts = QtCore.QRegularExpression.NoPatternOption
        if not self.case.isChecked():
            opts |= QtCore.QRegularExpression.CaseInsensitiveOption
        rx = QtCore.QRegularExpression(text, opts)
        return rx if rx.isValid() else None

    def _incremental(self):
        ed = self.tabs.current_editor()
        if ed is None:
            return
        c = ed.textCursor()
        c.setPosition(c.selectionStart())
        ed.setTextCursor(c)
        self.find()

    def find(self, backward=False, wrap=True):
        ed = self.tabs.current_editor()
        rx = self._pattern()
        if ed is None or rx is None:
            self.status.setText("")
            return False
        flags = QtGui.QTextDocument.FindFlag(0)
        if backward:
            flags |= QtGui.QTextDocument.FindBackward
        c = ed.document().find(rx, ed.textCursor(), flags)
        if c.isNull() and wrap:
            start = QtGui.QTextCursor(ed.document())
            if backward:
                start.movePosition(QtGui.QTextCursor.End)
            c = ed.document().find(rx, start, flags)
            if not c.isNull():
                self.status.setText("wrapped")
        else:
            self.status.setText("")
        if c.isNull():
            self.status.setText("not found")
            self.highlight_all()
            return False
        ed.setTextCursor(c)
        ed.ensureCursorVisible()
        self.highlight_all()
        return True

    def highlight_all(self):
        ed = self.tabs.current_editor()
        if ed is None:
            return
        rx = self._pattern()
        sels = []
        if rx is not None and self.isVisible():
            doc = ed.document()
            c = QtGui.QTextCursor(doc)
            color = QtGui.QColor(ed.theme["find_match"])
            while len(sels) < 2000:
                c = doc.find(rx, c)
                if c.isNull() or not c.hasSelection():
                    break
                s = QtWidgets.QTextEdit.ExtraSelection()
                s.format.setBackground(color)
                s.cursor = QtGui.QTextCursor(c)
                sels.append(s)
            if sels:
                self.status.setText(f"{len(sels)} matches")
        ed.set_extra("find", sels)

    def replace(self):
        ed = self.tabs.current_editor()
        rx = self._pattern()
        if ed is None or rx is None:
            return
        c = ed.textCursor()
        if c.hasSelection() and rx.match(c.selectedText()).hasMatch():
            c.insertText(self._replacement(c.selectedText(), rx))
        self.find()

    def _replacement(self, matched, rx):
        repl = self.replace_edit.text()
        if self.regex.isChecked():
            import re
            flags = 0 if self.case.isChecked() else re.IGNORECASE
            try:
                return re.sub(rx.pattern(), repl, matched, count=1, flags=flags)
            except re.error:
                return repl
        return repl

    def replace_all(self):
        ed = self.tabs.current_editor()
        rx = self._pattern()
        if ed is None or rx is None:
            return
        doc = ed.document()
        c = QtGui.QTextCursor(doc)
        edit = QtGui.QTextCursor(doc)
        edit.beginEditBlock()
        n = 0
        while True:
            c = doc.find(rx, c)
            if c.isNull() or not c.hasSelection():
                break
            c.insertText(self._replacement(c.selectedText(), rx))
            n += 1
        edit.endEditBlock()
        self.status.setText(f"replaced {n}")
        self.highlight_all()


class EditorTabs(QtWidgets.QWidget):
    currentEditorChanged = QtCore.Signal(object)
    editorsChanged = QtCore.Signal()
    fileSaved = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = get_config()
        self._new_counter = 0
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setElideMode(Qt.ElideRight)
        self.tabs.tabCloseRequested.connect(lambda i: self.close_editor(self.tabs.widget(i)))
        self.tabs.currentChanged.connect(self._on_current)
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_menu)
        layout.addWidget(self.tabs)
        self.find_bar = FindReplaceBar(self)
        layout.addWidget(self.find_bar)

        self.watcher = QtCore.QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._file_changed)
        self._ignore_change = set()

    # ------------------------------------------------------------- editors --
    def editors(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def current_editor(self):
        return self.tabs.currentWidget()

    def _make_editor(self, filename=None):
        ed = CodeEditor(self, filename)
        ed.modifiedChanged.connect(lambda _m, e=ed: self._update_title(e))
        window = self.window()
        if hasattr(window, "connect_editor"):
            window.connect_editor(ed)
        return ed

    def new_file(self):
        ed = self._make_editor()
        self._new_counter += 1
        ed._tmpname = f"<tmp {self._new_counter}>"
        i = self.tabs.addTab(ed, ed.name)
        self.tabs.setCurrentIndex(i)
        self._update_title(ed)
        ed.setFocus()
        self.editorsChanged.emit()
        return ed

    def find_editor(self, filename):
        filename = os.path.normcase(os.path.abspath(filename))
        for ed in self.editors():
            if ed.filename and os.path.normcase(ed.filename) == filename:
                return ed
        return None

    def open_file(self, filename=None, line=None):
        if filename is None:
            start = self.cfg.lastDir or os.path.expanduser("~")
            ed = self.current_editor()
            if ed is not None and ed.filename:
                start = os.path.dirname(ed.filename)
            names, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Open file", start, R_FILTER)
            result = None
            for n in names:
                result = self.open_file(n)
            return result
        filename = os.path.abspath(filename)
        ed = self.find_editor(filename)
        if ed is None:
            if not os.path.isfile(filename):
                QtWidgets.QMessageBox.warning(self, "Open file", f"File not found:\n{filename}")
                return None
            ed = self._make_editor(filename)
            try:
                ed.load(filename)
            except OSError as err:
                QtWidgets.QMessageBox.warning(self, "Open file", f"Could not open file:\n{err}")
                ed.deleteLater()
                return None
            # replace a pristine, empty tmp file
            cur = self.current_editor()
            if (cur is not None and cur.filename is None and not cur.document().isModified()
                    and not cur.toPlainText()):
                self.tabs.removeTab(self.tabs.indexOf(cur))
                cur.deleteLater()
            i = self.tabs.addTab(ed, ed.name)
            self.tabs.setTabToolTip(i, filename)
            self.watcher.addPath(filename)
            self._add_recent(filename)
            self.cfg.lastDir = os.path.dirname(filename)
            self.editorsChanged.emit()
        self.tabs.setCurrentWidget(ed)
        if line is not None:
            ed.go_to_line(line)
        ed.setFocus()
        self._update_title(ed)
        return ed

    def _add_recent(self, filename):
        recent = [f for f in self.cfg.recentFiles if f != filename]
        recent.insert(0, filename)
        self.cfg.recentFiles = recent[:15]

    def save(self, ed=None):
        ed = ed or self.current_editor()
        if ed is None:
            return False
        if not ed.filename:
            return self.save_as(ed)
        try:
            self._ignore_change.add(ed.filename)
            ed.save()
        except OSError as err:
            QtWidgets.QMessageBox.warning(self, "Save", f"Could not save file:\n{err}")
            return False
        self._update_title(ed)
        self.fileSaved.emit(ed.filename)
        return True

    def save_as(self, ed=None):
        ed = ed or self.current_editor()
        if ed is None:
            return False
        start = ed.filename or os.path.join(self.cfg.lastDir or os.path.expanduser("~"), "untitled.R")
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save file as", start, R_FILTER)
        if not filename:
            return False
        old = ed.filename
        try:
            ed.save(filename)
        except OSError as err:
            QtWidgets.QMessageBox.warning(self, "Save", f"Could not save file:\n{err}")
            return False
        if old:
            self.watcher.removePath(old)
        self._ignore_change.add(ed.filename)
        self.watcher.addPath(ed.filename)
        self._add_recent(ed.filename)
        self.cfg.lastDir = os.path.dirname(ed.filename)
        self.tabs.setTabToolTip(self.tabs.indexOf(ed), ed.filename)
        self._update_title(ed)
        self.editorsChanged.emit()
        self.fileSaved.emit(ed.filename)
        return True

    def save_all(self):
        for ed in self.editors():
            if ed.document().isModified() and ed.filename:
                self.save(ed)

    def close_editor(self, ed=None):
        ed = ed or self.current_editor()
        if ed is None:
            return True
        if ed.document().isModified():
            self.tabs.setCurrentWidget(ed)
            res = QtWidgets.QMessageBox.question(
                self, "Close file", f"Save changes to {ed.name}?",
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard |
                QtWidgets.QMessageBox.Cancel)
            if res == QtWidgets.QMessageBox.Cancel:
                return False
            if res == QtWidgets.QMessageBox.Save and not self.save(ed):
                return False
        if ed.filename:
            self.watcher.removePath(ed.filename)
            if self.cfg.mainFile == ed.filename:
                self.cfg.mainFile = ""
        self.tabs.removeTab(self.tabs.indexOf(ed))
        ed.deleteLater()
        self.editorsChanged.emit()
        return True

    def close_all(self, keep=None):
        for ed in list(self.editors()):
            if ed is keep:
                continue
            if not self.close_editor(ed):
                return False
        return True

    def _update_title(self, ed):
        i = self.tabs.indexOf(ed)
        if i < 0:
            return
        title = ed.name
        if ed.document().isModified():
            title += " *"
        if ed.filename and ed.filename == self.cfg.mainFile:
            title = "★ " + title
        self.tabs.setTabText(i, title)
        if ed is self.current_editor():
            self.currentEditorChanged.emit(ed)

    def _on_current(self, index):
        ed = self.tabs.widget(index)
        if self.find_bar.isVisible():
            self.find_bar.highlight_all()
        self.currentEditorChanged.emit(ed)

    def set_main_file(self, ed=None):
        ed = ed or self.current_editor()
        if ed is None or not ed.filename:
            return
        self.cfg.mainFile = "" if self.cfg.mainFile == ed.filename else ed.filename
        for e in self.editors():
            self._update_title(e)

    def main_editor(self):
        if self.cfg.mainFile:
            return self.find_editor(self.cfg.mainFile)
        return None

    def _tab_menu(self, pos):
        index = self.tabs.tabBar().tabAt(pos)
        ed = self.tabs.widget(index)
        if ed is None:
            return
        win = self.window()
        menu = QtWidgets.QMenu(self)
        menu.addAction("Save", lambda: self.save(ed))
        menu.addAction("Save as...", lambda: self.save_as(ed))
        menu.addAction("Close", lambda: self.close_editor(ed))
        menu.addAction("Close others", lambda: self.close_all(keep=ed))
        menu.addSeparator()
        act = menu.addAction("Main file (run with Ctrl+M)", lambda: self.set_main_file(ed))
        act.setCheckable(True)
        act.setChecked(bool(ed.filename) and ed.filename == self.cfg.mainFile)
        act.setEnabled(bool(ed.filename))
        if hasattr(win, "run_file"):
            menu.addAction("Run file", lambda: win.run_file(ed))
            menu.addAction("Run file as script", lambda: win.run_file(ed, as_script=True))
        menu.addSeparator()
        if ed.filename:
            menu.addAction("Copy path", lambda: QtWidgets.QApplication.clipboard().setText(ed.filename))
            menu.addAction("Show in file browser",
                           lambda: hasattr(win, "show_in_file_browser") and win.show_in_file_browser(ed.filename))
        menu.exec(self.tabs.tabBar().mapToGlobal(pos))

    def _file_changed(self, path):
        if path in self._ignore_change:
            self._ignore_change.discard(path)
            if os.path.exists(path):
                self.watcher.addPath(path)
            return
        ed = self.find_editor(path)
        if ed is None:
            return
        if not os.path.exists(path):
            return
        self.watcher.addPath(path)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return
        if ed.mtime and abs(mtime - ed.mtime) < 0.01:
            return
        ed.mtime = mtime
        if not ed.document().isModified():
            self._reload(ed)
            return
        res = QtWidgets.QMessageBox.question(
            self, "File changed", f"{ed.name} was changed outside Ryzo. Reload it?")
        if res == QtWidgets.QMessageBox.Yes:
            self._reload(ed)

    def _reload(self, ed):
        cursor_pos = ed.textCursor().position()
        scroll = ed.verticalScrollBar().value()
        try:
            ed.load(ed.filename)
        except OSError:
            return
        c = ed.textCursor()
        c.setPosition(min(cursor_pos, ed.document().characterCount() - 1))
        ed.setTextCursor(c)
        ed.verticalScrollBar().setValue(scroll)

    # -------------------------------------------------------------- session --
    def session_state(self):
        files = []
        for ed in self.editors():
            if ed.filename:
                files.append({"path": ed.filename, "pos": ed.textCursor().position(),
                              "scroll": ed.verticalScrollBar().value()})
        cur = self.current_editor()
        return files, (cur.filename if cur is not None and cur.filename else "")

    def restore_session(self, files, current):
        for item in files:
            path = item.get("path") if isinstance(item, dict) else item
            if not path or not os.path.isfile(path):
                continue
            ed = self.open_file(path)
            if ed is not None and isinstance(item, dict):
                c = ed.textCursor()
                c.setPosition(min(item.get("pos", 0), ed.document().characterCount() - 1))
                ed.setTextCursor(c)
                QtCore.QTimer.singleShot(0, lambda e=ed, s=item.get("scroll", 0):
                                         e.verticalScrollBar().setValue(s))
        if current:
            ed = self.find_editor(current)
            if ed is not None:
                self.tabs.setCurrentWidget(ed)
