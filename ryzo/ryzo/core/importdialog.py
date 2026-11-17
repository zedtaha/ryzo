"""Import Dataset dialog, modelled after RStudio's.

The preview is produced by R itself (the generated code is run with a row
limit), so what you see is exactly what the import will give.
"""

import csv
import html
import os
import re

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ryzo.core.editor import default_font

PREVIEW_ROWS = 50

# key: (menu label, required package, file dialog filter)
FORMATS = {
    "text_base": ("From Text (base)", None,
                  "Text files (*.csv *.tsv *.txt *.dat *.tab *.csv.gz);;All files (*)"),
    "text_readr": ("From Text (readr)", "readr",
                   "Text files (*.csv *.tsv *.txt *.dat *.tab *.csv.gz);;All files (*)"),
    "text_fread": ("From Text (data.table)", "data.table",
                   "Text files (*.csv *.tsv *.txt *.dat *.tab *.csv.gz);;All files (*)"),
    "excel": ("From Excel", "readxl", "Excel files (*.xlsx *.xls *.xlsm);;All files (*)"),
    "spss": ("From SPSS", "haven", "SPSS files (*.sav *.zsav *.por);;All files (*)"),
    "sas": ("From SAS", "haven", "SAS files (*.sas7bdat *.xpt);;All files (*)"),
    "stata": ("From Stata", "haven", "Stata files (*.dta);;All files (*)"),
    "json": ("From JSON", "jsonlite", "JSON files (*.json);;All files (*)"),
    "rds": ("From RDS / RData", None, "R data (*.rds *.RDS *.RData *.rdata *.rda);;All files (*)"),
}
PACKAGES = sorted({p for _, p, _ in FORMATS.values() if p})

EXTENSIONS = {
    ".csv": "text_base", ".tsv": "text_base", ".txt": "text_base", ".dat": "text_base",
    ".tab": "text_base", ".gz": "text_base",
    ".xlsx": "excel", ".xls": "excel", ".xlsm": "excel",
    ".sav": "spss", ".zsav": "spss", ".por": "spss",
    ".sas7bdat": "sas", ".xpt": "sas", ".dta": "stata", ".json": "json",
    ".rds": "rds", ".rdata": "rds", ".rda": "rds",
}

DELIMITERS = [("Comma", ","), ("Semicolon", ";"), ("Tab", "\t"), ("Whitespace", ""),
              ("Pipe", "|"), ("Other...", None)]


def format_for_path(path):
    ext = os.path.splitext(path.lower())[1]
    return EXTENSIONS.get(ext)


def rstr(s):
    """R string literal."""
    s = s.replace("\\", "/") if re.match(r"^[A-Za-z]:\\", s) else s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t") + '"'


def rvec(values):
    if len(values) == 1:
        return rstr(values[0])
    return "c(" + ", ".join(rstr(v) for v in values) + ")"


def r_name(path):
    base = os.path.basename(path.rstrip("/\\")) or "dataset"
    base = re.sub(r"\.(gz|bz2|xz|zip)$", "", base, flags=re.I)
    base = os.path.splitext(base)[0] or "dataset"
    name = re.sub(r"[^A-Za-z0-9._]", "_", base)
    if not re.match(r"^[A-Za-z]|^\.[A-Za-z_]", name):
        name = "X" + name
    return name


def sniff_text(path):
    """Guess delimiter, decimal mark and header from the first lines of a local file."""
    try:
        import gzip
        opener = gzip.open if path.lower().endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as f:
            sample = "".join(f.readline() for _ in range(20))
    except OSError:
        return None
    if not sample.strip():
        return None
    lines = [ln for ln in sample.splitlines() if ln.strip()]
    best, best_score = ",", -1
    for d in (",", ";", "\t", "|"):
        counts = [ln.count(d) for ln in lines]
        if counts and min(counts) > 0 and len(set(counts)) == 1:
            score = 100 + counts[0]
        else:
            score = sum(1 for c in counts if c > 0)
        if score > best_score:
            best, best_score = d, score
    if best_score <= 0:
        best = ""  # whitespace separated
    dec = "."
    if best != ",":
        body = "\n".join(lines[1:])
        if re.search(r"\d,\d", body) and not re.search(r"\d\.\d", body):
            dec = ","
    header = True
    try:
        if best:
            rows = list(csv.reader(lines[:2], delimiter=best))
            if len(rows) == 2:
                def numeric(v):
                    return bool(re.match(r"^\s*-?[\d.,]+([eE][-+]?\d+)?\s*$", v))
                # a first row with numbers, below a row of the same shape, is data
                header = not any(numeric(v) for v in rows[0])
    except csv.Error:
        pass
    return {"delim": best, "dec": dec, "header": header}


class ImportDatasetDialog(QtWidgets.QDialog):
    def __init__(self, main, path="", fmt=None):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Import Dataset")
        self.resize(1040, 720)
        self.available = {}  # package -> installed?
        self._preview_pending = False
        self._sheets_for = None

        layout = QtWidgets.QVBoxLayout(self)

        # ---- file / format row
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("File/URL:"))
        self.path = QtWidgets.QLineEdit(path)
        self.path.setPlaceholderText("Path to a file, or a URL (http/https)")
        self.path.editingFinished.connect(self._path_changed)
        top.addWidget(self.path, 1)
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        top.addWidget(browse)
        update = QtWidgets.QPushButton("Update")
        update.setToolTip("Re-read the file and refresh the preview")
        update.clicked.connect(self._refresh_all)
        top.addWidget(update)
        layout.addLayout(top)

        fmt_row = QtWidgets.QHBoxLayout()
        fmt_row.addWidget(QtWidgets.QLabel("Import:"))
        self.fmt = QtWidgets.QComboBox()
        for key, (label, pkg, _) in FORMATS.items():
            self.fmt.addItem(label + (f"   [{pkg}]" if pkg else ""), key)
        self.fmt.currentIndexChanged.connect(self._format_changed)
        fmt_row.addWidget(self.fmt)
        fmt_row.addStretch(1)
        layout.addLayout(fmt_row)

        # ---- missing package banner
        self.banner = QtWidgets.QFrame()
        self.banner.setStyleSheet(
            "QFrame { background: #fff4ce; border: 1px solid #e0c060; border-radius: 3px; }"
            "QLabel { color: #5a4500; border: none; }")
        bl = QtWidgets.QHBoxLayout(self.banner)
        bl.setContentsMargins(8, 4, 8, 4)
        self.banner_label = QtWidgets.QLabel()
        bl.addWidget(self.banner_label, 1)
        self.banner_button = QtWidgets.QPushButton("Install")
        self.banner_button.clicked.connect(self._install_missing)
        bl.addWidget(self.banner_button)
        self.banner.hide()
        layout.addWidget(self.banner)

        # ---- data preview
        box = QtWidgets.QGroupBox("Data Preview")
        bv = QtWidgets.QVBoxLayout(box)
        self.table = QtWidgets.QTableView()
        self.model = QtGui.QStandardItemModel(self)
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 6)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        bv.addWidget(self.table)
        self.text_preview = QtWidgets.QPlainTextEdit(readOnly=True)
        self.text_preview.setFont(default_font())
        self.text_preview.hide()
        bv.addWidget(self.text_preview)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bv.addWidget(self.status)
        layout.addWidget(box, 1)

        # ---- options and code
        bottom = QtWidgets.QHBoxLayout()
        opts = QtWidgets.QGroupBox("Import Options")
        ol = QtWidgets.QVBoxLayout(opts)
        name_row = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit("dataset")
        self.name.textEdited.connect(self._name_edited)
        self._name_touched = False
        name_row.addRow("Name:", self.name)
        ol.addLayout(name_row)
        self.pages = QtWidgets.QStackedWidget()
        self.pages.addWidget(self._text_page())
        self.pages.addWidget(self._excel_page())
        self.pages.addWidget(self._haven_page())
        self.pages.addWidget(self._json_page())
        self.pages.addWidget(self._rds_page())
        ol.addWidget(self.pages)
        ol.addStretch(1)
        bottom.addWidget(opts, 3)

        codebox = QtWidgets.QGroupBox("Code Preview")
        cl = QtWidgets.QVBoxLayout(codebox)
        self.code = QtWidgets.QPlainTextEdit(readOnly=True)
        self.code.setFont(default_font())
        self.code.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        cl.addWidget(self.code)
        copy = QtWidgets.QPushButton("Copy code")
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.code.toPlainText()))
        crow = QtWidgets.QHBoxLayout()
        crow.addStretch(1)
        crow.addWidget(copy)
        cl.addLayout(crow)
        bottom.addWidget(codebox, 4)
        layout.addLayout(bottom)

        # ---- buttons
        brow = QtWidgets.QHBoxLayout()
        self.open_viewer = QtWidgets.QCheckBox("Open data viewer")
        self.open_viewer.setChecked(True)
        self.open_viewer.toggled.connect(self._update_code)
        brow.addWidget(self.open_viewer)
        brow.addStretch(1)
        self.import_button = QtWidgets.QPushButton("Import")
        self.import_button.setDefault(True)
        self.import_button.clicked.connect(self._import)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        brow.addWidget(self.import_button)
        brow.addWidget(cancel)
        layout.addLayout(brow)

        self._preview_timer = QtCore.QTimer(self, singleShot=True, interval=350)
        self._preview_timer.timeout.connect(self._run_preview)

        self._loading = True
        if fmt is None and path:
            fmt = format_for_path(path)
        if fmt:
            self.fmt.setCurrentIndex(self.fmt.findData(fmt))
        self._loading = False
        self._query_packages()
        self._format_changed()
        if path:
            self._path_changed(force=True)

    # ------------------------------------------------------------ pages --
    def _form_page(self):
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        return w, f

    def _changed(self, *_):
        if not self._loading:
            self._update_code()
            self._preview_timer.start()

    def _text_page(self):
        w, f = self._form_page()
        grid = QtWidgets.QGridLayout()
        self.t_skip = QtWidgets.QSpinBox(maximum=100000)
        self.t_header = QtWidgets.QCheckBox("First row as names")
        self.t_header.setChecked(True)
        self.t_trim = QtWidgets.QCheckBox("Trim spaces")
        self.t_trim.setChecked(True)
        self.t_factors = QtWidgets.QCheckBox("Strings as factors")
        self.t_delim = QtWidgets.QComboBox()
        for label, d in DELIMITERS:
            self.t_delim.addItem(label, d)
        self.t_delim_other = QtWidgets.QLineEdit()
        self.t_delim_other.setMaximumWidth(40)
        self.t_delim_other.setEnabled(False)
        self.t_quote = QtWidgets.QComboBox()
        for label, q in (("Double quote (\")", '"'), ("Single quote (')", "'"),
                         ("Both", "\"'"), ("None", "")):
            self.t_quote.addItem(label, q)
        self.t_dec = QtWidgets.QComboBox()
        self.t_dec.addItem("Period (.)", ".")
        self.t_dec.addItem("Comma (,)", ",")
        self.t_na = QtWidgets.QLineEdit("NA")
        self._na_touched = False
        self.t_na.textEdited.connect(lambda _t: setattr(self, "_na_touched", True))
        self.t_na.setToolTip('Values to read as missing, separated by commas. "" means empty cells.')
        self.t_encoding = QtWidgets.QComboBox(editable=True)
        self.t_encoding.addItems(["UTF-8", "latin1", "Windows-1252", "UTF-16"])
        self.t_comment = QtWidgets.QLineEdit()
        self.t_comment.setMaximumWidth(40)
        self.t_comment.setToolTip("Lines starting with this character are ignored")

        delim_row = QtWidgets.QHBoxLayout()
        delim_row.addWidget(self.t_delim, 1)
        delim_row.addWidget(self.t_delim_other)
        grid.addWidget(QtWidgets.QLabel("Skip:"), 0, 0)
        grid.addWidget(self.t_skip, 0, 1)
        grid.addWidget(self.t_header, 0, 2)
        grid.addWidget(QtWidgets.QLabel("Delimiter:"), 1, 0)
        grid.addLayout(delim_row, 1, 1)
        grid.addWidget(self.t_trim, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Quotes:"), 2, 0)
        grid.addWidget(self.t_quote, 2, 1)
        grid.addWidget(self.t_factors, 2, 2)
        grid.addWidget(QtWidgets.QLabel("Decimal:"), 3, 0)
        grid.addWidget(self.t_dec, 3, 1)
        grid.addWidget(QtWidgets.QLabel("Comment:"), 3, 2)
        grid.addWidget(self.t_comment, 3, 3)
        grid.addWidget(QtWidgets.QLabel("NA:"), 4, 0)
        grid.addWidget(self.t_na, 4, 1)
        grid.addWidget(QtWidgets.QLabel("Encoding:"), 5, 0)
        grid.addWidget(self.t_encoding, 5, 1)
        f.addRow(grid)

        for sig in (self.t_skip.valueChanged, self.t_header.toggled, self.t_trim.toggled,
                    self.t_factors.toggled, self.t_quote.currentIndexChanged,
                    self.t_dec.currentIndexChanged, self.t_na.textChanged,
                    self.t_encoding.currentTextChanged, self.t_delim_other.textChanged,
                    self.t_comment.textChanged):
            sig.connect(self._changed)
        self.t_delim.currentIndexChanged.connect(self._delim_changed)
        return w

    def _delim_changed(self):
        self.t_delim_other.setEnabled(self.t_delim.currentData() is None)
        self._changed()

    def _excel_page(self):
        w, f = self._form_page()
        self.x_sheet = QtWidgets.QComboBox()
        self.x_sheet.addItem("Default", "")
        self.x_range = QtWidgets.QLineEdit()
        self.x_range.setPlaceholderText("e.g. A1:D20 (optional)")
        self.x_skip = QtWidgets.QSpinBox(maximum=100000)
        self.x_header = QtWidgets.QCheckBox("First row as names")
        self.x_header.setChecked(True)
        self.x_na = QtWidgets.QLineEdit("")
        self.x_na.setPlaceholderText('e.g. NA, -999   (empty cells are always missing)')
        f.addRow("Sheet:", self.x_sheet)
        f.addRow("Range:", self.x_range)
        f.addRow("Skip:", self.x_skip)
        f.addRow("", self.x_header)
        f.addRow("NA:", self.x_na)
        for sig in (self.x_sheet.currentIndexChanged, self.x_range.textChanged,
                    self.x_skip.valueChanged, self.x_header.toggled, self.x_na.textChanged):
            sig.connect(self._changed)
        return w

    def _haven_page(self):
        w, f = self._form_page()
        self.h_factor = QtWidgets.QCheckBox("Convert labelled values to factors (haven::as_factor)")
        self.h_skip = QtWidgets.QSpinBox(maximum=1000000)
        self.h_encoding = QtWidgets.QComboBox(editable=True)
        self.h_encoding.addItems(["Default", "UTF-8", "latin1", "Windows-1252"])
        f.addRow("", self.h_factor)
        f.addRow("Skip rows:", self.h_skip)
        f.addRow("Encoding:", self.h_encoding)
        for sig in (self.h_factor.toggled, self.h_skip.valueChanged,
                    self.h_encoding.currentTextChanged):
            sig.connect(self._changed)
        return w

    def _json_page(self):
        w, f = self._form_page()
        self.j_flatten = QtWidgets.QCheckBox("Flatten nested data frames")
        self.j_flatten.setChecked(True)
        self.j_simplify = QtWidgets.QCheckBox("Simplify to vectors / data frames")
        self.j_simplify.setChecked(True)
        f.addRow("", self.j_flatten)
        f.addRow("", self.j_simplify)
        for sig in (self.j_flatten.toggled, self.j_simplify.toggled):
            sig.connect(self._changed)
        return w

    def _rds_page(self):
        w, f = self._form_page()
        label = QtWidgets.QLabel(
            "<b>.rds</b>: the object is read with <code>readRDS()</code> and stored under "
            "the name above.<br><b>.RData / .rda</b>: all objects in the file are loaded "
            "into the global environment with <code>load()</code>; their own names are kept.")
        label.setWordWrap(True)
        f.addRow(label)
        return w

    # ------------------------------------------------------- file & format --
    def current_format(self):
        return self.fmt.currentData()

    def _browse(self):
        start = self.path.text() or self.main.cfg.get("lastDir") or os.path.expanduser("~")
        if os.path.isfile(start):
            start = os.path.dirname(start)
        filt = FORMATS[self.current_format()][2]
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose data file", start, filt)
        if path:
            self.path.setText(path)
            self.main.cfg["lastDir"] = os.path.dirname(path)
            self._path_changed(force=True)

    def _path_changed(self, force=False):
        path = self.path.text().strip()
        if not path:
            return
        if not force and path == getattr(self, "_last_path", None):
            return
        self._last_path = path
        guess = format_for_path(path)
        cur = self.current_format()
        if guess and not (guess == "text_base" and cur.startswith("text_")):
            self._loading = True
            self.fmt.setCurrentIndex(self.fmt.findData(guess))
            self._loading = False
            self._format_changed(preview=False)
        if not self._name_touched:
            self.name.setText(r_name(path))
        if self.current_format().startswith("text_") and os.path.isfile(path):
            guess = sniff_text(path)
            if guess:
                self._loading = True
                self.t_delim.setCurrentIndex(
                    next(i for i, (_, d) in enumerate(DELIMITERS) if d == guess["delim"]))
                self.t_dec.setCurrentIndex(self.t_dec.findData(guess["dec"]))
                self.t_header.setChecked(guess["header"])
                self._loading = False
        self._sheets_for = None
        self._update_sheets()
        self._update_code()
        self._preview_timer.start(10)

    def _name_edited(self, _text):
        self._name_touched = True
        self._update_code()

    def _format_changed(self, *_args, preview=True):
        fmt = self.current_format()
        page = {"text_base": 0, "text_readr": 0, "text_fread": 0, "excel": 1, "spss": 2,
                "sas": 2, "stata": 2, "json": 3, "rds": 4}[fmt]
        self.pages.setCurrentIndex(page)
        # options that do not apply to every text reader
        self.t_factors.setEnabled(fmt == "text_base")
        self.t_trim.setEnabled(fmt != "text_fread")
        self.t_comment.setEnabled(fmt != "text_fread")
        if not self._na_touched:  # each reader's own default
            self._loading, was = True, self._loading
            self.t_na.setText('"", NA' if fmt == "text_readr" else "NA")
            self._loading = was
        self._update_banner()
        self._update_sheets()
        self._update_code()
        if preview and not self._loading:
            self._preview_timer.start(10)

    def _refresh_all(self):
        self._query_packages()
        self._sheets_for = None
        self._update_sheets()
        self._preview_timer.start(10)

    # ------------------------------------------------------------ packages --
    def _kernel(self):
        shell = self.main.current_shell()
        return shell.kernel if shell is not None else None

    def _query_packages(self):
        k = self._kernel()
        if k is None:
            return
        code = "list(" + ", ".join(f'"{p}" = nzchar(system.file(package = "{p}"))'
                                   for p in PACKAGES) + ")"

        def done(msg):
            self.available = msg.get("value") or {}
            self._update_banner()
            self._update_sheets()

        if not k.query(code, done):
            QtCore.QTimer.singleShot(500, self._query_packages)

    def required_package(self):
        return FORMATS[self.current_format()][1]

    def _update_banner(self):
        pkg = self.required_package()
        missing = bool(pkg) and self.available and not self.available.get(pkg, False)
        if missing:
            self.banner_label.setText(
                f"The <b>{pkg}</b> package is required for this import but is not installed.")
            self.banner_button.setText(f"Install {pkg}...")
        self.banner.setVisible(bool(missing))
        self.import_button.setEnabled(not missing)

    def _install_missing(self):
        from ryzo.core.packagedialog import InstallPackagesDialog
        dlg = InstallPackagesDialog(self.main, packages=self.required_package())
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.status.setText("Installing... press Update when the installation has finished.")
            self._wait_install = QtCore.QTimer(self, interval=1000)
            self._wait_install.timeout.connect(self._check_installed)
            self._wait_install.start()

    def _check_installed(self):
        k = self._kernel()
        if k is not None and k.state == "ready":
            self._wait_install.stop()
            self._refresh_all()

    def _update_sheets(self):
        if self.current_format() != "excel" or not self.available.get("readxl"):
            return
        path = self.path.text().strip()
        if not path or self._sheets_for == path:
            return
        k = self._kernel()
        if k is None:
            return

        def done(msg):
            sheets = msg.get("value") or []
            if isinstance(sheets, str):
                sheets = [sheets]
            current = self.x_sheet.currentData()
            self._loading = True
            self.x_sheet.clear()
            self.x_sheet.addItem("Default", "")
            for s in sheets:
                self.x_sheet.addItem(s, s)
            i = self.x_sheet.findData(current)
            self.x_sheet.setCurrentIndex(max(0, i))
            self._loading = False

        if k.query(f"I(readxl::excel_sheets({rstr(path)}))", done):
            self._sheets_for = path

    # ---------------------------------------------------------------- code --
    @staticmethod
    def _na_values(text):
        vals = []
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            if part in ('""', "''"):
                vals.append("")
            else:
                vals.append(part.strip("\"'"))
        return vals

    def _delim(self):
        d = self.t_delim.currentData()
        return self.t_delim_other.text() if d is None else d

    def reader_call(self, preview=False):
        """The R expression that reads the data (no assignment)."""
        fmt = self.current_format()
        path = self.path.text().strip()
        p = rstr(path)
        args = []

        def arg(name, value, default=None):
            if value != default:
                args.append(f"{name} = {value}")

        if fmt == "text_base":
            delim = self._delim()
            dec = self.t_dec.currentData()
            fun = "read.csv"
            if delim == ";" and dec == ",":
                fun, std = "read.csv2", (";", ",")
            elif delim == "\t" and dec == ".":
                fun, std = "read.delim", ("\t", ".")
            else:
                std = (",", ".")
            if delim != std[0]:
                arg("sep", rstr(delim))
            if dec != std[1]:
                arg("dec", rstr(dec))
            arg("header", "FALSE" if not self.t_header.isChecked() else None)
            q = self.t_quote.currentData()
            if q != '"':
                args.append(f"quote = {rstr(q)}")
            na = self._na_values(self.t_na.text())
            if na != ["NA"]:
                args.append(f"na.strings = {rvec(na) if na else 'character(0)'}")
            arg("skip", str(self.t_skip.value()), "0")
            arg("strip.white", "TRUE" if self.t_trim.isChecked() else None)
            arg("stringsAsFactors", "TRUE" if self.t_factors.isChecked() else None)
            c = self.t_comment.text()
            arg("comment.char", rstr(c) if c else None)
            enc = self.t_encoding.currentText().strip()
            arg("fileEncoding", rstr(enc) if enc and enc.upper() != "UTF-8" else None)
            if preview:
                args.append(f"nrows = {PREVIEW_ROWS}")
            return f"{fun}({p}" + "".join(", " + a for a in args) + ")"

        if fmt == "text_readr":
            delim = self._delim()
            fun = "readr::read_delim"
            if delim == "":
                fun = "readr::read_table"
            elif delim == ",":
                fun = "readr::read_csv"
            elif delim == "\t":
                fun = "readr::read_tsv"
            else:
                arg("delim", rstr(delim))
            q = self.t_quote.currentData()
            if delim != "" and q != '"':
                args.append(f"quote = {rstr(q)}")
            arg("col_names", "FALSE" if not self.t_header.isChecked() else None)
            na = self._na_values(self.t_na.text())
            if sorted(na) != ["", "NA"]:
                args.append(f"na = {rvec(na) if na else 'character()'}")
            arg("skip", str(self.t_skip.value()), "0")
            arg("trim_ws", "FALSE" if not self.t_trim.isChecked() else None)
            c = self.t_comment.text()
            arg("comment", rstr(c) if c else None)
            loc = []
            if self.t_dec.currentData() == ",":
                loc.append('decimal_mark = ","')
                loc.append('grouping_mark = "."')
            enc = self.t_encoding.currentText().strip()
            if enc and enc.upper() != "UTF-8":
                loc.append(f"encoding = {rstr(enc)}")
            if loc:
                args.append("locale = readr::locale(" + ", ".join(loc) + ")")
            arg("show_col_types", "FALSE")
            if preview:
                args.append(f"n_max = {PREVIEW_ROWS}")
            return f"{fun}({p}" + "".join(", " + a for a in args) + ")"

        if fmt == "text_fread":
            delim = self._delim()
            if delim != ",":
                args.append(f"sep = {rstr(delim) if delim else chr(34) + ' ' + chr(34)}")
            arg("dec", rstr(self.t_dec.currentData()), '"."')
            arg("header", "FALSE" if not self.t_header.isChecked() else None)
            q = self.t_quote.currentData()
            if q != '"':
                args.append(f"quote = {rstr(q)}")
            na = self._na_values(self.t_na.text())
            if na != ["NA"]:
                args.append(f"na.strings = {rvec(na) if na else 'character(0)'}")
            arg("skip", str(self.t_skip.value()), "0")
            enc = self.t_encoding.currentText().strip()
            arg("encoding", '"Latin-1"' if enc.lower() in ("latin1", "latin-1") else None)
            if preview:
                args.append(f"nrows = {PREVIEW_ROWS}")
            return f"data.table::fread({p}" + "".join(", " + a for a in args) + ")"

        if fmt == "excel":
            sheet = self.x_sheet.currentData()
            arg("sheet", rstr(sheet) if sheet else None)
            rng = self.x_range.text().strip()
            arg("range", rstr(rng) if rng else None)
            arg("col_names", "FALSE" if not self.x_header.isChecked() else None)
            na = self._na_values(self.x_na.text())
            arg("na", rvec([""] + na) if na else None)
            if not rng:
                arg("skip", str(self.x_skip.value()), "0")
            if preview and not rng:
                args.append(f"n_max = {PREVIEW_ROWS}")
            return f"readxl::read_excel({p}" + "".join(", " + a for a in args) + ")"

        if fmt in ("spss", "sas", "stata"):
            fun = {"spss": "haven::read_sav", "sas": "haven::read_sas",
                   "stata": "haven::read_dta"}[fmt]
            low = path.lower()
            if fmt == "spss" and low.endswith(".por"):
                fun = "haven::read_por"
            elif fmt == "sas" and low.endswith(".xpt"):
                fun = "haven::read_xpt"
            enc = self.h_encoding.currentText().strip()
            if enc and enc != "Default" and not fun.endswith(("_por", "_xpt")):
                arg("encoding", rstr(enc))
            arg("skip", str(self.h_skip.value()), "0")
            if preview:
                args.append(f"n_max = {PREVIEW_ROWS}")
            call = f"{fun}({p}" + "".join(", " + a for a in args) + ")"
            if self.h_factor.isChecked():
                call = f"haven::as_factor({call})"
            return call

        if fmt == "json":
            arg("simplifyVector", "FALSE" if not self.j_simplify.isChecked() else None)
            arg("flatten", "TRUE" if self.j_flatten.isChecked() else None)
            return f"jsonlite::fromJSON({p}" + "".join(", " + a for a in args) + ")"

        # rds / RData
        if re.search(r"\.(rdata|rda)$", path, re.I):
            if preview:
                return f"local({{e <- new.env(); load({p}, envir = e); e}})"
            return None
        return f"readRDS({p})"

    def import_code(self):
        path = self.path.text().strip()
        name = self.name.text().strip() or "dataset"
        if not re.match(r"^([A-Za-z]|\.[A-Za-z_.])[A-Za-z0-9._]*$", name):
            name = f"`{name}`"
        call = self.reader_call()
        if call is None:  # .RData
            return f"load({rstr(path)})"
        lines = [f"{name} <- {call}"]
        if self.open_viewer.isChecked():
            lines.append(f"View({name})")
        return "\n".join(lines)

    def _update_code(self):
        if not self.path.text().strip():
            self.code.setPlainText("# Choose a file or enter a URL above")
            return
        code = self.import_code()
        # wrap long calls after commas for readability
        out = []
        for line in code.split("\n"):
            if len(line) > 70 and "(" in line:
                head, _, rest = line.partition("(")
                parts = re.split(r",\s(?=[A-Za-z_.]+ = )", rest)
                indent = " " * (len(head) + 1)
                line = head + "(" + (",\n" + indent).join(parts)
            out.append(line)
        self.code.setPlainText("\n".join(out))

    # ------------------------------------------------------------- preview --
    def _run_preview(self):
        path = self.path.text().strip()
        if not path:
            return
        if self.banner.isVisible():
            self.model.clear()
            self.status.setText("")
            return
        k = self._kernel()
        if k is None:
            self.status.setText("Start an R shell to preview the data.")
            return
        call = self.reader_call(preview=True)
        if not k.preview(call, self._show_preview):
            self.status.setText("Waiting for R to finish...")
            self._preview_timer.start(600)
            return
        self.status.setText("Reading...")

    def _show_preview(self, msg):
        data = msg.get("data") or {}
        err = data.get("error") or ""
        self.model.clear()
        if err:
            self.table.show()
            self.text_preview.hide()
            self.status.setText("<span style='color:#c62828'><b>Error:</b> "
                                + html.escape(err).replace("\n", "<br>") + "</span>")
            return
        if "text" in data:
            self.table.hide()
            self.text_preview.show()
            self.text_preview.setPlainText(data["text"])
            self.status.setText("The object is not a table; its structure is shown.")
            return
        self.table.show()
        self.text_preview.hide()
        cols, types = data.get("columns") or [], data.get("types") or []
        self.model.setColumnCount(len(cols))
        for i, (c, t) in enumerate(zip(cols, types)):
            item = QtGui.QStandardItem(f"{c}\n({t})")
            self.model.setHorizontalHeaderItem(i, item)
        numeric = [t in ("double", "integer") for t in types]
        gray = QtGui.QBrush(QtGui.QColor("#999999"))
        for row in data.get("rows") or []:
            items = []
            for i, v in enumerate(row):
                it = QtGui.QStandardItem(v)
                if i < len(numeric) and numeric[i]:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if v == "NA":
                    it.setForeground(gray)
                items.append(it)
            self.model.appendRow(items)
        self.table.resizeColumnsToContents()
        for c in range(self.model.columnCount()):
            self.table.setColumnWidth(c, min(220, max(60, self.table.columnWidth(c))))
        nrow, ncol = data.get("nrow", 0), data.get("ncol", 0)
        shown = len(data.get("rows") or [])
        msg_txt = f"{ncol} columns. Previewing the first {shown} rows." if nrow >= PREVIEW_ROWS else \
            f"{nrow} rows x {ncol} columns."
        warns = data.get("warnings") or []
        if warns:
            msg_txt += "<br><span style='color:#b26a00'>" + "<br>".join(
                html.escape(w) for w in warns[:3]) + "</span>"
        self.status.setText(msg_txt)

    # -------------------------------------------------------------- import --
    def _import(self):
        if not self.path.text().strip():
            QtWidgets.QMessageBox.information(self, "Import Dataset", "Choose a file first.")
            return
        code = self.import_code()
        self.main.execute_code(code, "block", label="[Import Dataset]")
        shell = self.main.current_shell()
        if shell is not None:
            shell._add_history(code)
        self.accept()
