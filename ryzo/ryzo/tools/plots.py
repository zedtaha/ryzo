"""Plots tool: shows R graphics captured by the kernel.

Every plot is kept in R (as a recorded plot) under an id, so it can be
re-rendered at any size: plots are re-drawn to exactly fit the panel
(including high-DPI screens) and can be exported to PNG/PDF/SVG/JPEG/TIFF
at any size and resolution.
"""

import os
import tempfile
import time

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ryzo.config import get_config

MARGIN = 10  # space around the plot "page" in the canvas


class PlotCanvas(QtWidgets.QGraphicsView):
    """Shows one plot; fit-to-window by default, with zoom and pan."""

    zoomChanged = QtCore.Signal(float)
    navigate = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setAlignment(Qt.AlignCenter)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setMinimumSize(80, 60)
        self._item = QtWidgets.QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.SmoothTransformation)
        shadow = QtWidgets.QGraphicsDropShadowEffect()
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 2)
        shadow.setColor(QtGui.QColor(0, 0, 0, 70))
        self._item.setGraphicsEffect(shadow)
        self.scene().addItem(self._item)
        self._placeholder = self.scene().addText("")
        self.fit = True
        self.zoom = 1.0
        self._update_background()
        self.show_placeholder("No plots yet.\nRun e.g.  plot(cars)  in a shell.")

    def _update_background(self):
        base = self.palette().color(QtGui.QPalette.Window)
        bg = base.darker(108) if base.lightness() > 128 else base.lighter(115)
        self.setBackgroundBrush(bg)
        self._placeholder.setDefaultTextColor(self.palette().color(QtGui.QPalette.PlaceholderText))

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.PaletteChange:
            self._update_background()
        super().changeEvent(event)

    def show_placeholder(self, text):
        self._item.setPixmap(QtGui.QPixmap())
        self._item.setVisible(False)
        self._placeholder.setPlainText(text)
        self._placeholder.setVisible(True)
        self.resetTransform()
        self.scene().setSceneRect(self._placeholder.boundingRect())

    def set_pixmap(self, pixmap):
        self._placeholder.setVisible(False)
        self._item.setVisible(True)
        self._item.setPixmap(pixmap)
        rect = self._item.boundingRect().adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN)
        self.scene().setSceneRect(rect)
        self._apply_zoom()

    def has_pixmap(self):
        return self._item.isVisible() and not self._item.pixmap().isNull()

    def available_size(self):
        """Logical size a plot should be rendered at to fit exactly."""
        vp = self.viewport().size()
        return max(100, vp.width() - 2 * MARGIN - 2), max(80, vp.height() - 2 * MARGIN - 2)

    def _apply_zoom(self):
        if not self.has_pixmap():
            return
        if self.fit:
            vp = self.viewport().size()
            sr = self.sceneRect()
            z = min(vp.width() / sr.width(), vp.height() / sr.height())
            if 0.96 < z < 1.04:
                z = 1.0  # rendered for this panel: show pixel-exact
            self.resetTransform()
            self.scale(z, z)
            self.centerOn(sr.center())
            self.zoom = z
        else:
            self.resetTransform()
            self.scale(self.zoom, self.zoom)
        self.zoomChanged.emit(self.zoom)

    def set_fit(self):
        self.fit = True
        self._apply_zoom()

    def set_zoom(self, z):
        self.fit = False
        self.zoom = max(0.1, min(8.0, z))
        self._apply_zoom()

    def zoom_by(self, factor):
        self.set_zoom(self.zoom * factor)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit:
            self._apply_zoom()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_by(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.fit:
            self.set_zoom(1.0)
        else:
            self.set_fit()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Left, Qt.Key_PageUp):
            self.navigate.emit(-1)
        elif key in (Qt.Key_Right, Qt.Key_PageDown):
            self.navigate.emit(1)
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_by(1.25)
        elif key == Qt.Key_Minus:
            self.zoom_by(0.8)
        elif key == Qt.Key_0:
            self.set_fit()
        else:
            super().keyPressEvent(event)


class PlotEntry:
    __slots__ = ("id", "path", "shell", "pid", "w", "h", "dpr", "pixmap", "stale")

    def __init__(self, plot_id, shell, pid):
        self.id, self.shell, self.pid = plot_id, shell, pid
        self.path, self.w, self.h, self.dpr = "", 0, 0, 1.0
        self.pixmap = None
        self.stale = False

    def load(self):
        if self.pixmap is None and self.path and os.path.exists(self.path):
            pm = QtGui.QPixmap(self.path)
            pm.setDevicePixelRatio(self.dpr)
            self.pixmap = pm
        return self.pixmap

    def kernel(self):
        """The kernel that can still re-render this plot, or None."""
        try:
            k = self.shell.kernel
        except RuntimeError:  # shell widget deleted
            return None
        if self.stale or k.info.get("pid") != self.pid or not k.is_alive:
            return None
        return k


class ExportDialog(QtWidgets.QDialog):
    PRESETS = [
        ("Current panel size", None),
        ("Presentation slide, 16:9 (10 x 5.625 in)", (10, 5.625)),
        ("Journal, single column (3.5 x 3 in)", (3.5, 3.0)),
        ("Journal, double column (7 x 4.5 in)", (7.0, 4.5)),
        ("A4 landscape (11.7 x 8.3 in)", (11.69, 8.27)),
        ("Square (6 x 6 in)", (6.0, 6.0)),
    ]
    FORMATS = [("PNG image", "png"), ("PDF (vector)", "pdf"), ("SVG (vector)", "svg"),
               ("JPEG image", "jpg"), ("TIFF image", "tiff")]

    def __init__(self, panel_size, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export plot")
        self.panel_size = panel_size  # logical px
        self.cfg = get_config()
        form = QtWidgets.QFormLayout(self)
        self.preset = QtWidgets.QComboBox()
        for name, _ in self.PRESETS:
            self.preset.addItem(name)
        self.preset.currentIndexChanged.connect(self._preset)
        form.addRow("Size preset", self.preset)
        self.fmt = QtWidgets.QComboBox()
        for name, ext in self.FORMATS:
            self.fmt.addItem(name, ext)
        self.fmt.currentIndexChanged.connect(self._update)
        form.addRow("Format", self.fmt)
        self.width = QtWidgets.QDoubleSpinBox(decimals=2, minimum=1, maximum=60, singleStep=0.5,
                                              suffix=" in")
        self.height = QtWidgets.QDoubleSpinBox(decimals=2, minimum=1, maximum=60, singleStep=0.5,
                                               suffix=" in")
        self.dpi = QtWidgets.QSpinBox(minimum=50, maximum=1200, singleStep=50, suffix=" dpi")
        self.dpi.setValue(int(self.cfg.get("plotExportDpi", 300)))
        for w in (self.width, self.height, self.dpi):
            w.valueChanged.connect(self._update)
        form.addRow("Width", self.width)
        form.addRow("Height", self.height)
        form.addRow("Resolution", self.dpi)
        self.info = QtWidgets.QLabel()
        self.info.setStyleSheet("color: gray;")
        form.addRow("", self.info)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        save = buttons.addButton("Save as...", QtWidgets.QDialogButtonBox.AcceptRole)
        save.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._preset(0)

    def _preset(self, i):
        size = self.PRESETS[i][1]
        if size is None:
            w, h = self.panel_size
            size = (w / 96, h / 96)
        self.width.setValue(size[0])
        self.height.setValue(size[1])
        self._update()

    def _update(self):
        ext = self.fmt.currentData()
        raster = ext not in ("pdf", "svg")
        self.dpi.setEnabled(raster)
        if raster:
            self.info.setText(f"{round(self.width.value() * self.dpi.value())} x "
                              f"{round(self.height.value() * self.dpi.value())} pixels")
        else:
            self.info.setText("Vector output: sharp at any size")

    def values(self):
        """(ext, width px@96, height px@96, dpi)"""
        self.cfg["plotExportDpi"] = self.dpi.value()
        return (self.fmt.currentData(), self.width.value() * 96, self.height.value() * 96,
                self.dpi.value())


class PlotWindow(QtWidgets.QWidget):
    """A large, separate window for one plot, re-rendered to fit the window."""

    def __init__(self, tool, entry):
        super().__init__(tool, Qt.Window)
        self.tool = tool
        self.entry = entry
        self.setWindowTitle(f"Plot {entry.id}")
        self.resize(900, 650)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = PlotCanvas(self)
        layout.addWidget(self.canvas)
        pm = entry.load()
        if pm is not None:
            self.canvas.set_pixmap(pm)
        self._file = None
        self._timer = QtCore.QTimer(self, singleShot=True, interval=350)
        self._timer.timeout.connect(self.render)
        self.setAttribute(Qt.WA_DeleteOnClose)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._timer.start()

    def render(self):
        k = self.entry.kernel()
        if k is None:
            return
        w, h = self.canvas.available_size()
        dpr = self.devicePixelRatioF()
        fd, self._file = tempfile.mkstemp(suffix=".png", prefix="ryzo_popout_")
        os.close(fd)
        if not k.save_plot(self.entry.id, self._file.replace("\\", "/"), w, h, 96 * dpr):
            self._timer.start(800)  # R is busy; try again shortly
            return
        self._dpr = dpr

    def on_saved(self, msg):
        if not self._file or os.path.normcase(msg.get("path", "")) != os.path.normcase(
                self._file.replace("\\", "/")):
            return False
        if msg.get("ok"):
            pm = QtGui.QPixmap(self._file)
            pm.setDevicePixelRatio(self._dpr)
            self.canvas.set_pixmap(pm)
        try:
            os.remove(self._file)
        except OSError:
            pass
        self._file = None
        return True


class PlotsTool(QtWidgets.QWidget):
    title = "Plots"

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.cfg = get_config()
        self.entries = []
        self.index = -1
        self._windows = []
        self._pending_export = None
        self._last_render_request = 0

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        tb = QtWidgets.QToolBar(self)
        tb.setIconSize(QtCore.QSize(16, 16))
        style = self.style()
        S = QtWidgets.QStyle

        def action(icon, tip, slot, text=None):
            a = tb.addAction(style.standardIcon(icon) if icon is not None else QtGui.QIcon(),
                             text or "")
            if slot is not None:
                a.triggered.connect(lambda _checked=False: slot())
            a.setToolTip(tip)
            return a

        self.prev_act = action(S.SP_ArrowBack, "Previous plot (Left)", lambda: self.step(-1))
        self.next_act = action(S.SP_ArrowForward, "Next plot (Right)", lambda: self.step(1))
        self.label = QtWidgets.QLabel(" 0 / 0 ")
        tb.addWidget(self.label)
        tb.addSeparator()
        action(None, "Fit to panel (0, or double-click)", lambda: self.canvas.set_fit(), "Fit")
        action(None, "Actual size (100%)", lambda: self.canvas.set_zoom(1.0), "1:1")
        action(None, "Zoom in (Ctrl+wheel, +)", lambda: self.canvas.zoom_by(1.25), "+")
        action(None, "Zoom out (Ctrl+wheel, -)", lambda: self.canvas.zoom_by(0.8), "−")
        self.zoom_label = QtWidgets.QLabel("")
        self.zoom_label.setMinimumWidth(42)
        tb.addWidget(self.zoom_label)
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.style_act = action(None, "Modern style for base graphics (las = 1, L-shaped box, "
                                      "softer axes, filled points).\nApplies to new plots.",
                                None, "Style")
        self.style_act.setCheckable(True)
        self.style_act.setChecked(self.cfg.get("plotStyle", True))
        self.style_act.toggled.connect(self._toggle_style)
        self.thumbs_act = action(None, "Show thumbnails of all plots", None, "Thumbs")
        self.thumbs_act.setCheckable(True)
        self.thumbs_act.setChecked(self.cfg.get("plotThumbnails", True))
        self.thumbs_act.toggled.connect(self._toggle_thumbs)
        tb.addSeparator()
        action(S.SP_TitleBarMaxButton, "Open in a separate, resizable window", self.pop_out)
        action(S.SP_FileDialogDetailedView, "Copy to clipboard", self.copy)
        action(S.SP_DialogSaveButton, "Export (PNG, PDF, SVG, JPEG, TIFF)...", self.export)
        action(S.SP_TrashIcon, "Remove this plot (Delete)", self.remove)
        action(S.SP_DialogDiscardButton, "Remove all plots", self.clear)
        layout.addWidget(tb)

        self.canvas = PlotCanvas(self)
        self.canvas.navigate.connect(self.step)
        self.canvas.zoomChanged.connect(lambda z: self.zoom_label.setText(f"{round(z * 100)}%"))
        self.canvas.setContextMenuPolicy(Qt.CustomContextMenu)
        self.canvas.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.canvas, 1)

        self.thumbs = QtWidgets.QListWidget(self)
        self.thumbs.setViewMode(QtWidgets.QListView.IconMode)
        self.thumbs.setFlow(QtWidgets.QListView.LeftToRight)
        self.thumbs.setWrapping(False)
        self.thumbs.setMovement(QtWidgets.QListView.Static)
        self.thumbs.setIconSize(QtCore.QSize(100, 70))
        self.thumbs.setSpacing(3)
        self.thumbs.setFixedHeight(94)
        self.thumbs.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.thumbs.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.thumbs.currentRowChanged.connect(self._thumb_selected)
        self.thumbs.setVisible(self.thumbs_act.isChecked())
        layout.addWidget(self.thumbs)

        QtGui.QShortcut(QtGui.QKeySequence.Delete, self.canvas, self.remove)
        QtGui.QShortcut(QtGui.QKeySequence.Copy, self.canvas, self.copy)

        self._resize_timer = QtCore.QTimer(self, singleShot=True, interval=300)
        self._resize_timer.timeout.connect(self._fit_render)
        self._update()

    # ------------------------------------------------------------- messages --
    def on_message(self, shell, msg):
        t = msg.get("type")
        if t == "plot":
            self._on_plot(shell, msg)
        elif t == "plot_missing":
            e = self._find(shell, msg.get("id"))
            if e is not None:
                e.stale = True
        elif t == "saved":
            for w in list(self._windows):
                try:
                    if w.on_saved(msg):
                        return
                except RuntimeError:
                    self._windows.remove(w)
            self._on_saved(msg)
        elif t == "hello":
            # a new R process: plots of an earlier process can no longer be re-rendered
            if not self.cfg.get("plotStyle", True):
                shell.kernel.set_plot_style(False)
            self._sync_size(shell)
        elif t == "ready":
            if shell is self.main.current_shell():
                self._sync_size(shell)
            self._resize_timer.start(60)

    def _find(self, shell, plot_id):
        pid = shell.kernel.info.get("pid")
        for e in self.entries:
            if e.id == plot_id and e.shell is shell and e.pid == pid:
                return e
        return None

    def _on_plot(self, shell, msg):
        path = msg.get("path")
        if not path or not os.path.exists(path):
            return
        e = self._find(shell, msg.get("id"))
        is_new = e is None
        if is_new:
            if msg.get("rerender"):
                return
            e = PlotEntry(msg.get("id"), shell, shell.kernel.info.get("pid"))
            self.entries.append(e)
            self.thumbs.addItem(QtWidgets.QListWidgetItem())
            while len(self.entries) > 100:
                self.entries.pop(0)
                self.thumbs.takeItem(0)
        e.path = path
        e.w, e.h, e.dpr = msg.get("width", 0), msg.get("height", 0), msg.get("dpr", 1.0)
        e.pixmap = None
        e.load()
        self._update_thumb(self.entries.index(e))
        if not msg.get("rerender"):
            # new plot, or an update of a plot (abline after plot): show it
            self.index = self.entries.index(e)
            self.main.show_tool(self, focus=False)
            self._update()
        elif self.index >= 0 and self.entries[self.index] is e:
            self._update()

    # ------------------------------------------------------------- display --
    def current(self):
        return self.entries[self.index] if 0 <= self.index < len(self.entries) else None

    def step(self, d):
        if self.entries:
            self.index = max(0, min(len(self.entries) - 1, self.index + d))
            self._update()

    def _thumb_selected(self, row):
        if 0 <= row < len(self.entries) and row != self.index:
            self.index = row
            self._update()

    def _update(self):
        n = len(self.entries)
        self.label.setText(f" {self.index + 1} / {n} " if n else " 0 / 0 ")
        self.prev_act.setEnabled(self.index > 0)
        self.next_act.setEnabled(self.index < n - 1)
        e = self.current()
        if e is None or e.load() is None:
            self.canvas.show_placeholder("No plots yet.\nRun e.g.  plot(cars)  in a shell.")
            self.zoom_label.setText("")
        else:
            self.canvas.set_pixmap(e.pixmap)
            self._resize_timer.start(10)
        self.thumbs.blockSignals(True)
        self.thumbs.setCurrentRow(self.index)
        self.thumbs.blockSignals(False)
        if 0 <= self.index < self.thumbs.count():
            self.thumbs.scrollToItem(self.thumbs.item(self.index))

    def _update_thumb(self, row):
        e = self.entries[row]
        item = self.thumbs.item(row)
        pm = e.load()
        if item is None or pm is None:
            return
        icon_size = self.thumbs.iconSize() * self.devicePixelRatioF()
        thumb = pm.scaled(icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        thumb.setDevicePixelRatio(self.devicePixelRatioF())
        item.setIcon(QtGui.QIcon(thumb))
        item.setToolTip(f"Plot {row + 1}")

    # ------------------------------------------------- fitting to the panel --
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_thumb_visibility()
        self._resize_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._resize_timer.start(50)

    def _sync_size(self, shell):
        w, h = self.canvas.available_size()
        if self.isVisible() and w > 120 and h > 100:
            shell.kernel.set_plot_size(w, h, self.canvas.devicePixelRatioF())

    def _fit_render(self):
        """Re-render the shown plot so it exactly fits the panel."""
        if not self.isVisible():
            return
        shell = self.main.current_shell()
        if shell is not None and shell.kernel.state == "ready":
            self._sync_size(shell)
        e = self.current()
        if e is None or not self.canvas.fit:
            return
        k = e.kernel()
        if k is None:
            return
        w, h = self.canvas.available_size()
        dpr = self.canvas.devicePixelRatioF()
        if abs(e.w - w) <= 6 and abs(e.h - h) <= 6 and abs(e.dpr - dpr) < 0.01:
            return
        if time.time() - self._last_render_request < 0.15:
            self._resize_timer.start(200)
            return
        if k.render_plot(e.id, w, h, dpr):
            self._last_render_request = time.time()
        # if R is busy, the next "ready" message retries

    # -------------------------------------------------------------- actions --
    def _toggle_style(self, on):
        self.cfg["plotStyle"] = on
        for shell in self.main.shells.shells():
            shell.kernel.set_plot_style(on)

    def _toggle_thumbs(self, on):
        self.cfg["plotThumbnails"] = on
        self._update_thumb_visibility()

    def _update_thumb_visibility(self):
        # in a short panel the plot itself gets all the room
        show = self.thumbs_act.isChecked() and self.height() >= 300
        if self.thumbs.isVisible() != show:
            self.thumbs.setVisible(show)

    def copy(self):
        e = self.current()
        if e is not None and e.load() is not None:
            QtWidgets.QApplication.clipboard().setPixmap(e.pixmap)

    def pop_out(self):
        e = self.current()
        if e is None:
            return
        w = PlotWindow(self, e)
        self._windows = [x for x in self._windows if self._alive(x)] + [w]
        w.show()
        if e.kernel() is None:
            w.setWindowTitle(w.windowTitle() + "  (R was restarted: cannot re-render)")

    @staticmethod
    def _alive(w):
        try:
            w.isVisible()
            return True
        except RuntimeError:
            return False

    def export(self):
        e = self.current()
        if e is None:
            return
        dlg = ExportDialog(self.canvas.available_size(), self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        ext, w, h, dpi = dlg.values()
        start = os.path.join(self.cfg.get("lastDir") or os.path.expanduser("~"), f"plot.{ext}")
        filters = {"png": "PNG image (*.png)", "pdf": "PDF (*.pdf)", "svg": "SVG (*.svg)",
                   "jpg": "JPEG image (*.jpg *.jpeg)", "tiff": "TIFF image (*.tif *.tiff)"}
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export plot", start, filters[ext])
        if not filename:
            return
        if not os.path.splitext(filename)[1]:
            filename += "." + ext
        k = e.kernel()
        if k is None:
            # R restarted since: we can only save the image we have
            if filename.lower().endswith(".png") and e.load() is not None:
                e.pixmap.save(filename)
                return
            QtWidgets.QMessageBox.information(
                self, "Export plot", "R has been restarted since this plot was made, so it can "
                "only be saved as the PNG shown. Re-run the code to export other formats.")
            return
        self._pending_export = filename.replace("\\", "/")
        if not k.save_plot(e.id, self._pending_export, w, h, dpi):
            self._pending_export = None
            QtWidgets.QMessageBox.information(self, "Export plot",
                                              "R is busy. Try again when it has finished.")

    def _on_saved(self, msg):
        if self._pending_export and msg.get("path") == self._pending_export:
            if not msg.get("ok"):
                QtWidgets.QMessageBox.warning(self, "Export plot",
                                              f"Could not save {self._pending_export}")
            else:
                self.main.statusBar().showMessage(f"Plot saved to {self._pending_export}", 5000)
            self._pending_export = None

    def remove(self):
        e = self.current()
        if e is None:
            return
        k = e.kernel()
        if k is not None:
            k.remove_plot(e.id)
        del self.entries[self.index]
        self.thumbs.takeItem(self.index)
        self.index = min(self.index, len(self.entries) - 1)
        self._update()

    def clear(self):
        for shell in self.main.shells.shells():
            shell.kernel.remove_plot("all")
        self.entries = []
        self.thumbs.clear()
        self.index = -1
        self._update()

    def _context_menu(self, pos):
        if self.current() is None:
            return
        menu = QtWidgets.QMenu(self)
        menu.addAction("Copy to clipboard", self.copy)
        menu.addAction("Export...", self.export)
        menu.addAction("Open in separate window", self.pop_out)
        menu.addSeparator()
        menu.addAction("Fit to panel", self.canvas.set_fit)
        menu.addAction("Actual size", lambda: self.canvas.set_zoom(1.0))
        menu.addSeparator()
        menu.addAction("Remove", self.remove)
        menu.exec(self.canvas.mapToGlobal(pos))
