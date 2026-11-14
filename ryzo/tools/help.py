"""Interactive help tool: shows R documentation, optionally following the editor cursor."""

import re

from PySide6 import QtCore, QtGui, QtWidgets

from ryzo.config import get_config

WELCOME = """
<h3>Ryzo help</h3>
<p>Type a topic above and press Enter, or use <code>?topic</code> /
<code>help(topic)</code> in the shell.</p>
<p>With <i>follow cursor</i> enabled the help for the function under the
editor's cursor is shown automatically.</p>
<p>Shift+F1 shows the help for the word under the cursor.</p>
"""

STYLE = """
<style>
body { font-family: sans-serif; }
h2 { font-size: 15pt; margin-top: 2px; }
h3 { font-size: 12pt; margin-bottom: 2px; }
pre { background: rgba(127,127,127,0.12); padding: 4px; }
code { font-family: monospace; }
table { border-collapse: collapse; }
td { padding: 2px 6px; vertical-align: top; }
</style>
"""


class HelpTool(QtWidgets.QWidget):
    title = "Interactive help"

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.cfg = get_config()
        self._history = []
        self._pos = -1
        self._pending_cursor_topic = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        row = QtWidgets.QHBoxLayout()
        style = self.style()
        self.back = QtWidgets.QToolButton()
        self.back.setIcon(style.standardIcon(QtWidgets.QStyle.SP_ArrowBack))
        self.back.clicked.connect(lambda: self._step(-1))
        self.fwd = QtWidgets.QToolButton()
        self.fwd.setIcon(style.standardIcon(QtWidgets.QStyle.SP_ArrowForward))
        self.fwd.clicked.connect(lambda: self._step(1))
        self.topic = QtWidgets.QLineEdit()
        self.topic.setPlaceholderText("help topic, e.g. lm or stats::lm")
        self.topic.returnPressed.connect(lambda: self.show_help(self.topic.text().strip()))
        self.follow = QtWidgets.QCheckBox("follow cursor")
        self.follow.setChecked(self.cfg.helpFollowsCursor)
        self.follow.toggled.connect(lambda v: self.cfg.__setitem__("helpFollowsCursor", v))
        row.addWidget(self.back)
        row.addWidget(self.fwd)
        row.addWidget(self.topic, 1)
        row.addWidget(self.follow)
        layout.addLayout(row)
        self.browser = QtWidgets.QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._link)
        layout.addWidget(self.browser)
        self.browser.setHtml(STYLE + WELCOME)
        self._update_buttons()

        self._cursor_timer = QtCore.QTimer(self, singleShot=True, interval=700)
        self._cursor_timer.timeout.connect(self._help_from_cursor)

    def show_help(self, topic, add_history=True):
        if not topic:
            return
        pkg = ""
        m = re.match(r"^([A-Za-z.][A-Za-z0-9.]*):::?(.+)$", topic)
        if m:
            pkg, topic = m.group(1), m.group(2)
        shell = self.main.current_shell()
        if shell is None or not shell.kernel.help(topic, pkg):
            self.browser.setHtml(STYLE + "<p><i>Help needs an idle R shell.</i></p>")
            return
        self._requested = (topic, pkg, add_history)
        self._from_cursor = False

    def on_message(self, shell, msg):
        if msg.get("type") == "help":
            self._display(msg)
        elif msg.get("type") == "pager":
            text = QtGui.QTextDocumentFragment.fromPlainText(msg.get("text", "")).toHtml()
            self.browser.setHtml(text)
            self.main.show_tool(self)

    def _display(self, msg):
        from_cursor = getattr(self, "_from_cursor", False)
        self._from_cursor = False
        if msg.get("error"):
            if not from_cursor:
                self.browser.setHtml(STYLE + f"<p>{msg['error']}</p>")
            return
        html = msg.get("html", "")
        html = re.sub(r"<link[^>]*>", "", html)
        html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
        html = html.replace("<head>", "<head>" + STYLE, 1)
        topic = msg.get("topic", "")
        self.browser.setHtml(html)
        self.topic.setText(topic)
        if not self._history or self._history[self._pos] != topic:
            self._history = self._history[:self._pos + 1] + [topic]
            self._pos = len(self._history) - 1
        self._update_buttons()
        if not from_cursor:
            self.main.show_tool(self)

    def _link(self, url):
        s = url.toString()
        if s.startswith(("http://", "https://", "mailto:")):
            QtGui.QDesktopServices.openUrl(url)
            return
        # dynamic help links look like ../../pkg/help/topic or ../help/topic
        parts = [p for p in s.split("/") if p not in ("..", ".", "")]
        if "help" in parts:
            i = parts.index("help")
            topic = "/".join(parts[i + 1:])
            pkg = parts[i - 1] if i > 0 else ""
            topic = QtCore.QUrl.fromPercentEncoding(topic.encode())
            self.show_help(f"{pkg}::{topic}" if pkg else topic)
        elif parts:
            topic = re.sub(r"\.html$", "", parts[-1])
            self.show_help(topic)

    def _step(self, d):
        new = self._pos + d
        if 0 <= new < len(self._history):
            self._pos = new
            self.show_help(self._history[new], add_history=False)
            self._update_buttons()

    def _update_buttons(self):
        self.back.setEnabled(self._pos > 0)
        self.fwd.setEnabled(self._pos < len(self._history) - 1)

    # ----------------------------------------------------- follow the cursor --
    def editor_cursor_moved(self, editor):
        if self.follow.isChecked() and self.isVisible():
            self._pending_cursor_topic = editor
            self._cursor_timer.start()

    def _help_from_cursor(self):
        ed = self._pending_cursor_topic
        if ed is None:
            return
        try:
            word = ed.word_under_cursor()
        except RuntimeError:
            return
        if not word or len(word) < 2 or word == self.topic.text():
            return
        shell = self.main.current_shell()
        if shell is None or shell.kernel.state != "ready":
            return
        pkg, topic = "", word
        if "::" in word:
            pkg, topic = word.split("::", 1)
            topic = topic.lstrip(":")
        if shell.kernel.help(topic, pkg):
            self._from_cursor = True
