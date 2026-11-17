"""R language support: tokenizer, syntax highlighter, cell detection and
a light-weight parser for the source structure tool."""

import re

from PySide6 import QtGui

KEYWORDS = {
    "if", "else", "repeat", "while", "function", "for", "in", "next", "break",
    "return", "switch", "library", "require", "invisible", "stop", "warning",
    "tryCatch", "on.exit", "local",
}
CONSTANTS = {
    "TRUE", "FALSE", "NULL", "NA", "NA_integer_", "NA_real_", "NA_complex_",
    "NA_character_", "Inf", "NaN", "T", "F",
}

# Cell markers, as in Pyzo ("##"), Spyder/VS Code ("# %%") and RStudio
# sections ("# Section ----").
CELL_RE = re.compile(r"^\s*(##(?!#)|#\s*%%|#.*?(-{4,}|={4,}|#{4,})\s*$)")


def is_cell_line(text):
    return bool(CELL_RE.match(text)) and not text.lstrip().startswith("#'")


def cell_title(text):
    t = text.strip()
    t = re.sub(r"^#+\s*(%%)?\s*", "", t)
    t = re.sub(r"\s*[-=#]{4,}\s*$", "", t)
    return t.strip() or "(cell)"


NUMBER_RE = re.compile(
    r"0[xX][0-9a-fA-F]+[Li]?|(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?[Li]?")
IDENT_RE = re.compile(r"[A-Za-z_À-￿.][A-Za-z0-9_.À-￿]*")
OPERATOR_RE = re.compile(r"<<-|->>|<-|->|\|>|%[^%\n]*%|::?:?|[-+*/^~!&|=<>$@?]=?|:=")
RAW_START_RE = re.compile(r"[rR](['\"])(-*)([(\[{])")

# Block states for multi-line strings
S_NORMAL, S_DQ, S_SQ, S_BT = 0, 1, 2, 3
S_RAW_BASE = 100  # raw string: 100 + 10*dashes + bracket index, quote stored separately
_BRACKETS = "([{"
_CLOSE = {"(": ")", "[": "]", "{": "}"}


def tokenize(line, state=S_NORMAL):
    """Yield (start, length, kind) tokens for one line; return final state.

    kinds: comment, roxygen, cell, string, number, keyword, constant,
           function, operator, assign, backtick, ident
    """
    tokens = []
    i, n = 0, len(line)

    def end_of_string(start, quote):
        j = start
        while j < n:
            c = line[j]
            if c == "\\":
                j += 2
                continue
            if c == quote:
                return j + 1, True
            j += 1
        return n, False

    def end_of_raw(start, raw_state):
        code = raw_state - S_RAW_BASE
        quote = "'" if code >= 1000 else '"'
        code %= 1000
        dashes, br = divmod(code, 10)
        closing = _CLOSE[_BRACKETS[br]] + "-" * dashes + quote
        k = line.find(closing, start)
        if k < 0:
            return n, False
        return k + len(closing), True

    # continue a multi-line string from the previous line
    if state in (S_DQ, S_SQ, S_BT):
        quote = {S_DQ: '"', S_SQ: "'", S_BT: "`"}[state]
        j, closed = end_of_string(0, quote)
        tokens.append((0, j, "backtick" if state == S_BT else "string"))
        if not closed:
            return tokens, state
        i = j
    elif state >= S_RAW_BASE:
        j, closed = end_of_raw(0, state)
        tokens.append((0, j, "string"))
        if not closed:
            return tokens, state
        i = j

    while i < n:
        c = line[i]
        if c in " \t":
            i += 1
            continue
        if c == "#":
            rest = line[i:]
            if rest.startswith("#'"):
                kind = "roxygen"
            elif line[:i].strip() == "" and is_cell_line(line):
                kind = "cell"
            else:
                kind = "comment"
            tokens.append((i, n - i, kind))
            return tokens, S_NORMAL
        m = RAW_START_RE.match(line, i)
        if m and (i == 0 or not (line[i - 1].isalnum() or line[i - 1] in "._")):
            quote, dashes, br = m.group(1), len(m.group(2)), _BRACKETS.index(m.group(3))
            raw_state = S_RAW_BASE + (1000 if quote == "'" else 0) + dashes * 10 + br
            j, closed = end_of_raw(m.end(), raw_state)
            tokens.append((i, j - i, "string"))
            if not closed:
                return tokens, raw_state
            i = j
            continue
        if c in "\"'`":
            j, closed = end_of_string(i + 1, c)
            tokens.append((i, j - i, "backtick" if c == "`" else "string"))
            if not closed:
                return tokens, {'"': S_DQ, "'": S_SQ, "`": S_BT}[c]
            i = j
            continue
        if c.isdigit() or (c == "." and i + 1 < n and line[i + 1].isdigit()):
            m = NUMBER_RE.match(line, i)
            if m:
                tokens.append((i, m.end() - i, "number"))
                i = m.end()
                continue
        m = IDENT_RE.match(line, i)
        if m:
            word = m.group()
            j = m.end()
            if word in CONSTANTS:
                kind = "constant"
            elif word in KEYWORDS:
                kind = "keyword"
            else:
                k = j
                while k < n and line[k] in " \t":
                    k += 1
                kind = "function" if k < n and line[k] == "(" else "ident"
            tokens.append((i, j - i, kind))
            i = j
            continue
        m = OPERATOR_RE.match(line, i)
        if m:
            op = m.group()
            kind = "assign" if op in ("<-", "<<-", "->", "->>") else "operator"
            tokens.append((i, len(op), kind))
            i = m.end()
            continue
        i += 1
    return tokens, S_NORMAL


def cell_marker_lines(text):
    """Line numbers of cell separators that are at the top level.

    A separator-looking comment inside a function body (or any open bracket)
    does not start a cell, so running a cell never cuts code in half.
    """
    markers = []
    depth = 0
    state = S_NORMAL
    for lineno, line in enumerate(text.split("\n")):
        start_state = state
        tokens, state = tokenize(line, state)
        if start_state == S_NORMAL and depth == 0 and is_cell_line(line):
            markers.append(lineno)
            continue
        # count brackets outside strings and comments
        skip = [(s, s + n) for s, n, k in tokens
                if k in ("string", "comment", "roxygen", "cell", "backtick")]
        for i, c in enumerate(line):
            if c in "([{" or c in ")]}":
                if any(a <= i < b for a, b in skip):
                    continue
                depth = depth + 1 if c in "([{" else max(0, depth - 1)
    return markers


class RHighlighter(QtGui.QSyntaxHighlighter):
    def __init__(self, document, theme):
        super().__init__(document)
        self.set_theme(theme)

    def set_theme(self, theme):
        def fmt(color, bold=False, italic=False):
            f = QtGui.QTextCharFormat()
            f.setForeground(QtGui.QColor(color))
            if bold:
                f.setFontWeight(QtGui.QFont.Bold)
            if italic:
                f.setFontItalic(True)
            return f

        t = theme
        self.formats = {
            "comment": fmt(t["comment"], italic=True),
            "roxygen": fmt(t["roxygen"], italic=True),
            "cell": fmt(t["cell"], bold=True),
            "string": fmt(t["string"]),
            "number": fmt(t["number"]),
            "keyword": fmt(t["keyword"], bold=True),
            "constant": fmt(t["constant"], bold=True),
            "function": fmt(t["function"]),
            "operator": fmt(t["operator"]),
            "assign": fmt(t["assign"], bold=True),
            "backtick": fmt(t["backtick"]),
        }
        self.rehighlight()

    def highlightBlock(self, text):
        prev = self.previousBlockState()
        tokens, state = tokenize(text, prev if prev >= 0 else S_NORMAL)
        for start, length, kind in tokens:
            f = self.formats.get(kind)
            if f is not None:
                self.setFormat(start, length, f)
        self.setCurrentBlockState(state)


# --------------------------------------------------------------- structure --

ASSIGN_FUNC_RE = re.compile(
    r"^(\s*)([A-Za-z_.][A-Za-z0-9_.]*|`[^`]+`)\s*(<<?-|=)\s*(function\b|\\\s*\()")
S4_RE = re.compile(r"^(\s*)(setClass|setGeneric|setMethod|setRefClass|setValidity)\s*\(\s*[\"']([^\"']+)")
R6_RE = re.compile(r"^(\s*)([A-Za-z_.][A-Za-z0-9_.]*)\s*(<-|=)\s*(R6::)?R6Class\s*\(")
LIB_RE = re.compile(r"^\s*(library|require|requireNamespace)\s*\(\s*[\"']?([A-Za-z0-9.]+)")


class StructureItem:
    __slots__ = ("kind", "name", "line", "indent", "children")

    def __init__(self, kind, name, line, indent):
        self.kind, self.name, self.line, self.indent = kind, name, line, indent
        self.children = []


def parse_structure(text):
    """Return a list of top-level StructureItems (cells contain the rest)."""
    root = []
    cell = None
    stack = []  # (indent, item) of function definitions
    state = S_NORMAL
    markers = set(cell_marker_lines(text))
    for lineno, line in enumerate(text.split("\n")):
        in_string = state != S_NORMAL
        _, state = tokenize(line, state)
        if in_string:
            continue
        if lineno in markers:
            cell = StructureItem("cell", cell_title(line), lineno, 0)
            root.append(cell)
            stack = []
            continue
        item = None
        m = ASSIGN_FUNC_RE.match(line)
        if m:
            item = StructureItem("function", m.group(2).strip("`"), lineno, len(m.group(1)))
        else:
            m = R6_RE.match(line)
            if m:
                item = StructureItem("class", m.group(2), lineno, len(m.group(1)))
            else:
                m = S4_RE.match(line)
                if m:
                    kind = "class" if m.group(2) in ("setClass", "setRefClass") else "method"
                    item = StructureItem(kind, f"{m.group(3)}  [{m.group(2)}]", lineno,
                                         len(m.group(1)))
                else:
                    m = LIB_RE.match(line)
                    if m:
                        item = StructureItem("import", m.group(2), lineno, 0)
        if item is None:
            continue
        while stack and stack[-1][0] >= item.indent:
            stack.pop()
        if stack:
            stack[-1][1].children.append(item)
        elif cell is not None:
            cell.children.append(item)
        else:
            root.append(item)
        if item.kind in ("function", "class"):
            stack.append((item.indent, item))
    return root
