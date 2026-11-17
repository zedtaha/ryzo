"""A tabbed stack of R shells, plus the shell configuration dialog."""

import copy

from PySide6 import QtCore, QtWidgets

from ryzo.config import default_r_executable, get_config
from ryzo.core.kernel import find_r_executable
from ryzo.core.shell import ShellWidget


class ShellStack(QtWidgets.QWidget):
    currentShellChanged = QtCore.Signal(object)
    shellStateChanged = QtCore.Signal(object, str)
    kernelMessage = QtCore.Signal(object, dict)
    commandExecuted = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = get_config()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toolbar = QtWidgets.QToolBar(self)
        self.toolbar.setIconSize(QtCore.QSize(16, 16))
        self.toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        style = self.style()
        self.new_button = QtWidgets.QToolButton(self)
        self.new_button.setText("Shell")
        self.new_button.setIcon(style.standardIcon(QtWidgets.QStyle.SP_FileDialogNewFolder))
        self.new_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.new_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.new_menu = QtWidgets.QMenu(self)
        self.new_menu.aboutToShow.connect(self._fill_new_menu)
        self.new_button.setMenu(self.new_menu)
        self.toolbar.addWidget(self.new_button)
        self.toolbar.addSeparator()
        self.toolbar.addAction(style.standardIcon(QtWidgets.QStyle.SP_MediaPause), "Interrupt",
                               self.interrupt).setToolTip("Interrupt the running code (Ctrl+I)")
        self.toolbar.addAction(style.standardIcon(QtWidgets.QStyle.SP_BrowserReload), "Restart",
                               self.restart).setToolTip("Restart R (Ctrl+K)")
        self.toolbar.addAction(style.standardIcon(QtWidgets.QStyle.SP_DialogDiscardButton), "Clear",
                               self.clear).setToolTip("Clear the screen (Ctrl+L)")
        self.toolbar.addAction(style.standardIcon(QtWidgets.QStyle.SP_BrowserStop), "Terminate",
                               self.terminate).setToolTip("Terminate the R process")
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setContentsMargins(4, 0, 6, 0)
        self.toolbar.addWidget(self.status_label)
        layout.addWidget(self.toolbar)

        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(lambda i: self.close_shell(self.tabs.widget(i)))
        self.tabs.currentChanged.connect(self._on_current_changed)
        layout.addWidget(self.tabs)

    def _fill_new_menu(self):
        self.new_menu.clear()
        for i, sc in enumerate(self.cfg.shellConfigs):
            act = self.new_menu.addAction(f"Create shell: {sc['name']}",
                                          lambda c=sc: self.add_shell(c))
            if i < 8:
                act.setShortcut(f"Ctrl+{i + 1}")
        self.new_menu.addSeparator()
        self.new_menu.addAction("Edit shell configurations...", self.edit_configs)

    # --------------------------------------------------------------- shells --
    def shells(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def current_shell(self):
        return self.tabs.currentWidget()

    def add_shell(self, shell_config=None):
        if shell_config is None:
            shell_config = self.cfg.shellConfigs[0] if self.cfg.shellConfigs else {
                "name": "R", "exe": default_r_executable()}
        shell = ShellWidget(shell_config, self)
        shell.stateChanged.connect(self._on_shell_state)
        shell.kernelMessage.connect(self.kernelMessage)
        shell.executed.connect(self.commandExecuted)
        index = self.tabs.addTab(shell, shell_config.get("name", "R"))
        self.tabs.setCurrentIndex(index)
        shell.start()
        shell.setFocus()
        return shell

    def close_shell(self, shell=None):
        shell = shell or self.current_shell()
        if shell is None:
            return
        shell.shutdown()
        self.tabs.removeTab(self.tabs.indexOf(shell))
        shell.deleteLater()

    def interrupt(self):
        s = self.current_shell()
        if s:
            s.interrupt()

    def restart(self):
        s = self.current_shell()
        if s:
            s.restart()
        else:
            self.add_shell()

    def terminate(self):
        s = self.current_shell()
        if s:
            s.terminate()

    def clear(self):
        s = self.current_shell()
        if s:
            s.clear_screen()

    def shutdown(self):
        for s in self.shells():
            s.shutdown()

    def _on_current_changed(self, index):
        shell = self.tabs.widget(index)
        self._update_status(shell)
        self.currentShellChanged.emit(shell)

    def _on_shell_state(self, shell, state):
        i = self.tabs.indexOf(shell)
        if i >= 0:
            name = shell.shell_config.get("name", "R")
            icon = {"busy": "● ", "dead": "✕ ", "starting": "… "}.get(state, "")
            self.tabs.setTabText(i, icon + name)
        if shell is self.current_shell():
            self._update_status(shell)
        self.shellStateChanged.emit(shell, state)

    def _update_status(self, shell):
        if shell is None:
            self.status_label.setText("no shell")
            return
        version = shell.kernel.info.get("version", "").replace("R version ", "R ")
        version = version.split(" (")[0]
        self.status_label.setText(f"{version}  [{shell.kernel.state}]")

    def edit_configs(self):
        dlg = ShellConfigDialog(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.cfg.shellConfigs = dlg.configs()
            self.cfg.save()


class ShellConfigDialog(QtWidgets.QDialog):
    """Edit the list of shell configurations (one per R installation/setup)."""

    FIELDS = [
        ("name", "Name", "A name for this shell configuration"),
        ("exe", "R executable", "Path to R (R.exe on Windows). Leave as 'R' to use the PATH."),
        ("args", "Extra arguments", "Extra command line arguments for R, e.g. --vanilla"),
        ("startDir", "Startup directory", "Working directory for new shells (empty = home)"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shell configurations")
        self.resize(640, 420)
        self._configs = copy.deepcopy(get_config().shellConfigs) or [
            {"name": "R", "exe": default_r_executable()}]
        layout = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.list = QtWidgets.QListWidget()
        left.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Add")
        dup = QtWidgets.QPushButton("Duplicate")
        rem = QtWidgets.QPushButton("Remove")
        for b in (add, dup, rem):
            row.addWidget(b)
        left.addLayout(row)
        layout.addLayout(left, 1)

        right = QtWidgets.QVBoxLayout()
        form = QtWidgets.QFormLayout()
        self.edits = {}
        for key, label, tip in self.FIELDS:
            e = QtWidgets.QLineEdit()
            e.setToolTip(tip)
            e.textEdited.connect(lambda _t, k=key: self._store(k))
            if key in ("exe", "startDir"):
                w = QtWidgets.QWidget()
                h = QtWidgets.QHBoxLayout(w)
                h.setContentsMargins(0, 0, 0, 0)
                h.addWidget(e)
                b = QtWidgets.QPushButton("...")
                b.setFixedWidth(30)
                b.clicked.connect(lambda _c=False, k=key: self._browse(k))
                h.addWidget(b)
                form.addRow(label, w)
            else:
                form.addRow(label, e)
            self.edits[key] = e
        self.env_edit = QtWidgets.QPlainTextEdit()
        self.env_edit.setPlaceholderText("NAME=value, one per line")
        self.env_edit.setMaximumHeight(70)
        self.env_edit.textChanged.connect(lambda: self._store("env"))
        form.addRow("Environment", self.env_edit)
        self.startup_edit = QtWidgets.QPlainTextEdit()
        self.startup_edit.setPlaceholderText("R code to run when the shell starts, e.g. library(tidyverse)")
        self.startup_edit.setMaximumHeight(90)
        self.startup_edit.textChanged.connect(lambda: self._store("startupCode"))
        form.addRow("Startup code", self.startup_edit)
        right.addLayout(form)
        self.found = QtWidgets.QLabel()
        self.found.setWordWrap(True)
        right.addWidget(self.found)
        right.addStretch(1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                             QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        layout.addLayout(right, 2)

        add.clicked.connect(lambda: self._add({"name": "R", "exe": default_r_executable()}))
        dup.clicked.connect(lambda: self._add(copy.deepcopy(self._current() or {})))
        rem.clicked.connect(self._remove)
        self.list.currentRowChanged.connect(self._show)
        self._loading = False
        self._refresh_list()
        self.list.setCurrentRow(0)

    def _refresh_list(self):
        row = self.list.currentRow()
        self.list.clear()
        for c in self._configs:
            self.list.addItem(c.get("name", "R"))
        self.list.setCurrentRow(min(max(row, 0), len(self._configs) - 1))

    def _current(self):
        row = self.list.currentRow()
        return self._configs[row] if 0 <= row < len(self._configs) else None

    def _show(self, row):
        c = self._current()
        if c is None:
            return
        self._loading = True
        for key, e in self.edits.items():
            e.setText(c.get(key, ""))
        self.env_edit.setPlainText(c.get("env", ""))
        self.startup_edit.setPlainText(c.get("startupCode", ""))
        self._loading = False
        self._update_found()

    def _store(self, key):
        if self._loading:
            return
        c = self._current()
        if c is None:
            return
        if key == "env":
            c["env"] = self.env_edit.toPlainText()
        elif key == "startupCode":
            c["startupCode"] = self.startup_edit.toPlainText()
        else:
            c[key] = self.edits[key].text()
        if key == "name":
            self.list.currentItem().setText(c["name"])
        if key == "exe":
            self._update_found()

    def _update_found(self):
        c = self._current() or {}
        path = find_r_executable(c.get("exe") or "R")
        self.found.setText(f"Resolved R executable: {path}" if path else
                           "<b>R executable not found.</b> Install R or give its full path.")

    def _browse(self, key):
        if key == "exe":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select R executable")
        else:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select startup directory")
        if path:
            self.edits[key].setText(path)
            self._store(key)

    def _add(self, c):
        self._configs.append(c)
        self._refresh_list()
        self.list.setCurrentRow(len(self._configs) - 1)

    def _remove(self):
        row = self.list.currentRow()
        if len(self._configs) > 1 and row >= 0:
            del self._configs[row]
            self._refresh_list()

    def configs(self):
        return self._configs
