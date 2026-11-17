"""Ryzo main window."""

import os
import sys

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

import ryzo
from ryzo.config import get_config
from ryzo.core.dataviewer import DataViewer
from ryzo.core.editortabs import EditorTabs
from ryzo.core.rsyntax import cell_title
from ryzo.core.shellstack import ShellStack
from ryzo.core.themes import THEMES, apply_app_palette, get_theme
from ryzo.tools.editorlist import EditorListTool
from ryzo.tools.filebrowser import FileBrowserTool
from ryzo.tools.help import HelpTool
from ryzo.tools.history import HistoryTool
from ryzo.tools.plots import PlotsTool
from ryzo.tools.sourcestructure import SourceStructureTool
from ryzo.tools.workspace import WorkspaceTool

TOOL_CLASSES = [FileBrowserTool, WorkspaceTool, PlotsTool, HelpTool, SourceStructureTool,
                HistoryTool, EditorListTool]


def make_icon():
    icon = QtGui.QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QtGui.QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        grad = QtGui.QLinearGradient(0, 0, size, size)
        grad.setColorAt(0, QtGui.QColor("#3b6fd1"))
        grad.setColorAt(1, QtGui.QColor("#1d3f8f"))
        p.setBrush(grad)
        p.setPen(Qt.NoPen)
        r = size * 0.22
        p.drawRoundedRect(QtCore.QRectF(0, 0, size, size), r, r)
        f = QtGui.QFont("sans-serif")
        f.setBold(True)
        f.setPixelSize(int(size * 0.72))
        p.setFont(f)
        p.setPen(QtGui.QColor("#ffffff"))
        p.drawText(QtCore.QRectF(0, -size * 0.03, size, size), Qt.AlignCenter, "R")
        p.setBrush(QtGui.QColor("#ffcc33"))
        p.setPen(Qt.NoPen)
        d = size * 0.2
        p.drawEllipse(QtCore.QRectF(size - d * 1.25, size - d * 1.25, d, d))
        p.end()
        icon.addPixmap(pm)
    return icon


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, files=()):
        super().__init__()
        self.cfg = get_config()
        self.setWindowTitle("Ryzo")
        self.setWindowIcon(make_icon())
        self.resize(1280, 820)
        self.setDockOptions(QtWidgets.QMainWindow.AnimatedDocks |
                            QtWidgets.QMainWindow.AllowTabbedDocks |
                            QtWidgets.QMainWindow.AllowNestedDocks)
        self._viewers = []

        self.editors = EditorTabs(self)
        self.setCentralWidget(self.editors)
        self.editors.currentEditorChanged.connect(self._on_editor_changed)

        self.shells = ShellStack(self)
        self.shell_dock = self._make_dock("Shells", self.shells, Qt.RightDockWidgetArea)
        self.shells.kernelMessage.connect(self._on_kernel_message)
        self.shells.commandExecuted.connect(lambda c: self.tools["HistoryTool"].add(c))
        self.shells.currentShellChanged.connect(self._on_shell_changed)
        self.shells.shellStateChanged.connect(lambda s, st: self._update_status())

        self.tools = {}
        self.tool_docks = {}
        first = None
        for cls in TOOL_CLASSES:
            tool = cls(self)
            self.tools[cls.__name__] = tool
            dock = self._make_dock(cls.title, tool, Qt.RightDockWidgetArea)
            self.tool_docks[cls.__name__] = dock
            if first is None:
                first = dock
                self.splitDockWidget(self.shell_dock, dock, Qt.Vertical)
            else:
                self.tabifyDockWidget(first, dock)
        first.raise_()
        self.resizeDocks([self.shell_dock], [560], Qt.Horizontal)
        self.resizeDocks([self.shell_dock, first], [460, 340], Qt.Vertical)

        self._build_statusbar()
        self._build_menus()

        self._restore_window()
        self.apply_theme(self.cfg.theme, initial=True)

        # initial content
        self.editors.restore_session(self.cfg.openFiles, self.cfg.currentFile)
        for f in files:
            self.editors.open_file(f)
        if self.cfg.firstRun:
            self.open_tutorial()
            self.cfg.firstRun = False
        if not self.editors.editors():
            self.editors.new_file()
        self.shells.add_shell()
        QtCore.QTimer.singleShot(0, lambda: (self.editors.current_editor() or self).setFocus())

    # ------------------------------------------------------------ helpers --
    def _make_dock(self, title, widget, area):
        dock = QtWidgets.QDockWidget(title, self)
        dock.setObjectName("dock_" + title.replace(" ", "_"))
        dock.setWidget(widget)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable |
                         QtWidgets.QDockWidget.DockWidgetFloatable |
                         QtWidgets.QDockWidget.DockWidgetClosable)
        self.addDockWidget(area, dock)
        return dock

    def show_tool(self, tool, focus=False):
        for name, t in self.tools.items():
            if t is tool:
                dock = self.tool_docks[name]
                dock.show()
                dock.raise_()
                if focus:
                    tool.setFocus()

    def current_shell(self):
        return self.shells.current_shell()

    def current_editor(self):
        return self.editors.current_editor()

    def connect_editor(self, ed):
        ed.completionRequested.connect(self._complete_in_editor)
        ed.calltipRequested.connect(self._calltip_in_editor)
        ed.cursorPositionChanged.connect(lambda e=ed: self._on_cursor(e))

    # ------------------------------------------------------- status bar --
    def _build_statusbar(self):
        sb = self.statusBar()
        self.pos_label = QtWidgets.QLabel()
        self.file_label = QtWidgets.QLabel()
        self.wd_label = QtWidgets.QLabel()
        self.wd_label.setToolTip("Working directory of the current R shell")
        sb.addWidget(self.wd_label, 1)
        sb.addPermanentWidget(self.file_label)
        sb.addPermanentWidget(self.pos_label)

    def _update_status(self):
        ed = self.current_editor()
        if ed is not None:
            c = ed.textCursor()
            self.pos_label.setText(f"Ln {c.blockNumber() + 1}, Col {c.positionInBlock() + 1}")
            enc = ed.encoding.upper()
            eol = {"\n": "LF", "\r\n": "CRLF", "\r": "CR"}[ed.line_ending]
            self.file_label.setText(f"{enc}  {eol}  R  ")
        shell = self.current_shell()
        cwd = getattr(shell, "cwd", "") if shell else ""
        self.wd_label.setText(f"wd: {cwd}" if cwd else "")

    def _on_cursor(self, ed):
        if ed is self.current_editor():
            self._update_status()
            self.tools["HelpTool"].editor_cursor_moved(ed)

    def _on_editor_changed(self, ed):
        name = ed.name if ed is not None else ""
        path = ed.filename if ed is not None and ed.filename else name
        self.setWindowTitle(f"{path} - Ryzo" if path else "Ryzo")
        self._update_status()

    def _on_shell_changed(self, shell):
        self._update_status()
        self.tools["WorkspaceTool"].refresh()

    # ------------------------------------------------------------- menus --
    def _build_menus(self):
        mb = self.menuBar()
        self.actions = {}

        def act(menu, text, slot, shortcut=None, checkable=False, checked=False, tip=None):
            a = QtGui.QAction(text, self)
            if shortcut:
                keys = [QtGui.QKeySequence(s) for s in shortcut.split("|")]
                a.setShortcuts(keys)
                a.setShortcutContext(Qt.WindowShortcut)
            if checkable:
                a.setCheckable(True)
                a.setChecked(checked)
                a.toggled.connect(slot)
            else:
                a.triggered.connect(lambda _c=False: slot())
            if tip:
                a.setStatusTip(tip)
            menu.addAction(a)
            self.actions[text] = a
            return a

        ed = self.current_editor
        style = self.style()

        # File
        m = mb.addMenu("&File")
        act(m, "New", self.editors.new_file, "Ctrl+N").setIcon(style.standardIcon(QtWidgets.QStyle.SP_FileIcon))
        act(m, "Open...", self.editors.open_file, "Ctrl+O").setIcon(style.standardIcon(QtWidgets.QStyle.SP_DialogOpenButton))
        self.recent_menu = m.addMenu("Recent files")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        act(m, "Save", lambda: self.editors.save(), "Ctrl+S").setIcon(style.standardIcon(QtWidgets.QStyle.SP_DialogSaveButton))
        act(m, "Save as...", lambda: self.editors.save_as(), "Ctrl+Shift+S")
        act(m, "Save all", self.editors.save_all, "Ctrl+Alt+S")
        m.addSeparator()
        act(m, "Close", lambda: self.editors.close_editor(), "Ctrl+W")
        act(m, "Close all", self.editors.close_all)
        act(m, "Toggle main file", self.editors.set_main_file,
            tip="Mark the current file as the main file (run it from anywhere with Ctrl+M)")
        m.addSeparator()
        self.import_menu = m.addMenu("Import Dataset")
        self.fill_import_menu(self.import_menu)
        m.addSeparator()
        act(m, "Quit", self.close, "Ctrl+Q")

        # Edit
        m = mb.addMenu("&Edit")
        act(m, "Undo", lambda: ed() and ed().undo(), "Ctrl+Z")
        act(m, "Redo", lambda: ed() and ed().redo(), "Ctrl+Y|Ctrl+Shift+Z")
        m.addSeparator()
        act(m, "Cut", lambda: self._focus_call("cut"), None)
        act(m, "Copy", lambda: self._focus_call("copy"), None)
        act(m, "Paste", lambda: self._focus_call("paste"), None)
        act(m, "Select all", lambda: self._focus_call("selectAll"), None)
        m.addSeparator()
        act(m, "Indent", lambda: ed() and ed().indent_selection(), None)
        act(m, "Dedent", lambda: ed() and ed().dedent_selection(), None)
        act(m, "Comment", lambda: ed() and ed().comment_selection(), "Ctrl+R")
        act(m, "Uncomment", lambda: ed() and ed().uncomment_selection(), "Ctrl+T")
        act(m, "Toggle comment", lambda: ed() and ed().toggle_comment(), "Ctrl+Shift+3|Ctrl+/")
        act(m, "Duplicate line", lambda: ed() and ed().duplicate_lines(), "Ctrl+Shift+D")
        act(m, "Delete line", lambda: ed() and ed().delete_lines(), "Ctrl+Shift+K")
        act(m, "Insert cell separator", self.insert_cell, "Ctrl+Alt+I",
            tip="Insert a '##' cell separator line")
        m.addSeparator()
        act(m, "Find or replace", lambda: self.editors.find_bar.show_bar(), "Ctrl+F")
        act(m, "Replace", lambda: self.editors.find_bar.show_bar(replace=True), "Ctrl+H")
        act(m, "Find next", lambda: self.editors.find_bar.find(), "Ctrl+G|F3")
        act(m, "Find previous", lambda: self.editors.find_bar.find(backward=True), "Ctrl+Shift+G|Shift+F3")
        act(m, "Find selection", self._find_selection, "Ctrl+F3")
        act(m, "Go to line...", self.goto_line, "Alt+G")

        # View
        m = mb.addMenu("&View")
        act(m, "Select editor", lambda: ed() and ed().setFocus(), "Ctrl+9|F2")
        act(m, "Select shell", lambda: self.current_shell() and self.current_shell().setFocus(), "Ctrl+0|F1")
        act(m, "Select previous file", lambda: self._cycle_editor(-1), "Ctrl+PgUp")
        act(m, "Select next file", lambda: self._cycle_editor(1), "Ctrl+PgDown")
        m.addSeparator()
        z = m.addMenu("Zooming")
        act(z, "Zoom in", lambda: self.zoom(1), "Ctrl+=|Ctrl++")
        act(z, "Zoom out", lambda: self.zoom(-1), "Ctrl+-")
        act(z, "Zoom reset", lambda: self.zoom(0), "Ctrl+\\")
        m.addSeparator()
        act(m, "Wrap long lines", self._set_wrap, checkable=True, checked=self.cfg.wrap)
        act(m, "Show whitespace", self._set_whitespace, checkable=True, checked=self.cfg.showWhitespace)
        act(m, "Show line numbers", lambda v: self._set_opt("showLineNumbers", v), checkable=True,
            checked=self.cfg.showLineNumbers)
        act(m, "Show indentation guides", lambda v: self._set_opt("showIndentGuides", v), checkable=True,
            checked=self.cfg.showIndentGuides)
        act(m, "Highlight current line", lambda v: self._set_opt("highlightCurrentLine", v),
            checkable=True, checked=self.cfg.highlightCurrentLine)
        act(m, "Long line indicator at column 80",
            lambda v: self._set_opt("longLineIndicator", 80 if v else 0), checkable=True,
            checked=bool(self.cfg.longLineIndicator))
        m.addSeparator()
        tm = m.addMenu("Theme")
        group = QtGui.QActionGroup(self)
        for name in THEMES:
            a = tm.addAction(name)
            a.setCheckable(True)
            a.setChecked(name == self.cfg.theme)
            a.triggered.connect(lambda _c=False, n=name: self.apply_theme(n))
            group.addAction(a)
        act(m, "Font...", self.choose_font)

        # Settings
        m = mb.addMenu("&Settings")
        act(m, "Automatically complete code", lambda v: self._set_opt("autoComplete", v),
            checkable=True, checked=self.cfg.autoComplete)
        act(m, "Show calltips", lambda v: self._set_opt("calltips", v), checkable=True,
            checked=self.cfg.calltips)
        act(m, "Auto-close brackets and quotes", lambda v: self._set_opt("autoClose", v),
            checkable=True, checked=self.cfg.autoClose)
        im = m.addMenu("Indentation width")
        group = QtGui.QActionGroup(self)
        for n in (2, 4, 8):
            a = im.addAction(f"{n} spaces")
            a.setCheckable(True)
            a.setChecked(self.cfg.indentWidth == n)
            a.triggered.connect(lambda _c=False, n=n: self._set_opt("indentWidth", n))
            group.addAction(a)
        m.addSeparator()
        act(m, "Edit shell configurations...", self.shells.edit_configs)
        act(m, "Open configuration folder", lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(os.path.dirname(self.cfg.path))))

        # Shell
        m = mb.addMenu("&Shell")
        self.shell_menu = m
        m.aboutToShow.connect(self._fill_shell_menu)
        self._fill_shell_menu()
        self._install_shell_shortcuts()

        # Run
        m = mb.addMenu("&Run")
        act(m, "Run selection or line", lambda: self.run_selection(), "Alt+Return|F9",
            tip="Run the selected code, or the current line")
        act(m, "Run selection and advance", lambda: self.run_selection(advance=True),
            "Shift+F9|Shift+Alt+Return")
        act(m, "Run cell", lambda: self.run_cell(), "Ctrl+Return|Ctrl+Enter",
            tip="Run the cell under the cursor (cells are separated by ## lines)")
        act(m, "Run cell and advance", lambda: self.run_cell(advance=True),
            "Ctrl+Shift+Return|Ctrl+Shift+Enter")
        act(m, "Run from start to cursor", self.run_to_cursor, "Ctrl+Alt+B")
        m.addSeparator()
        act(m, "Run file", lambda: self.run_file(), "Ctrl+E|F5")
        act(m, "Run main file", lambda: self.run_file(self.editors.main_editor()), "Ctrl+M|F6")
        act(m, "Run file as script", lambda: self.run_file(as_script=True), "Ctrl+Shift+E|Ctrl+F5",
            tip="Restart R, change to the file's folder and run the file")
        act(m, "Run main file as script", lambda: self.run_file(self.editors.main_editor(), as_script=True),
            "Ctrl+Shift+M|Ctrl+F6")
        m.addSeparator()
        act(m, "Help on word under cursor", self.help_under_cursor, "Shift+F1")

        # Tools
        m = mb.addMenu("&Tools")
        act(m, "Install Packages...", lambda: self.install_packages())
        act(m, "Update Packages...", lambda: self.execute_code(
            "update.packages(ask = FALSE, checkBuilt = TRUE)", "block",
            label="[Update Packages]"))
        m.addSeparator()
        for name, dock in self.tool_docks.items():
            a = dock.toggleViewAction()
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.shell_dock.toggleViewAction())
        act(m, "Reset layout", self.reset_layout)

        # Help
        m = mb.addMenu("&Help")
        act(m, "Ryzo tutorial", self.open_tutorial)
        act(m, "R documentation (help.start)", lambda: self.execute_code("help.start()", "block"))
        act(m, "An introduction to R (online)", lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl("https://cran.r-project.org/doc/manuals/r-release/R-intro.html")))
        act(m, "Keyboard shortcuts", self.show_shortcuts)
        m.addSeparator()
        act(m, "About Ryzo", self.about)

    def _fill_shell_menu(self):
        m = self.shell_menu
        m.clear()
        for i, sc in enumerate(self.cfg.shellConfigs):
            hint = f"\tCtrl+{i + 1}" if i < 8 else ""
            m.addAction(f"Create shell {i + 1}: ({sc['name']}){hint}",
                        lambda c=sc: self.shells.add_shell(c))
        m.addSeparator()
        for text, slot, key in (
                ("Interrupt", self.shells.interrupt, "Ctrl+I"),
                ("Restart", self.shells.restart, "Ctrl+K"),
                ("Terminate", self.shells.terminate, None),
                ("Close", self.shells.close_shell, "Alt+K"),
                ("Clear screen", self.shells.clear, "Ctrl+L")):
            m.addAction(text + (f"\t{key}" if key else ""), slot)
        m.addSeparator()
        m.addAction("Change directory to current file", self.cd_to_file)
        m.addAction("Change directory...", self.choose_wd)
        m.addSeparator()
        m.addAction("Edit shell configurations...", self.shells.edit_configs)

    def _install_shell_shortcuts(self):
        # the Shell menu is rebuilt on show, so its shortcuts are registered separately
        for key, slot in (("Ctrl+I", self.shells.interrupt), ("Ctrl+K", self.shells.restart),
                          ("Alt+K", self.shells.close_shell), ("Ctrl+L", self.shells.clear)):
            sc = QtGui.QShortcut(QtGui.QKeySequence(key), self)
            sc.activated.connect(slot)
        for i in range(8):
            sc = QtGui.QShortcut(QtGui.QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.activated.connect(lambda i=i: i < len(self.cfg.shellConfigs) and
                                 self.shells.add_shell(self.cfg.shellConfigs[i]))


    def _fill_recent(self):
        self.recent_menu.clear()
        for f in self.cfg.recentFiles:
            self.recent_menu.addAction(f, lambda f=f: self.editors.open_file(f))
        if not self.cfg.recentFiles:
            self.recent_menu.addAction("(none)").setEnabled(False)

    def _focus_call(self, name):
        w = QtWidgets.QApplication.focusWidget()
        if w is not None and hasattr(w, name):
            getattr(w, name)()

    def _cycle_editor(self, d):
        t = self.editors.tabs
        if t.count():
            t.setCurrentIndex((t.currentIndex() + d) % t.count())
            self.current_editor().setFocus()

    def _find_selection(self):
        ed = self.current_editor()
        if ed is None:
            return
        word = ed.textCursor().selectedText() or ed.word_under_cursor()
        self.editors.find_bar.find_edit.setText(word)
        self.editors.find_bar.show()
        self.editors.find_bar.find()
        ed.setFocus()

    def goto_line(self):
        ed = self.current_editor()
        if ed is None:
            return
        n, ok = QtWidgets.QInputDialog.getInt(self, "Go to line", "Line number:",
                                              ed.textCursor().blockNumber() + 1, 1, ed.blockCount())
        if ok:
            ed.go_to_line(n - 1)

    def insert_cell(self):
        ed = self.current_editor()
        if ed is None:
            return
        c = ed.textCursor()
        c.movePosition(QtGui.QTextCursor.StartOfBlock)
        c.insertText("## \n")
        c.movePosition(QtGui.QTextCursor.Up)
        c.movePosition(QtGui.QTextCursor.EndOfBlock)
        ed.setTextCursor(c)

    # ------------------------------------------------------- appearance --
    def zoom(self, d):
        self.cfg.zoom = 0 if d == 0 else max(-6, min(20, self.cfg.zoom + d))
        for ed in self.editors.editors():
            ed.set_font_zoom()
        for s in self.shells.shells():
            s.set_font_zoom()

    def _set_wrap(self, v):
        self.cfg.wrap = v
        for ed in self.editors.editors():
            ed.set_wrap(v)

    def _set_whitespace(self, v):
        self.cfg.showWhitespace = v
        for ed in self.editors.editors():
            ed.set_show_whitespace(v)

    def _set_opt(self, key, value):
        self.cfg[key] = value
        for ed in self.editors.editors():
            ed.set_font_zoom()
            ed._on_cursor_moved()
            ed.viewport().update()

    def apply_theme(self, name, initial=False):
        self.cfg.theme = name
        theme = get_theme(name)
        apply_app_palette(QtWidgets.QApplication.instance(), theme)
        if not initial:
            for ed in self.editors.editors():
                ed.apply_theme(theme)
            for s in self.shells.shells():
                s.apply_theme(theme)

    def choose_font(self):
        ed = self.current_editor()
        font = ed.font() if ed else QtGui.QFont()
        font.setPointSize(int(self.cfg.font.get("size", 10)))
        ok, font = QtWidgets.QFontDialog.getFont(font, self, "Editor font",
                                                 QtWidgets.QFontDialog.MonospacedFonts)
        if isinstance(ok, QtGui.QFont):  # PySide versions differ in return order
            ok, font = font, ok
        if ok:
            self.cfg.font = {"family": font.family(), "size": font.pointSize()}
            self.zoom(0)

    # --------------------------------------------------------------- run --
    def _target_shell(self):
        shell = self.current_shell()
        if shell is None:
            shell = self.shells.add_shell()
        return shell

    def execute_code(self, code, mode="block", srcname="", lineoffset=0, label=None):
        shell = self._target_shell()
        if not shell.kernel.is_alive and shell.kernel.state == "starting":
            shell.kernel.execute(code, mode, srcname, lineoffset)
            return
        shell.execute(code, mode, srcname, lineoffset, echo_label=label)

    def run_selection(self, advance=False):
        ed = self.current_editor()
        if ed is None:
            return
        c = ed.textCursor()
        doc = ed.document()
        if c.hasSelection():
            text = c.selectedText().replace(" ", "\n")
            first = doc.findBlock(c.selectionStart()).blockNumber()
            last_block = doc.findBlock(c.selectionEnd())
        else:
            text = c.block().text()
            first = c.blockNumber()
            last_block = c.block()
        last = last_block.blockNumber()
        if c.hasSelection() and c.selectionEnd() == last_block.position() and last > first:
            last -= 1  # selection ends at the start of a line
        label = (f"[Run lines {first + 1}\u2013{last + 1} of {ed.name}]"
                 if last > first else None)
        if text.strip():
            self.execute_code(text, "block", ed.filename or ed.name, first, label=label)
        if advance:
            b = last_block.next()
            while b.isValid() and not b.text().strip():
                b = b.next()
            if b.isValid():
                nc = QtGui.QTextCursor(b)
                ed.setTextCursor(nc)
                ed.ensureCursorVisible()

    def run_cell(self, advance=False):
        ed = self.current_editor()
        if ed is None:
            return
        if ed.textCursor().hasSelection():
            # like RStudio: with a selection, Ctrl+Enter runs the selection
            self.run_selection(advance=advance)
            return
        text, first, last = ed.cell_text()
        start_block = ed.document().findBlockByNumber(first)
        title = cell_title(start_block.text()) if first in ed.cell_markers() else None
        lines = f"lines {first + 1}\u2013{last.blockNumber() + 1} of {ed.name}"
        label = f"[Run cell {title!r}, {lines}]" if title and title != "(cell)" else \
            f"[Run cell, {lines}]"
        if text.strip():
            self.execute_code(text, "block", ed.filename or ed.name, first, label=label)
        if advance:
            nxt = last.next()
            if nxt.isValid():
                nc = QtGui.QTextCursor(nxt)
                ed.setTextCursor(nc)
                ed.ensureCursorVisible()

    def run_to_cursor(self):
        ed = self.current_editor()
        if ed is None:
            return
        c = ed.textCursor()
        c.movePosition(QtGui.QTextCursor.EndOfBlock)
        c.setPosition(0, QtGui.QTextCursor.KeepAnchor)
        text = c.selectedText().replace(" ", "\n")
        self.execute_code(text, "file", ed.filename or ed.name, 0,
                          label=f"[Run {ed.name} up to line {ed.textCursor().blockNumber() + 1}]")

    def run_file(self, ed=None, as_script=False):
        ed = ed or self.current_editor()
        if ed is None:
            QtWidgets.QMessageBox.information(self, "Run", "There is no (main) file to run.")
            return
        text = ed.toPlainText()
        name = ed.filename or ed.name
        if as_script:
            if ed.document().isModified() and ed.filename:
                self.editors.save(ed)
            shell = self._target_shell()
            shell.restart()
            if ed.filename:
                d = os.path.dirname(ed.filename).replace("\\", "/").replace('"', '\\"')
                shell.kernel.execute(f'setwd("{d}")', "file")
            shell.write(f"[Run {ed.name} as script]\n", "info")
            shell.kernel.execute(text, "file", name, 0)
            return
        self.execute_code(text, "file", name, 0, label=f"[Run file {ed.name}]")

    def help_under_cursor(self):
        ed = self.current_editor()
        word = ed.word_under_cursor() if ed is not None else ""
        if word:
            self.show_help(word)

    # ------------------------------------------------ import / packages --
    def fill_import_menu(self, menu):
        from ryzo.core.importdialog import FORMATS
        for key, (label, pkg, _) in FORMATS.items():
            menu.addAction(label + "...", lambda k=key: self.import_dataset(fmt=k))

    def import_dataset(self, path="", fmt=None):
        from ryzo.core.importdialog import ImportDatasetDialog
        if self.current_shell() is None:
            self.shells.add_shell()
        ImportDatasetDialog(self, path=path, fmt=fmt).exec()

    def install_packages(self, packages=""):
        from ryzo.core.packagedialog import InstallPackagesDialog
        if self.current_shell() is None:
            self.shells.add_shell()
        InstallPackagesDialog(self, packages=packages).exec()

    def show_help(self, topic):
        tool = self.tools["HelpTool"]
        self.show_tool(tool)
        tool.show_help(topic)

    def setwd(self, path):
        shell = self.current_shell()
        if shell is None:
            return
        p = path.replace("\\", "/").replace('"', '\\"')
        self.execute_code(f'setwd("{p}")', "block")

    def cd_to_file(self):
        ed = self.current_editor()
        if ed is not None and ed.filename:
            self.setwd(os.path.dirname(ed.filename))

    def choose_wd(self):
        shell = self.current_shell()
        start = getattr(shell, "cwd", "") or os.path.expanduser("~")
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "R working directory", start)
        if path:
            self.setwd(path)

    def show_in_file_browser(self, filename):
        tool = self.tools["FileBrowserTool"]
        self.show_tool(tool)
        tool.show_file(filename)

    # ------------------------------------------------- completion/calltips --
    def _complete_in_editor(self, ed, line):
        import re
        m = re.search(r"([A-Za-z_.][A-Za-z0-9_.]*(\$|@|:::?)?[A-Za-z0-9_.]*)$", line)
        token = m.group(1) if m else ""
        local_prefix = re.split(r"\$|@|::", token)[-1]
        buffer_words = ed.buffer_words(token) if token and token == local_prefix else []

        shell = self.current_shell()

        def done(msg):
            items = list(msg.get("items") or [])
            tok = msg.get("token") or token
            seen = set(items)
            items += [w for w in buffer_words if w not in seen]
            ed.show_completions(tok, items)

        if shell is None or not shell.kernel.complete(line, done):
            if buffer_words:
                ed.show_completions(token, buffer_words)

    def _calltip_in_editor(self, ed, name):
        shell = self.current_shell()
        if shell is not None:
            shell.kernel.calltip(name, lambda msg: ed.show_calltip(msg.get("tip", "")))

    # ------------------------------------------------------ kernel messages --
    def _on_kernel_message(self, shell, msg):
        t = msg.get("type")
        if t == "cwd":
            shell.cwd = msg.get("path", "")
            if shell is self.current_shell():
                self._update_status()
        elif t == "hello":
            shell.cwd = msg.get("cwd", "")
            self._update_status()
        elif t == "view":
            try:
                v = DataViewer(msg["path"], msg.get("title", ""), msg.get("nrow", 0), self)
            except (OSError, IndexError) as err:
                shell.write(f"[Could not open data viewer: {err}]\n", "err")
                return
            v.setAttribute(Qt.WA_DeleteOnClose)
            v.show()
            self._viewers.append(v)
        elif t == "open_url":
            url = msg.get("url", "")
            qurl = QtCore.QUrl.fromLocalFile(url) if os.path.exists(url) else QtCore.QUrl(url)
            QtGui.QDesktopServices.openUrl(qurl)
        for name in ("WorkspaceTool", "PlotsTool", "HelpTool"):
            self.tools[name].on_message(shell, msg)

    # ----------------------------------------------------------- dialogs --
    def open_tutorial(self):
        path = os.path.join(ryzo.RESOURCE_DIR, "tutorial.R")
        if not os.path.exists(path):
            return
        ed = self.editors.find_editor(path)
        if ed is None:
            ed = self.editors.new_file()
            with open(path, encoding="utf-8") as f:
                ed.setPlainText(f.read())
            ed._tmpname = "tutorial.R"
            ed.document().setModified(False)
            self.editors._update_title(ed)
        self.editors.tabs.setCurrentWidget(ed)

    def show_shortcuts(self):
        rows = []
        for text, a in self.actions.items():
            keys = ", ".join(k.toString(QtGui.QKeySequence.NativeText) for k in a.shortcuts())
            if keys:
                rows.append(f"<tr><td>{text}</td><td><b>{keys}</b></td></tr>")
        rows += [f"<tr><td>{t}</td><td><b>{k}</b></td></tr>" for t, k in (
            ("Interrupt", "Ctrl+I, or Ctrl+C in the shell"), ("Restart shell", "Ctrl+K"),
            ("Clear shell", "Ctrl+L"), ("Close shell", "Alt+K"),
            ("New shell 1..8", "Ctrl+1 .. Ctrl+8"))]
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Keyboard shortcuts")
        box.setText("<table>" + "".join(rows) + "</table>")
        box.exec()

    def about(self):
        versions = []
        for s in self.shells.shells():
            v = s.kernel.info.get("version")
            if v and v not in versions:
                versions.append(v)
        import PySide6
        QtWidgets.QMessageBox.about(
            self, "About Ryzo",
            f"<h2>Ryzo {ryzo.__version__}</h2>"
            "<p>The interactive editor for R. Ryzo is modelled after "
            "<a href='https://pyzo.org'>Pyzo</a>, the interactive editor for Python, and keeps "
            "its philosophy: an editor and interactive shells side by side, with cells, "
            "simple tools and no clutter.</p>"
            f"<p>R: {', '.join(versions) or 'no running shell'}<br>"
            f"Python {sys.version.split()[0]}, PySide {PySide6.__version__}, Qt {QtCore.qVersion()}</p>"
            f"<p>Config: {self.cfg.path}</p>"
            "<p>License: BSD 2-clause (same as Pyzo).</p>")

    # ---------------------------------------------------------- layout --
    def _restore_window(self):
        geo = self.cfg.windowGeometry
        state = self.cfg.windowState
        self._default_state = self.saveState()
        if geo:
            self.restoreGeometry(QtCore.QByteArray.fromBase64(geo.encode()))
        if state:
            self.restoreState(QtCore.QByteArray.fromBase64(state.encode()))

    def reset_layout(self):
        self.restoreState(self._default_state)
        for dock in list(self.tool_docks.values()) + [self.shell_dock]:
            dock.show()
            dock.setFloating(False)

    def closeEvent(self, event):
        files, current = self.editors.session_state()
        for ed in self.editors.editors():
            if ed.document().isModified():
                self.editors.tabs.setCurrentWidget(ed)
                res = QtWidgets.QMessageBox.question(
                    self, "Quit", f"Save changes to {ed.name}?",
                    QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard |
                    QtWidgets.QMessageBox.Cancel)
                if res == QtWidgets.QMessageBox.Cancel:
                    event.ignore()
                    return
                if res == QtWidgets.QMessageBox.Save and not self.editors.save(ed):
                    event.ignore()
                    return
        self.cfg.openFiles = files
        self.cfg.currentFile = current
        self.cfg.windowGeometry = bytes(self.saveGeometry().toBase64()).decode()
        self.cfg.windowState = bytes(self.saveState().toBase64()).decode()
        self.shells.shutdown()
        self.cfg.save()
        event.accept()


def run(argv=()):
    QtCore.QCoreApplication.setApplicationName("Ryzo")
    QtCore.QCoreApplication.setOrganizationName("Ryzo")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]])
    app.setWindowIcon(make_icon())
    files = [a for a in argv if not a.startswith("-")]
    win = MainWindow(files)
    win.show()
    return app.exec()
