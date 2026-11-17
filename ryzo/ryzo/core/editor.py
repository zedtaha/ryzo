"""The code editor: a QPlainTextEdit with R-specific conveniences."""

import os
import re

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ryzo.config import get_config
from ryzo.core.rsyntax import RHighlighter, cell_marker_lines
from ryzo.core.themes import get_theme

OPEN_BRACKETS = {"(": ")", "[": "]", "{": "}"}
CLOSE_BRACKETS = {v: k for k, v in OPEN_BRACKETS.items()}
WORD_RE = re.compile(r"[A-Za-z_.][A-Za-z0-9_.]*")
CONTINUATION_RE = re.compile(r"(%[^%]*%|\|>|\+|-|\*|/|&|\||,|<-|=|\(|\[|\{|~)\s*(#.*)?$")


def default_font():
    cfg = get_config()
    family = cfg.font.get("family") or ""
    font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
    if family:
        font.setFamily(family)
    font.setPointSize(max(5, int(cfg.font.get("size", 10)) + int(cfg.zoom)))
    font.setStyleHint(QtGui.QFont.Monospace)
    return font


class LineNumberArea(QtWidgets.QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QtCore.QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)

    def mousePressEvent(self, event):
        # click selects the line, like most editors
        cursor = self.editor.cursorForPosition(QtCore.QPoint(0, int(event.position().y())))
        cursor.movePosition(QtGui.QTextCursor.StartOfBlock)
        cursor.movePosition(QtGui.QTextCursor.EndOfBlock, QtGui.QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cursor)


class CodeEditor(QtWidgets.QPlainTextEdit):
    """Base editor used for R files. Also serves as the base of the shell look."""

    modifiedChanged = QtCore.Signal(bool)
    completionRequested = QtCore.Signal(object, str)  # editor, line text up to cursor
    calltipRequested = QtCore.Signal(object, str)  # editor, function name

    def __init__(self, parent=None, filename=None):
        super().__init__(parent)
        self.cfg = get_config()
        self.filename = filename
        self.encoding = "utf-8"
        self.line_ending = "\n"
        self.mtime = None
        self.theme = get_theme(self.cfg.theme)
        self._line_numbers = LineNumberArea(self)
        self._extra = {}  # name -> list of ExtraSelection
        self._completer = None
        self._completion_prefix = ""

        self.setFont(default_font())
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth if self.cfg.wrap
                             else QtWidgets.QPlainTextEdit.NoWrap)
        self.setCenterOnScroll(False)
        self.highlighter = RHighlighter(self.document(), self.theme)
        self.apply_theme(self.theme)
        self.set_show_whitespace(self.cfg.showWhitespace)

        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self.document().modificationChanged.connect(self.modifiedChanged)
        self._update_margin()
        self._on_cursor_moved()

        self._init_completer()

    # ---------------------------------------------------------- appearance --
    def apply_theme(self, theme):
        self.theme = theme
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Base, QtGui.QColor(theme["background"]))
        pal.setColor(QtGui.QPalette.Text, QtGui.QColor(theme["foreground"]))
        pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(theme["selection"]))
        pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(theme["foreground"]))
        self.setPalette(pal)
        self.highlighter.set_theme(theme)
        self._on_cursor_moved()
        self.viewport().update()

    def set_font_zoom(self):
        self.setFont(default_font())
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * self.cfg.indentWidth)
        self._update_margin()

    def set_wrap(self, wrap):
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth if wrap
                             else QtWidgets.QPlainTextEdit.NoWrap)

    def set_show_whitespace(self, show):
        opt = self.document().defaultTextOption()
        flags = opt.flags()
        if show:
            flags |= QtGui.QTextOption.ShowTabsAndSpaces
        else:
            flags &= ~QtGui.QTextOption.ShowTabsAndSpaces
        opt.setFlags(flags)
        self.document().setDefaultTextOption(opt)

    # ---------------------------------------------------------- line numbers --
    def line_number_width(self):
        if not self.cfg.showLineNumbers:
            return 6
        digits = len(str(max(1, self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * max(3, digits)

    def _update_margin(self, *_):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _on_update_request(self, rect, dy):
        if dy:
            self._line_numbers.scroll(0, dy)
        else:
            self._line_numbers.update(0, rect.y(), self._line_numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_numbers.setGeometry(QtCore.QRect(cr.left(), cr.top(),
                                                    self.line_number_width(), cr.height()))

    def paint_line_numbers(self, event):
        painter = QtGui.QPainter(self._line_numbers)
        painter.fillRect(event.rect(), QtGui.QColor(self.theme["gutter_bg"]))
        if not self.cfg.showLineNumbers:
            return
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        normal = QtGui.QColor(self.theme["gutter_fg"])
        active = QtGui.QColor(self.theme["foreground"])
        width = self._line_numbers.width() - 6
        h = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(active if number == current else normal)
                painter.drawText(0, top, width, h, Qt.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    # ------------------------------------------------------ viewport painting --
    def paintEvent(self, event):
        painter = QtGui.QPainter(self.viewport())
        fm = self.fontMetrics()
        offset = self.contentOffset()
        char_w = fm.horizontalAdvance(" ")
        # long line indicator
        col = self.cfg.longLineIndicator
        if col and col > 0:
            x = round(offset.x() + self.document().documentMargin() + col * char_w)
            painter.setPen(QtGui.QColor(self.theme["long_line"]))
            painter.drawLine(x, 0, x, self.viewport().height())
        # indentation guides and cell separators
        block = self.firstVisibleBlock()
        indent_w = self.cfg.indentWidth
        guide = QtGui.QPen(QtGui.QColor(self.theme["indent_guide"]))
        cellpen = QtGui.QPen(QtGui.QColor(self.theme["cell_line"]))
        cellpen.setWidth(1)
        margin = self.document().documentMargin()
        markers = self.cell_markers()
        last_indent = 0
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(offset)
            if geo.top() > event.rect().bottom():
                break
            text = block.text()
            if self.cfg.showIndentGuides:
                stripped = text.lstrip(" ")
                indent = len(text) - len(stripped) if stripped else last_indent
                last_indent = indent
                painter.setPen(guide)
                for level in range(indent_w, indent, indent_w):
                    x = round(offset.x() + margin + level * char_w)
                    painter.drawLine(x, round(geo.top()), x, round(geo.bottom()))
            if block.blockNumber() in markers:
                painter.setPen(cellpen)
                y = round(geo.top())
                painter.drawLine(0, y, self.viewport().width(), y)
            block = block.next()
        painter.end()
        super().paintEvent(event)

    # ----------------------------------------------------- extra selections --
    def set_extra(self, name, selections):
        self._extra[name] = selections
        allsel = []
        for key in ("line", "cell", "find", "brace"):
            allsel.extend(self._extra.get(key, []))
        self.setExtraSelections(allsel)

    def _on_cursor_moved(self):
        sels = []
        if self.cfg.highlightCurrentLine and not self.isReadOnly():
            sel = QtWidgets.QTextEdit.ExtraSelection()
            sel.format.setBackground(QtGui.QColor(self.theme["current_line"]))
            sel.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            sels.append(sel)
        self.set_extra("line", sels)
        self._match_braces()
        self._line_numbers.update()

    def _match_braces(self):
        cursor = self.textCursor()
        doc = self.document()
        pos = cursor.position()
        sels = []
        for p in (pos - 1, pos):
            ch = doc.characterAt(p)
            if ch in OPEN_BRACKETS or ch in CLOSE_BRACKETS:
                other = self._find_matching(p, ch)
                color = self.theme["brace_match"] if other is not None else self.theme["brace_bad"]
                for q in (p, other):
                    if q is None:
                        continue
                    sel = QtWidgets.QTextEdit.ExtraSelection()
                    sel.format.setBackground(QtGui.QColor(color))
                    c = QtGui.QTextCursor(doc)
                    c.setPosition(q)
                    c.setPosition(q + 1, QtGui.QTextCursor.KeepAnchor)
                    sel.cursor = c
                    sels.append(sel)
                break
        self.set_extra("brace", sels)

    def _find_matching(self, pos, ch):
        doc = self.document()
        text = doc.toPlainText()
        if ch in OPEN_BRACKETS:
            target, rng = OPEN_BRACKETS[ch], range(pos + 1, min(len(text), pos + 50000))
        else:
            target, rng = CLOSE_BRACKETS[ch], range(pos - 1, max(-1, pos - 50000), -1)
        depth = 0
        for i in rng:
            c = text[i]
            if c == ch:
                depth += 1
            elif c == target:
                if depth == 0:
                    return i
                depth -= 1
        return None

    # --------------------------------------------------------------- editing --
    def indent_str(self):
        return " " * self.cfg.indentWidth

    def selected_blocks(self):
        cursor = self.textCursor()
        doc = self.document()
        start = doc.findBlock(cursor.selectionStart())
        end = doc.findBlock(cursor.selectionEnd())
        if cursor.hasSelection() and end.position() == cursor.selectionEnd() and end != start:
            end = end.previous()
        blocks = []
        b = start
        while b.isValid():
            blocks.append(b)
            if b == end:
                break
            b = b.next()
        return blocks

    def _edit_blocks(self, func):
        blocks = self.selected_blocks()
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for b in blocks:
            func(b)
        cursor.endEditBlock()
        # select the full lines that were changed
        if len(blocks) > 1:
            c = self.textCursor()
            c.setPosition(blocks[0].position())
            c.setPosition(blocks[-1].position() + blocks[-1].length() - 1,
                          QtGui.QTextCursor.KeepAnchor)
            self.setTextCursor(c)

    def indent_selection(self):
        ind = self.indent_str()

        def f(b):
            c = QtGui.QTextCursor(b)
            c.insertText(ind)
        self._edit_blocks(f)

    def dedent_selection(self):
        n = self.cfg.indentWidth

        def f(b):
            text = b.text()
            remove = len(text) - len(text.lstrip(" "))
            remove = min(remove, n) if remove else (1 if text.startswith("\t") else 0)
            if remove:
                c = QtGui.QTextCursor(b)
                c.setPosition(b.position() + remove, QtGui.QTextCursor.KeepAnchor)
                c.removeSelectedText()
        self._edit_blocks(f)

    def comment_selection(self):
        blocks = self.selected_blocks()
        texts = [b.text() for b in blocks if b.text().strip()]
        col = min((len(t) - len(t.lstrip()) for t in texts), default=0)

        def f(b):
            if b.text().strip() or len(blocks) == 1:
                c = QtGui.QTextCursor(b)
                c.setPosition(b.position() + min(col, len(b.text())))
                c.insertText("# ")
        self._edit_blocks(f)

    def uncomment_selection(self):
        def f(b):
            text = b.text()
            stripped = text.lstrip()
            if stripped.startswith("#"):
                start = len(text) - len(stripped)
                n = 2 if stripped.startswith("# ") else 1
                c = QtGui.QTextCursor(b)
                c.setPosition(b.position() + start)
                c.setPosition(b.position() + start + n, QtGui.QTextCursor.KeepAnchor)
                c.removeSelectedText()
        self._edit_blocks(f)

    def toggle_comment(self):
        blocks = [b for b in self.selected_blocks() if b.text().strip()]
        if blocks and all(b.text().lstrip().startswith("#") for b in blocks):
            self.uncomment_selection()
        else:
            self.comment_selection()

    def duplicate_lines(self):
        blocks = self.selected_blocks()
        text = "\n".join(b.text() for b in blocks)
        c = QtGui.QTextCursor(blocks[-1])
        c.movePosition(QtGui.QTextCursor.EndOfBlock)
        c.insertText("\n" + text)

    def delete_lines(self):
        blocks = self.selected_blocks()
        c = QtGui.QTextCursor(blocks[0])
        c.beginEditBlock()
        start = blocks[0].position()
        end = blocks[-1].position() + blocks[-1].length()
        if end > self.document().characterCount() - 1:
            end = self.document().characterCount() - 1
            start = max(0, start - 1)
        c.setPosition(start)
        c.setPosition(end, QtGui.QTextCursor.KeepAnchor)
        c.removeSelectedText()
        c.endEditBlock()

    def go_to_line(self, lineno, select=False):
        block = self.document().findBlockByNumber(max(0, lineno))
        if not block.isValid():
            return
        c = QtGui.QTextCursor(block)
        if select:
            c.movePosition(QtGui.QTextCursor.EndOfBlock, QtGui.QTextCursor.KeepAnchor)
        self.setTextCursor(c)
        self.centerCursor()
        self.setFocus()

    def word_under_cursor(self):
        """The R identifier (incl. pkg::name) at the cursor."""
        cursor = self.textCursor()
        text = cursor.block().text()
        col = cursor.positionInBlock()
        for m in re.finditer(r"[A-Za-z_.][A-Za-z0-9_.]*(:::?[A-Za-z_.][A-Za-z0-9_.]*)?", text):
            if m.start() <= col <= m.end():
                return m.group()
        return ""

    # ---------------------------------------------------------------- cells --
    def cell_markers(self):
        """Set of block numbers that start a cell (cached per document revision)."""
        rev = self.document().revision()
        cache = getattr(self, "_cell_cache", None)
        if cache is None or cache[0] != rev:
            cache = (rev, set(cell_marker_lines(self.toPlainText())))
            self._cell_cache = cache
        return cache[1]

    def cell_range(self, block=None):
        """Return (first_block, last_block) of the cell containing the cursor."""
        if block is None:
            block = self.textCursor().block()
        markers = self.cell_markers()
        n = block.blockNumber()
        first = max((m for m in markers if m <= n), default=0)
        nxt = min((m for m in markers if m > n), default=self.blockCount())
        doc = self.document()
        return doc.findBlockByNumber(first), doc.findBlockByNumber(nxt - 1)

    def cell_text(self):
        start, end = self.cell_range()
        lines = []
        b = start
        while b.isValid():
            lines.append(b.text())
            if b == end:
                break
            b = b.next()
        return "\n".join(lines), start.blockNumber(), end

    # ---------------------------------------------------------------- keys --
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        text = event.text()
        cursor = self.textCursor()
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

        if key == Qt.Key_Escape:
            QtWidgets.QToolTip.hideText()

        if key == Qt.Key_Tab and not mods & (Qt.ControlModifier | Qt.AltModifier):
            if cursor.hasSelection() and cursor.block() != self.document().findBlock(
                    cursor.selectionEnd()) or "\n" in cursor.selectedText().replace(" ", "\n"):
                self.indent_selection()
            else:
                col = cursor.positionInBlock()
                n = self.cfg.indentWidth - (col % self.cfg.indentWidth)
                cursor.insertText(" " * n)
            return
        if key == Qt.Key_Backtab:
            self.dedent_selection()
            return

        if key in (Qt.Key_Return, Qt.Key_Enter) and not mods & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier):
            self._newline_with_indent()
            return

        if key == Qt.Key_Backspace and not cursor.hasSelection() and not mods:
            # backspace removes a whole indent level inside leading whitespace
            col = cursor.positionInBlock()
            before = cursor.block().text()[:col]
            if col and before.strip() == "" and before.endswith(" "):
                n = (col - 1) % self.cfg.indentWidth + 1
                cursor.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.KeepAnchor, n)
                cursor.removeSelectedText()
                return
            # remove auto-closed pair
            doc = self.document()
            prev_ch, next_ch = doc.characterAt(cursor.position() - 1), doc.characterAt(cursor.position())
            if self.cfg.autoClose and (OPEN_BRACKETS.get(prev_ch) == next_ch or
                                       (prev_ch in "\"'`" and prev_ch == next_ch)):
                cursor.deleteChar()

        if self.cfg.autoClose and text and not mods & Qt.ControlModifier:
            if self._auto_close(text, cursor):
                return

        if text == "}" and cursor.block().text().strip() == "":
            # dedent a lone closing brace
            line = cursor.block().text()
            if len(line) >= self.cfg.indentWidth and cursor.positionInBlock() == len(line):
                cursor.movePosition(QtGui.QTextCursor.StartOfBlock)
                cursor.movePosition(QtGui.QTextCursor.EndOfBlock, QtGui.QTextCursor.KeepAnchor)
                cursor.insertText(line[:-self.cfg.indentWidth] if line.endswith(self.indent_str()) else line)

        super().keyPressEvent(event)
        self._after_key(text)

    def _auto_close(self, text, cursor):
        doc = self.document()
        next_ch = doc.characterAt(cursor.position())
        if text in CLOSE_BRACKETS or text in "\"'`":
            if next_ch == text and not cursor.hasSelection():
                if text not in "\"'`" or self._inside_string_end(cursor):
                    cursor.movePosition(QtGui.QTextCursor.Right)
                    self.setTextCursor(cursor)
                    return True
        if text in OPEN_BRACKETS or text in "\"'`":
            if cursor.hasSelection():
                sel = cursor.selectedText()
                close = OPEN_BRACKETS.get(text, text)
                cursor.insertText(text + sel + close)
                return True
            if next_ch and not next_ch.isspace() and next_ch not in ")]},;":
                return False
            if text in "\"'`":
                prev_ch = doc.characterAt(cursor.position() - 1)
                if prev_ch.isalnum() or prev_ch == text:
                    return False
                line_before = cursor.block().text()[:cursor.positionInBlock()]
                if "#" in line_before and line_before.count('"') % 2 == 0:
                    return False
            close = OPEN_BRACKETS.get(text, text)
            cursor.insertText(text + close)
            cursor.movePosition(QtGui.QTextCursor.Left)
            self.setTextCursor(cursor)
            self._after_key(text)
            return True
        return False

    def _inside_string_end(self, cursor):
        line = cursor.block().text()[:cursor.positionInBlock()]
        return True if line else False

    def _newline_with_indent(self):
        cursor = self.textCursor()
        line = cursor.block().text()
        col = cursor.positionInBlock()
        before = line[:col]
        after = line[col:]
        indent = before[:len(before) - len(before.lstrip())]
        stripped = before.rstrip()
        extra = ""
        if stripped.endswith(("{", "(", "[")):
            extra = self.indent_str()
        elif CONTINUATION_RE.search(stripped) and not stripped.lstrip().startswith("#"):
            # continuation of a pipe chain / argument list
            prev = cursor.block().previous()
            if not (prev.isValid() and CONTINUATION_RE.search(prev.text().rstrip())):
                extra = self.indent_str()
        cursor.beginEditBlock()
        # strip trailing whitespace on the line being left
        if after.strip() == "" and before != before.rstrip():
            cursor.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.KeepAnchor,
                                len(before) - len(before.rstrip()))
            cursor.removeSelectedText()
        if after.lstrip().startswith(("}", ")", "]")) and extra:
            cursor.insertText("\n" + indent + extra + "\n" + indent)
            cursor.movePosition(QtGui.QTextCursor.Up)
            cursor.movePosition(QtGui.QTextCursor.EndOfBlock)
            # remove the leading whitespace of the closing line
            nxt = cursor.block().next()
            c2 = QtGui.QTextCursor(nxt)
            c2.movePosition(QtGui.QTextCursor.StartOfBlock)
            lead = len(nxt.text()) - len(nxt.text().lstrip())
            c2.setPosition(nxt.position() + lead, QtGui.QTextCursor.KeepAnchor)
            c2.insertText(indent)
        else:
            cursor.insertText("\n" + indent + extra)
            # remove spaces that were after the cursor
            c2 = QtGui.QTextCursor(cursor)
            lead = len(after) - len(after.lstrip(" "))
            if lead:
                c2.setPosition(cursor.position() + lead, QtGui.QTextCursor.KeepAnchor)
                c2.removeSelectedText()
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    # ---------------------------------------------------- completion/calltips --
    def _init_completer(self):
        self._completer = QtWidgets.QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setModelSorting(QtWidgets.QCompleter.UnsortedModel)
        self._completer.setMaxVisibleItems(12)
        self._model = QtCore.QStringListModel(self)
        self._completer.setModel(self._model)
        self._completer.activated.connect(self._insert_completion)
        self._completer.popup().setFont(self.font())

    def _line_before_cursor(self):
        c = self.textCursor()
        return c.block().text()[:c.positionInBlock()]

    def _after_key(self, text):
        if not text:
            return
        line = self._line_before_cursor()
        if self.cfg.calltips and text == "(":
            m = re.search(r"([A-Za-z_.][A-Za-z0-9_.]*(:::?[A-Za-z_.][A-Za-z0-9_.]*)?)\s*\($", line)
            if m:
                self.calltipRequested.emit(self, m.group(1))
        elif text == ")":
            QtWidgets.QToolTip.hideText()
        if not self.cfg.autoComplete:
            return
        popup = self._completer.popup()
        m = re.search(r"([A-Za-z_.][A-Za-z0-9_.]*(\$|@|:::?)?[A-Za-z0-9_.]*)$", line)
        token = m.group(1) if m else ""
        trigger = token.endswith(("$", "@", "::"))
        if (len(token) >= self.cfg.autoCompleteMinChars or trigger) and not self._in_comment_or_string(line):
            self.request_completion(line)
        elif popup.isVisible():
            popup.hide()

    def _in_comment_or_string(self, line):
        from ryzo.core.rsyntax import tokenize
        tokens, state = tokenize(line, self._block_state_before())
        if state != 0:
            return True
        if tokens:
            start, length, kind = tokens[-1]
            if kind in ("comment", "roxygen", "cell") or (
                    kind == "string" and start + length >= len(line)):
                return True
        return False

    def _block_state_before(self):
        prev = self.textCursor().block().previous()
        s = prev.userState() if prev.isValid() else 0
        return s if s >= 0 else 0

    def request_completion(self, line=None):
        if line is None:
            line = self._line_before_cursor()
        self.completionRequested.emit(self, line)

    def buffer_words(self, prefix):
        words = set(WORD_RE.findall(self.toPlainText()))
        words.discard(prefix)
        low = prefix.lower()
        return sorted(w for w in words if w.lower().startswith(low) and len(w) > 2)

    def show_completions(self, token, items):
        """Called by whoever handles completionRequested."""
        line = self._line_before_cursor()
        if not line.endswith(token) or not items:
            self._completer.popup().hide()
            return
        if len(items) == 1 and items[0] == token:
            self._completer.popup().hide()
            return
        self._completion_prefix = token
        self._model.setStringList(items[:400])
        self._completer.setCompletionPrefix(token)
        if self._completer.completionCount() == 0:
            self._completer.setCompletionPrefix("")
        popup = self._completer.popup()
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        fm = self.fontMetrics()
        rect.translate(self.viewportMargins().left() - fm.horizontalAdvance(token), 0)
        width = min(500, max(180, max(fm.horizontalAdvance(s) for s in items[:200]) + 40))
        rect.setWidth(width)
        self._completer.complete(rect)

    def _insert_completion(self, completion):
        if not completion:
            return
        cursor = self.textCursor()
        prefix = self._completion_prefix
        cursor.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.KeepAnchor, len(prefix))
        cursor.insertText(completion)
        self.setTextCursor(cursor)

    def show_calltip(self, tip):
        if not tip:
            return
        rect = self.cursorRect()
        pos = self.viewport().mapToGlobal(QtCore.QPoint(rect.left(), rect.top() - self.fontMetrics().height() - 10))
        if len(tip) > 300:
            tip = tip[:297] + "..."
        QtWidgets.QToolTip.showText(pos, tip, self)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            win = self.window()
            if hasattr(win, "zoom"):
                win.zoom(1 if event.angleDelta().y() > 0 else -1)
            return
        super().wheelEvent(event)

    # -------------------------------------------------------------- file I/O --
    @property
    def name(self):
        return os.path.basename(self.filename) if self.filename else getattr(self, "_tmpname", "<new>")

    def load(self, filename):
        with open(filename, "rb") as f:
            raw = f.read()
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = raw.decode(enc)
                self.encoding = "utf-8" if enc == "utf-8-sig" else enc
                break
            except UnicodeDecodeError:
                continue
        if "\r\n" in text:
            self.line_ending = "\r\n"
        elif "\r" in text:
            self.line_ending = "\r"
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.setPlainText(text)
        self.filename = os.path.abspath(filename)
        self.document().setModified(False)
        self.mtime = os.path.getmtime(self.filename)

    def save(self, filename=None):
        filename = filename or self.filename
        text = self.toPlainText()
        if text and not text.endswith("\n"):
            text += "\n"
        data = text.replace("\n", self.line_ending).encode(self.encoding)
        with open(filename, "wb") as f:
            f.write(data)
        self.filename = os.path.abspath(filename)
        self.document().setModified(False)
        self.mtime = os.path.getmtime(self.filename)
