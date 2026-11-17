"""Install Packages dialog, modelled after RStudio's."""

import os
import re

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt

from ryzo.core.importdialog import rstr

_cran_cache = []  # package names, kept for the session


class MultiCompleteLineEdit(QtWidgets.QLineEdit):
    """Completes the last word of a space/comma separated list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = QtCore.QStringListModel(self)
        self.completer_ = QtWidgets.QCompleter(self._model, self)
        self.completer_.setWidget(self)
        self.completer_.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer_.setMaxVisibleItems(12)
        self.completer_.activated.connect(self._insert)
        self.textEdited.connect(self._edited)

    def set_words(self, words):
        self._model.setStringList(words)

    def _last_token(self):
        text = self.text()[:self.cursorPosition()]
        return re.split(r"[\s,]+", text)[-1]

    def _edited(self, _text):
        token = self._last_token()
        if len(token) < 1 or not self._model.rowCount():
            self.completer_.popup().hide()
            return
        self.completer_.setCompletionPrefix(token)
        if self.completer_.completionCount() == 0:
            self.completer_.popup().hide()
            return
        self.completer_.complete()

    def _insert(self, word):
        pos = self.cursorPosition()
        before = self.text()[:pos]
        after = self.text()[pos:]
        token = self._last_token()
        before = before[:len(before) - len(token)] + word
        self.setText(before + after)
        self.setCursorPosition(len(before))

    def keyPressEvent(self, event):
        popup = self.completer_.popup()
        if popup.isVisible() and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
            idx = popup.currentIndex()
            if idx.isValid():
                self._insert(idx.data())
            popup.hide()
            return
        super().keyPressEvent(event)


class InstallPackagesDialog(QtWidgets.QDialog):
    def __init__(self, main, packages=""):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Install Packages")
        self.setMinimumWidth(520)
        self._libs = []
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.source = QtWidgets.QComboBox()
        self.source.addItem("Repository (CRAN)", "cran")
        self.source.addItem("Package Archive File (.zip; .tar.gz)", "file")
        self.source.currentIndexChanged.connect(self._source_changed)
        form.addRow("Install from:", self.source)
        self.repo_label = QtWidgets.QLabel("")
        self.repo_label.setStyleSheet("color: gray;")
        form.addRow("", self.repo_label)

        self.pkg_label = QtWidgets.QLabel("Packages (separate multiple with space or comma):")
        form.addRow(self.pkg_label)
        row = QtWidgets.QHBoxLayout()
        self.packages = MultiCompleteLineEdit()
        self.packages.setText(packages)
        self.packages.setPlaceholderText("e.g. dplyr ggplot2")
        row.addWidget(self.packages, 1)
        self.browse = QtWidgets.QPushButton("Browse...")
        self.browse.clicked.connect(self._browse)
        self.browse.hide()
        row.addWidget(self.browse)
        form.addRow(row)

        self.lib = QtWidgets.QComboBox()
        form.addRow("Install to Library:", self.lib)
        self.deps = QtWidgets.QCheckBox("Install dependencies")
        self.deps.setChecked(True)
        form.addRow("", self.deps)
        layout.addLayout(form)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: gray;")
        layout.addWidget(self.status)

        buttons = QtWidgets.QDialogButtonBox()
        self.install_button = buttons.addButton("Install", QtWidgets.QDialogButtonBox.AcceptRole)
        self.install_button.setDefault(True)
        buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._install)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_info()

    # ------------------------------------------------------------- loading --
    def _kernel(self):
        shell = self.main.current_shell()
        return shell.kernel if shell is not None else None

    def _load_info(self):
        k = self._kernel()
        if k is None:
            self.status.setText("Start an R shell first.")
            return
        code = ('list(repos = I(unname(getOption("repos"))), '
                'libs = lapply(.libPaths(), function(p) list(path = p, '
                'writable = file.access(p, 2) == 0)))')
        if not k.query(code, self._got_info):
            self.status.setText("Waiting for R to finish...")
            QtCore.QTimer.singleShot(700, self._load_info)

    def _got_info(self, msg):
        v = msg.get("value") or {}
        repos = v.get("repos") or []
        self.repo_label.setText("Repository: " + ", ".join(repos))
        self._libs = v.get("libs") or []
        self.lib.clear()
        default = None
        for i, lib in enumerate(self._libs):
            label = lib["path"]
            if default is None and lib.get("writable"):
                default = i
                label += "  [Default]"
            elif not lib.get("writable"):
                label += "  (not writable)"
            self.lib.addItem(label, lib["path"])
        if default is None:
            self.status.setText("None of the R libraries is writable. R will offer to create a "
                                "personal library when you install.")
            default = 0
        self.lib.setCurrentIndex(default)
        self._default_lib = default
        self._load_cran()

    def _load_cran(self):
        if _cran_cache:
            self.packages.set_words(_cran_cache)
            self.status.setText(f"{len(_cran_cache)} packages available.")
            return
        k = self._kernel()
        if k is None:
            return
        self.status.setText("Loading the list of CRAN packages...")
        code = ('I(tryCatch(suppressWarnings(rownames(utils::available.packages())), '
                'error = function(e) character()))')

        def done(msg):
            names = msg.get("value") or []
            if isinstance(names, str):
                names = [names]
            if names:
                _cran_cache[:] = sorted(names, key=str.lower)
                self.packages.set_words(_cran_cache)
                self.status.setText(f"{len(names)} packages available.")
            else:
                self.status.setText("Could not load the CRAN package list (no internet "
                                    "connection?). You can still type package names.")

        if not k.query(code, done):
            QtCore.QTimer.singleShot(700, self._load_cran)

    # ------------------------------------------------------------- actions --
    def _source_changed(self):
        from_file = self.source.currentData() == "file"
        self.browse.setVisible(from_file)
        self.repo_label.setVisible(not from_file)
        self.deps.setEnabled(not from_file)
        self.pkg_label.setText("Package archive:" if from_file else
                               "Packages (separate multiple with space or comma):")
        self.packages.setPlaceholderText("path to a .tar.gz or .zip file" if from_file
                                         else "e.g. dplyr ggplot2")
        self.packages.clear()

    def _browse(self):
        start = self.main.cfg.get("lastDir") or os.path.expanduser("~")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose package archive", start,
            "Package archives (*.tar.gz *.zip *.tgz);;All files (*)")
        if path:
            self.packages.setText(path)

    def package_names(self):
        return [p for p in re.split(r"[\s,]+", self.packages.text().strip()) if p]

    def install_code(self):
        lib_args = ""
        if self.lib.count() and self.lib.currentIndex() != getattr(self, "_default_lib", 0):
            lib_args = f", lib = {rstr(self.lib.currentData())}"
        if self.source.currentData() == "file":
            path = self.packages.text().strip()
            type_arg = ', type = "source"' if re.search(r"\.(tar\.gz|tgz)$", path, re.I) else ""
            return f"install.packages({rstr(path)}, repos = NULL{type_arg}{lib_args})"
        pkgs = self.package_names()
        vec = rstr(pkgs[0]) if len(pkgs) == 1 else "c(" + ", ".join(rstr(p) for p in pkgs) + ")"
        # checked: R's default (Depends, Imports, LinkingTo), like RStudio
        deps = "" if self.deps.isChecked() else ", dependencies = FALSE"
        return f"install.packages({vec}{lib_args}{deps})"

    def _install(self):
        if self.source.currentData() == "file":
            path = self.packages.text().strip()
            if not path or not os.path.isfile(path):
                QtWidgets.QMessageBox.warning(self, "Install Packages", "Choose a package archive file.")
                return
            names = [re.split(r"_", os.path.basename(path))[0]]
        else:
            names = self.package_names()
            if not names:
                QtWidgets.QMessageBox.information(self, "Install Packages",
                                                  "Enter one or more package names.")
                return
            bad = [n for n in names if not re.match(r"^[A-Za-z][A-Za-z0-9.]*$", n)]
            if bad:
                QtWidgets.QMessageBox.warning(self, "Install Packages",
                                              "Not a valid package name: " + ", ".join(bad))
                return
            if _cran_cache:
                lower = {p.lower(): p for p in _cran_cache}
                unknown = [n for n in names if n not in _cran_cache]
                fixed = [lower.get(n.lower()) for n in unknown]
                if any(fixed):  # fix capitalisation, e.g. "Rcpp" typed as "rcpp"
                    names = [lower.get(n.lower(), n) for n in names]
                    self.packages.setText(" ".join(names))
                    unknown = [n for n in names if n not in _cran_cache]
                if unknown:
                    res = QtWidgets.QMessageBox.question(
                        self, "Install Packages",
                        "Not found on CRAN: " + ", ".join(unknown) + "\nInstall anyway?")
                    if res != QtWidgets.QMessageBox.Yes:
                        return
        code = self.install_code()
        k = self._kernel()
        if k is None:
            return

        def check_loaded(msg):
            loaded = msg.get("value") or []
            if isinstance(loaded, str):
                loaded = [loaded]
            shell = self.main.current_shell()
            if loaded:
                res = QtWidgets.QMessageBox.question(
                    self, "Install Packages",
                    "These packages are loaded in the current R session: "
                    + ", ".join(loaded) + ".\n\nRestart R before installing? (recommended, "
                    "so the new version can be installed and used)",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No |
                    QtWidgets.QMessageBox.Cancel)
                if res == QtWidgets.QMessageBox.Cancel:
                    return
                if res == QtWidgets.QMessageBox.Yes:
                    shell.restart()
                    shell.write("[Install Packages]\n", "info")
                    shell.kernel.execute(code, "block")
                    self.accept()
                    return
            self.main.execute_code(code, "block", label="[Install Packages]")
            self.accept()

        vec = "c(" + ", ".join(rstr(n) for n in names) + ")"
        if not k.query(f"I(intersect({vec}, loadedNamespaces()))", check_loaded):
            QtWidgets.QMessageBox.information(self, "Install Packages",
                                              "R is busy. Try again when it has finished.")
