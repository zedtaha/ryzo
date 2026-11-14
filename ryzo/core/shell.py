"""The interactive R shell widget."""

import re

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ryzo.config import get_config
from ryzo.core.editor import default_font
from ryzo.core.kernel import RKernel
from ryzo.core.themes import get_theme

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
MAX_CHARS = 2_000_000


class ShellWidget(QtWidgets.QPlainTextEdit):
    """Console showing output with an editable input line at the bottom."""

    stateChanged = QtCore.Signal(object, str)
    executed = QtCore.Signal(str)  # a command typed by the user
    kernelMessage = QtCore.Signal(object, dict)

    def __init__(self, shell_config, parent=None):
        super().__init__(parent)
        self.cfg = get_config()
        self.shell_config = dict(shell_config)
        self.theme = get_theme(self.cfg.theme)
        self.setFont(default_font())
        self.setUndoRedoEnabled(False)
        self.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.document().setDocumentMargin(4)

        self._prompt_start = 0  # where the prompt begins
        self._input_start = 0  # where user input begins
        self._prompt = ""
        self._prompt_visible = False
        self._history = list(self.cfg.history[-1000:])
        self._hist_index = len(self._history)
        self._hist_prefix = None
        self._formats = {}
        self._pending_cr = False
        self._apply_formats()

        self.kernel = RKernel(shell_config, self)
        self.kernel.output.connect(self.write)
        self.kernel.stateChanged.connect(self._on_state)
        self.kernel.promptChanged.connect(self._on_prompt)
        self.kernel.started.connect(self._on_started)
        self.kernel.message.connect(self._on_message)

        self._completer = QtWidgets.QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setModelSorting(QtWidgets.QCompleter.UnsortedModel)
        self._cmodel = QtCore.QStringListModel(self)
        self._completer.setModel(self._cmodel)
        self._completer.activated.connect(self._insert_completion)
        self._completion_token = ""

    # ---------------------------------------------------------- appearance --
    def _apply_formats(self):
        t = self.theme

        def fmt(color, bold=False, italic=False):
            f = QtGui.QTextCharFormat()
            f.setForeground(QtGui.QColor(color))
            if bold:
                f.setFontWeight(QtGui.QFont.Bold)
            if italic:
                f.setFontItalic(True)
            return f

        self._formats = {
            "out": fmt(t["shell_out"]),
            "err": fmt(t["shell_err"]),
            "warning": fmt(t["shell_warn"]),
            "echo": fmt(t["shell_echo"]),
            "info": fmt(t["shell_info"], italic=True),
            "prompt": fmt(t["shell_prompt"], bold=True),
            "input": fmt(t["foreground"]),
        }
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Base, QtGui.QColor(t["background"]))
        pal.setColor(QtGui.QPalette.Text, QtGui.QColor(t["foreground"]))
        pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(t["selection"]))
        pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(t["foreground"]))
        self.setPalette(pal)

    def apply_theme(self, theme):
        self.theme = theme
        self._apply_formats()

    def set_font_zoom(self):
        self.setFont(default_font())

    # ------------------------------------------------------------- kernel --
    def start(self):
        self.write(f"Starting R ({self.shell_config.get('name', 'R')})...\n", "info")
        self.kernel.start()

    def _on_started(self, info):
        version = info.get("version", "R")
        self.write(f"{version} -- Ryzo shell, pid {info.get('pid')}\n"
                   "Type ?topic for help, Ctrl+I (or Ctrl+C) to interrupt, Ctrl+K to restart.\n",
                   "info")
        startup = self.shell_config.get("startupCode") or ""
        if startup.strip():
            self.kernel.execute(startup, "block")

    def _on_state(self, state):
        if state == "busy" and self._prompt_visible:
            # hide the prompt but keep what the user typed
            pass
        if state == "dead":
            self._remove_prompt()
        self.stateChanged.emit(self, state)

    def _on_prompt(self, prompt):
        self._show_prompt(prompt)

    def _on_message(self, msg):
        if msg.get("type") == "clear":
            self.clear_screen()
        self.kernelMessage.emit(self, msg)

    def execute(self, code, mode="block", srcname="", lineoffset=0, echo_label=None):
        """Execute code from the editor (or a tool)."""
        if not self.kernel.is_alive:
            self.write("[No running R process. Restart the shell with Ctrl+K]\n", "info")
            return
        if echo_label:
            self._remove_prompt()
            self.write(echo_label + "\n", "info")
        else:
            self._remove_prompt()
        self.kernel.execute(code, mode, srcname, lineoffset)

    def interrupt(self):
        self.kernel.interrupt()

    def restart(self):
        self._remove_prompt()
        self.write("\n[Restarting R]\n", "info")
        self.kernel.restart()

    def terminate(self):
        self.kernel.terminate(wait=True)
        self.write("\n[R process terminated]\n", "info")

    # --------------------------------------------------------------- output --
    def _input_text(self):
        doc = self.document()
        if not self._prompt_visible:
            return ""
        c = QtGui.QTextCursor(doc)
        c.setPosition(self._input_start)
        c.movePosition(QtGui.QTextCursor.End, QtGui.QTextCursor.KeepAnchor)
        return c.selectedText().replace(" ", "\n")

    def _end_pos(self):
        return self.document().characterCount() - 1

    def _remove_prompt(self):
        """Remove prompt+input, returning the input text."""
        if not self._prompt_visible:
            return ""
        text = self._input_text()
        c = QtGui.QTextCursor(self.document())
        c.setPosition(self._prompt_start)
        c.movePosition(QtGui.QTextCursor.End, QtGui.QTextCursor.KeepAnchor)
        c.removeSelectedText()
        self._prompt_visible = False
        self._input_start = self._prompt_start = self._end_pos()
        return text

    def _show_prompt(self, prompt, text=""):
        if self._prompt_visible:
            text = self._remove_prompt() or text
        self._prompt = prompt
        c = QtGui.QTextCursor(self.document())
        c.movePosition(QtGui.QTextCursor.End)
        # prompts start on a fresh line
        if c.positionInBlock() > 0:
            c.insertText("\n", self._formats["out"])
        self._prompt_start = c.position()
        c.insertText(prompt, self._formats["prompt"])
        self._input_start = c.position()
        c.insertText(text, self._formats["input"])
        self._prompt_visible = True
        self.setTextCursor(c)
        self.setCurrentCharFormat(self._formats["input"])
        self.ensureCursorVisible()

    def write(self, text, kind="out"):
        """Insert output above the prompt/input region."""
        if not text:
            return
        text = ANSI_RE.sub("", text)
        if "\x0c" in text:
            self.clear_screen()
            text = text.split("\x0c")[-1]
        scrollbar = self.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        had_prompt = self._prompt_visible
        prompt = self._prompt
        user_cursor = self.textCursor()
        rel = user_cursor.position() - self._input_start if had_prompt else None
        pending = self._remove_prompt() if had_prompt else ""

        c = QtGui.QTextCursor(self.document())
        c.movePosition(QtGui.QTextCursor.End)
        fmt = self._formats.get(kind, self._formats["out"])
        # handle carriage returns (progress bars): overwrite the current line
        parts = text.split("\r")
        for k, part in enumerate(parts):
            if k > 0 and not part.startswith("\n"):
                c.movePosition(QtGui.QTextCursor.StartOfBlock, QtGui.QTextCursor.KeepAnchor)
                c.removeSelectedText()
            c.insertText(part, fmt)
        self._prompt_start = self._input_start = c.position()
        self._trim()
        if had_prompt:
            self._show_prompt(prompt, pending)
            if rel is not None and rel >= 0:
                c = self.textCursor()
                c.setPosition(min(self._input_start + rel, self._end_pos()))
                self.setTextCursor(c)
        else:
            c.movePosition(QtGui.QTextCursor.End)
            self.setTextCursor(c)
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def _trim(self):
        doc = self.document()
        excess = doc.characterCount() - MAX_CHARS
        if excess > 0:
            c = QtGui.QTextCursor(doc)
            c.setPosition(excess + 10000)
            c.movePosition(QtGui.QTextCursor.StartOfBlock)
            removed = c.position()
            c.setPosition(0, QtGui.QTextCursor.KeepAnchor)
            c.removeSelectedText()
            self._prompt_start -= removed
            self._input_start -= removed

    def clear_screen(self):
        prompt_visible = self._prompt_visible
        text = self._remove_prompt()
        self.clear()
        self._prompt_start = self._input_start = 0
        if prompt_visible:
            self._show_prompt(self._prompt, text)

    # ---------------------------------------------------------------- input --
    def _cursor_in_input(self):
        c = self.textCursor()
        return self._prompt_visible and c.selectionStart() >= self._input_start

    def _move_to_input_end(self):
        c = self.textCursor()
        c.movePosition(QtGui.QTextCursor.End)
        self.setTextCursor(c)

    def _set_input(self, text):
        if not self._prompt_visible:
            return
        c = QtGui.QTextCursor(self.document())
        c.setPosition(self._input_start)
        c.movePosition(QtGui.QTextCursor.End, QtGui.QTextCursor.KeepAnchor)
        c.insertText(text, self._formats["input"])
        self.setTextCursor(c)

    def keyPressEvent(self, event):
        key, mods, text = event.key(), event.modifiers(), event.text()
        ctrl = bool(mods & Qt.ControlModifier)
        popup = self._completer.popup()
        if popup.isVisible():
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                self._insert_completion(self._completer.currentCompletion())
                popup.hide()
                return
            if key == Qt.Key_Escape:
                popup.hide()
                return
            if key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown):
                QtWidgets.QApplication.sendEvent(popup, event)
                return

        # copy / interrupt
        if ctrl and key == Qt.Key_C:
            if self.textCursor().hasSelection():
                self.copy()
            else:
                self.interrupt()
            return
        if ctrl and key in (Qt.Key_A,):
            super().keyPressEvent(event)
            return
        if ctrl and key == Qt.Key_L:
            self.clear_screen()
            return

        busy = self.kernel.state == "busy"

        if key in (Qt.Key_Return, Qt.Key_Enter):
            if mods & Qt.ShiftModifier and self._prompt_visible:
                self._move_to_input_end()
                self.textCursor().insertText("\n")
                return
            self._submit()
            return

        if not self._prompt_visible and not busy:
            if text and not ctrl:
                return
            super().keyPressEvent(event)
            return

        if busy and not self._prompt_visible:
            # typing while R is busy: input for readline()/scan()
            self._show_input_line()

        if key == Qt.Key_Escape:
            self._set_input("")
            return
        if key == Qt.Key_Up and not ctrl and not self._input_text().count("\n"):
            self._history_step(-1)
            return
        if key == Qt.Key_Down and not ctrl and not self._input_text().count("\n"):
            self._history_step(1)
            return
        if key == Qt.Key_Tab:
            self._request_completion()
            return
        if key == Qt.Key_Home and not ctrl:
            c = self.textCursor()
            move = QtGui.QTextCursor.KeepAnchor if mods & Qt.ShiftModifier else QtGui.QTextCursor.MoveAnchor
            if c.position() >= self._input_start and c.block().position() <= self._input_start:
                c.setPosition(self._input_start, move)
            else:
                c.movePosition(QtGui.QTextCursor.StartOfBlock, move)
            self.setTextCursor(c)
            return
        if key == Qt.Key_Backspace or key == Qt.Key_Left:
            c = self.textCursor()
            if c.position() <= self._input_start and not c.hasSelection():
                return
        is_edit = bool(text) or key in (Qt.Key_Backspace, Qt.Key_Delete) or (
            ctrl and key in (Qt.Key_V, Qt.Key_X))
        if is_edit and not self._cursor_in_input():
            c = self.textCursor()
            if c.hasSelection() and c.selectionEnd() > self._input_start:
                c.setPosition(max(c.selectionStart(), self._input_start))
                c.setPosition(c.selectionEnd() if False else self._end_pos(), QtGui.QTextCursor.KeepAnchor)
            else:
                self._move_to_input_end()
        self._hist_prefix = None
        super().keyPressEvent(event)
        if text and self._prompt_visible:
            # keep the input format consistent
            pass

    def _show_input_line(self):
        """Show an input region (no prompt) while R waits on readline()."""
        c = QtGui.QTextCursor(self.document())
        c.movePosition(QtGui.QTextCursor.End)
        self._prompt = ""
        self._prompt_start = self._input_start = c.position()
        self._prompt_visible = True
        self.setTextCursor(c)
        self.setCurrentCharFormat(self._formats["input"])

    def insertFromMimeData(self, source):
        if not source.hasText():
            return
        if not self._prompt_visible and self.kernel.state == "busy":
            self._show_input_line()
        if not self._cursor_in_input():
            self._move_to_input_end()
        self.textCursor().insertText(source.text().replace("\r\n", "\n"), self._formats["input"])

    def _submit(self):
        if not self._prompt_visible:
            return
        text = self._input_text()
        state = self.kernel.state
        if state == "busy":
            # R echoes what it reads from stdin, so don't keep a local copy
            self._remove_prompt()
            self.kernel.write_stdin(text + "\n")
            return
        if state != "ready":
            return
        # freeze the input into the output area
        self._prompt_visible = False
        c = QtGui.QTextCursor(self.document())
        c.movePosition(QtGui.QTextCursor.End)
        c.insertText("\n", self._formats["input"])
        self._prompt_start = self._input_start = c.position()
        self.setTextCursor(c)
        if text.strip():
            self._add_history(text)
        self.kernel.execute(text, "line")
        self.executed.emit(text)

    def _add_history(self, text):
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._history = self._history[-1000:]
        self._hist_index = len(self._history)
        self.cfg.history = self._history

    def _history_step(self, step):
        if self._hist_prefix is None:
            self._hist_prefix = self._input_text()
            self._hist_index = len(self._history)
        i = self._hist_index
        while True:
            i += step
            if i < 0:
                return
            if i >= len(self._history):
                self._hist_index = len(self._history)
                self._set_input(self._hist_prefix)
                return
            if self._history[i].startswith(self._hist_prefix):
                break
        self._hist_index = i
        prefix = self._hist_prefix
        self._set_input(self._history[i])
        self._hist_prefix = prefix

    # ---------------------------------------------------------- completion --
    def _request_completion(self):
        c = self.textCursor()
        if c.position() < self._input_start:
            return
        line_before = self._input_text()[:c.position() - self._input_start].split("\n")[-1]

        def done(msg):
            items = msg.get("items") or []
            token = msg.get("token") or ""
            self._show_completions(token, items)
        self.kernel.complete(line_before, done)

    def _show_completions(self, token, items):
        if not items:
            return
        if len(items) == 1:
            self._completion_token = token
            self._insert_completion(items[0])
            return
        self._completion_token = token
        self._cmodel.setStringList(items[:400])
        self._completer.setCompletionPrefix(token)
        if self._completer.completionCount() == 0:
            self._completer.setCompletionPrefix("")
        rect = self.cursorRect()
        rect.setWidth(260)
        self._completer.popup().setCurrentIndex(self._completer.completionModel().index(0, 0))
        self._completer.complete(rect)

    def _insert_completion(self, completion):
        if not completion:
            return
        c = self.textCursor()
        n = len(self._completion_token)
        c.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.KeepAnchor, n)
        c.insertText(completion, self._formats["input"])
        self.setTextCursor(c)

    # ---------------------------------------------------------------- misc --
    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Clear screen", self.clear_screen)
        menu.addAction("Interrupt", self.interrupt)
        menu.addAction("Restart", self.restart)
        menu.exec(event.globalPos())

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            win = self.window()
            if hasattr(win, "zoom"):
                win.zoom(1 if event.angleDelta().y() > 0 else -1)
            return
        super().wheelEvent(event)

    def shutdown(self):
        self.kernel.terminate(wait=True)
