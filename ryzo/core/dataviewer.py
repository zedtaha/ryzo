"""Data viewer for View(df): a sortable, filterable table."""

import csv

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt


class TableModel(QtCore.QAbstractTableModel):
    def __init__(self, header, rows, parent=None):
        super().__init__(parent)
        self.header = header
        self.rows = rows
        self._numeric = []
        for col in range(len(header)):
            ok = True
            for r in rows[:200]:
                v = r[col] if col < len(r) else ""
                if v in ("NA", ""):
                    continue
                try:
                    float(v)
                except ValueError:
                    ok = False
                    break
            self._numeric.append(ok)

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self.header)

    def data(self, index, role=Qt.DisplayRole):
        row = self.rows[index.row()]
        v = row[index.column()] if index.column() < len(row) else ""
        if role == Qt.DisplayRole:
            return v
        if role == Qt.UserRole:  # sort key
            if self._numeric[index.column()]:
                try:
                    return float(v)
                except ValueError:
                    return float("-inf")
            return v
        if role == Qt.TextAlignmentRole and self._numeric[index.column()]:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and v == "NA":
            return QtGui.QColor("#999999")
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.header[section] if section < len(self.header) else ""
        return None


class DataViewer(QtWidgets.QWidget):
    def __init__(self, path, title, nrow, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(f"View: {title}")
        self.resize(820, 520)
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
            rows = list(reader)
        header = rows[0] if rows else []
        if header and header[0] == "":
            header[0] = "row"
        data = rows[1:]
        layout = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        shown = len(data)
        info = f"{nrow} rows x {max(0, len(header) - 1)} columns"
        if shown < nrow:
            info += f" (showing first {shown})"
        top.addWidget(QtWidgets.QLabel(info))
        top.addStretch(1)
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("filter rows")
        top.addWidget(self.filter)
        layout.addLayout(top)
        self.model = TableModel(header, data, self)
        self.proxy = QtCore.QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.UserRole)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.AscendingOrder)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 6)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        self.table.resizeColumnsToContents()
        for c in range(self.model.columnCount()):
            if self.table.columnWidth(c) > 260:
                self.table.setColumnWidth(c, 260)
        layout.addWidget(self.table)
