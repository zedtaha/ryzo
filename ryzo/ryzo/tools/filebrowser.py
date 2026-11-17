"""File browser tool."""

import os
import shutil

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ryzo.config import get_config

TEXT_EXT = {".r", ".rmd", ".qmd", ".rprofile", ".renviron", ".txt", ".md", ".csv", ".tsv",
            ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".py", ".sh", ".sql", ".html",
            ".css", ".js", ".xml", ".tex", ".bib", ".rd", ".log", ""}


class FileBrowserTool(QtWidgets.QWidget):
    title = "File browser"

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.cfg = get_config()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        row = QtWidgets.QHBoxLayout()
        style = self.style()
        up = QtWidgets.QToolButton()
        up.setIcon(style.standardIcon(QtWidgets.QStyle.SP_FileDialogToParent))
        up.setToolTip("Parent folder")
        up.clicked.connect(self.go_up)
        self.star_button = QtWidgets.QToolButton()
        self.star_button.setText("☆")
        self.star_button.setToolTip("Starred folders")
        self.star_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.star_menu = QtWidgets.QMenu(self)
        self.star_menu.aboutToShow.connect(self._fill_star_menu)
        self.star_button.setMenu(self.star_menu)
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.returnPressed.connect(lambda: self.set_path(self.path_edit.text()))
        completer = QtWidgets.QCompleter(self)
        dir_model = QtWidgets.QFileSystemModel(completer)
        dir_model.setFilter(QtCore.QDir.Dirs | QtCore.QDir.NoDotAndDotDot)
        dir_model.setRootPath("")
        completer.setModel(dir_model)
        self.path_edit.setCompleter(completer)
        wd = QtWidgets.QToolButton()
        wd.setText("wd")
        wd.setToolTip("Go to the working directory of the current shell")
        wd.clicked.connect(self.go_to_shell_wd)
        row.addWidget(up)
        row.addWidget(self.star_button)
        row.addWidget(self.path_edit, 1)
        row.addWidget(wd)
        layout.addLayout(row)

        self.model = QtWidgets.QFileSystemModel(self)
        self.model.setReadOnly(False)
        self.model.setNameFilterDisables(False)
        self.model.setFilter(QtCore.QDir.AllDirs | QtCore.QDir.Files | QtCore.QDir.NoDotAndDotDot)
        self.model.setRootPath("")
        self.tree = QtWidgets.QTreeView()
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(False)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        self.tree.setColumnHidden(2, True)
        self.tree.setColumnWidth(0, 220)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditKeyPressed)
        self.tree.doubleClicked.connect(self._activated)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tree, 1)

        self.filter_edit = QtWidgets.QLineEdit(self.cfg.fileBrowser.get("filter", ""))
        self.filter_edit.setPlaceholderText("Filter, e.g. *.R *.csv   (empty = all files)")
        self.filter_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter_edit)
        self._apply_filter()

        path = self.cfg.fileBrowser.get("path") or os.path.expanduser("~")
        self.set_path(path)

    def _apply_filter(self):
        text = self.filter_edit.text().strip()
        self.cfg.fileBrowser["filter"] = text
        pats = [p for p in text.replace(",", " ").split() if p]
        self.model.setNameFilters(pats)

    def path(self):
        return self.model.filePath(self.tree.rootIndex())

    def set_path(self, path):
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isfile(path):
            path = os.path.dirname(path)
        if not os.path.isdir(path):
            return
        self.tree.setRootIndex(self.model.index(path))
        self.path_edit.setText(path)
        self.cfg.fileBrowser["path"] = path
        starred = path in self.cfg.fileBrowser.get("starred", [])
        self.star_button.setText("★" if starred else "☆")

    def go_up(self):
        self.set_path(os.path.dirname(self.path()))

    def go_to_shell_wd(self):
        shell = self.main.current_shell()
        if shell is not None and getattr(shell, "cwd", None):
            self.set_path(shell.cwd)

    def show_file(self, filename):
        self.set_path(os.path.dirname(filename))
        index = self.model.index(filename)
        self.tree.setCurrentIndex(index)
        self.tree.scrollTo(index)

    def _fill_star_menu(self):
        self.star_menu.clear()
        starred = self.cfg.fileBrowser.setdefault("starred", [])
        cur = self.path()
        if cur in starred:
            self.star_menu.addAction("Unstar this folder", lambda: self._toggle_star(cur))
        else:
            self.star_menu.addAction("Star this folder", lambda: self._toggle_star(cur))
        if starred:
            self.star_menu.addSeparator()
        for p in starred:
            self.star_menu.addAction(p, lambda p=p: self.set_path(p))

    def _toggle_star(self, path):
        starred = self.cfg.fileBrowser.setdefault("starred", [])
        if path in starred:
            starred.remove(path)
        else:
            starred.append(path)
        self.set_path(path)

    def _activated(self, index):
        path = self.model.filePath(index)
        if os.path.isdir(path):
            self.set_path(path)
        else:
            self.open_path(path)

    def open_path(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in TEXT_EXT or os.path.basename(path).startswith("."):
            self.main.editors.open_file(path)
        elif ext in (".rds", ".rdata", ".rda", ".xlsx", ".xls", ".xlsm", ".sav", ".zsav",
                     ".por", ".dta", ".sas7bdat", ".xpt"):
            self.main.import_dataset(path=path)
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def _selected_paths(self):
        rows = self.tree.selectionModel().selectedRows(0)
        return [self.model.filePath(i) for i in rows]

    def _context_menu(self, pos):
        index = self.tree.indexAt(pos)
        path = self.model.filePath(index) if index.isValid() else self.path()
        isdir = os.path.isdir(path)
        menu = QtWidgets.QMenu(self)
        if index.isValid() and not isdir:
            menu.addAction("Open", lambda: self.open_path(path))
            if path.lower().endswith(".r"):
                menu.addAction("Run file (source)", lambda: self.main.execute_code(
                    f'source("{path.replace(chr(92), "/")}", echo = FALSE)', "block"))
            from ryzo.core.importdialog import format_for_path
            if format_for_path(path):
                menu.addAction("Import Dataset...", lambda: self.main.import_dataset(path=path))
            menu.addAction("Open outside Ryzo",
                           lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path)))
            menu.addSeparator()
        folder = path if isdir else os.path.dirname(path)
        if isdir and index.isValid():
            menu.addAction("Go into folder", lambda: self.set_path(path))
        menu.addAction("Set as R working directory", lambda: self.main.setwd(folder))
        menu.addAction("New file...", lambda: self._new_file(folder))
        menu.addAction("New folder...", lambda: self._new_folder(folder))
        if index.isValid():
            menu.addSeparator()
            menu.addAction("Rename", lambda: self.tree.edit(index))
            menu.addAction("Delete", self._delete)
            menu.addAction("Copy path", lambda: QtWidgets.QApplication.clipboard().setText(path))
        menu.addAction("Open folder in system file manager",
                       lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder)))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _new_file(self, folder):
        name, ok = QtWidgets.QInputDialog.getText(self, "New file", "File name:", text="script.R")
        if ok and name:
            path = os.path.join(folder, name)
            if not os.path.exists(path):
                open(path, "w", encoding="utf-8").close()
            self.main.editors.open_file(path)

    def _new_folder(self, folder):
        name, ok = QtWidgets.QInputDialog.getText(self, "New folder", "Folder name:")
        if ok and name:
            os.makedirs(os.path.join(folder, name), exist_ok=True)

    def _delete(self):
        paths = self._selected_paths()
        if not paths:
            return
        names = "\n".join(os.path.basename(p) for p in paths[:10])
        res = QtWidgets.QMessageBox.question(self, "Delete", f"Permanently delete?\n\n{names}")
        if res != QtWidgets.QMessageBox.Yes:
            return
        for p in paths:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
            except OSError as err:
                QtWidgets.QMessageBox.warning(self, "Delete", str(err))
