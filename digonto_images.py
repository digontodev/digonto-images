#!/usr/bin/env python3
"""Digonto Images - layers, selections, brushes, adjustments and filters. A photo editor in the Digonto look."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import QPointF, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QImage, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QDockWidget, QHBoxLayout, QFileDialog, QInputDialog, QLabel, QMainWindow, QMessageBox, QTabBar,
                               QToolBar, QToolButton, QVBoxLayout, QWidget)

import digonto_ui as ui
from imgkit import __version__ as VERSION
from imgkit import adjlayers, adjust, arr, dialogs, filters, fileio, fx, ops
from imgkit.canvas import Canvas
from imgkit.doc import Document, Layer
from imgkit.panels import ColorPanel, HistoryPanel, LayersPanel, Navigator, OptionsBar
from imgkit.select import Selection
from imgkit.state import State
from imgkit.toolpanel import PropertiesPanel, ToolsPanel
from imgkit.tools import place_like, render_text

APP_NAME = "Digonto Images"
SLUG = "digonto-images"

TOOL_LIST = [("move", "Move", "V"), ("select", "Select", "M"), ("wand", "Wand", "W"), ("brush", "Brush", "B"), ("eraser", "Eraser", "E"),
             ("fill", "Fill", "K"), ("gradient", "Gradient", "G"), ("eyedropper", "Picker", "I"), ("text", "Text", "T"),
             ("shape", "Shape", "U"), ("crop", "Crop", "C"), ("hand", "Hand", "H"), ("zoom", "Zoom", "Z")]


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.icon = ui.app_icon(HERE, SLUG)
        self.setWindowIcon(self.icon)
        self.state = State()
        self.docs = []
        self.untitled = 0
        self.canvas = Canvas(self.state)
        self.canvas.info.connect(self._info)
        self.canvas.message.connect(lambda m: self.statusBar().showMessage(m, 4000))
        self.canvas.textRequested.connect(self.new_text)
        self.canvas.textEditRequested.connect(self.edit_text)
        self.setAcceptDrops(True)

        self.tabs = QTabBar()
        self.tabs.setTabsClosable(True)
        self.tabs.setExpanding(False)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.options = OptionsBar(self.state)
        self.options._stable()

        work = QWidget()
        v = QVBoxLayout(work)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.tabs)
        v.addWidget(self.canvas, 1)
        self.start = ui.StartScreen(
            "Photo editing with layers, selections and filters",
            [("New picture", "new", self.new_dialog, True), ("Open …", "open", self.open_dialog, False)],
            "or drop pictures here (JPG, PNG, PSD, WEBP …)", lambda: ui.recent_paths(SLUG), self.open_path)
        from PySide6.QtWidgets import QStackedWidget
        col = QStackedWidget()
        col.addWidget(self.start)
        col.addWidget(work)
        self.centre = col
        self._toolbar()
        body = QWidget()
        bl = QHBoxLayout(body)          # tools sit under the header, next to the picture
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(col, 1)
        # a window inside the window: the side panels dock here, so they start below the header too
        self.inner = QMainWindow()
        self.inner.setWindowFlags(Qt.Widget)
        self.inner.setCentralWidget(body)
        body = self.inner
        hd = ui.make_header(APP_NAME, "Photo editing with layers, selections and filters", self.icon, self.about)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(hd)
        cl.addWidget(self.options)          # the option bar spans the whole window; the side panels start below it
        cl.addWidget(body, 1)
        self.setCentralWidget(central)

        self._docks()
        self._menus()
        self.status_lbl = QLabel("")
        self.statusBar().addPermanentWidget(self.status_lbl)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self._refresh_panels)
        self.state.changed.connect(self._state_changed)
        ui.fit_window(self, 1400, 900)
        self._enable()

    # ------------------------------------------------------------------ pieces
    def _toolbar(self):
        self.tool_bar = ToolsPanel(self.state, self)
        # the Digonto file icons sit at the top of the tool column (same order as every Digonto program)
        from PySide6.QtWidgets import QFrame, QToolButton
        lay = self.tool_bar.widget().layout()
        self.file_buttons = {}
        items = [("new", "new", "New picture (Ctrl+N)", self.new_dialog), ("open", "open", "Open (Ctrl+O)", self.open_dialog),
                 ("save", "save", "Save project (Ctrl+S)", self.save), ("export", "export", "Export picture (Ctrl+E)", self.export),
                 ("print", "print", "Print (Ctrl+P)", self.print_doc)]
        for k, (key, kind, tip, fn) in enumerate(items):
            b = QToolButton()
            b.setIcon(ui.line_icon(kind, 22))
            b.setIconSize(QSize(22, 22))
            b.setFixedSize(40, 36)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setStyleSheet("QToolButton{border:none; border-radius:5px;} QToolButton:hover{background:#EFE7F5;}")
            b.clicked.connect(lambda _=False, f=fn: f())
            lay.insertWidget(k, b)
            self.file_buttons[key] = b
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{ui.LINE}; margin: 3px 4px;")
        lay.insertWidget(len(items), line)

    def _dock(self, title, widget, area=Qt.RightDockWidgetArea, scroll=True):
        d = QDockWidget(title, self.inner)
        d.setObjectName(title)
        if scroll:          # a panel that does not fit scrolls, so the window can always shrink or go full screen
            from PySide6.QtWidgets import QScrollArea
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QScrollArea.NoFrame)
            sa.setWidget(widget)
            sa.setMinimumSize(120, 60)
            widget = sa
        d.setWidget(widget)
        self.inner.addDockWidget(area, d)
        return d

    def _docks(self):
        from PySide6.QtWidgets import QTabWidget
        self.navigator = Navigator(self.canvas)
        self.color_panel = ColorPanel(self.state)
        self.layers = LayersPanel(self.cur_doc)
        self.history = HistoryPanel(self.cur_doc)
        self.props = PropertiesPanel(self.cur_doc)
        self.props.text_hook = self.text_props
        # Photoshop-style column: every panel is its own block (arrow on the right collapses it, drag the header to move it)
        self.stack = ui.PanelStack("Digonto", "Images")
        self.sections = {}

        def section(title, w, minh):
            self.sections[title] = self.stack.add(title, w)
        section("Navigator", self.navigator.box, 150)
        section("Properties", self.props, 250)
        section("Colour", self.color_panel, 300)
        section("History", self.history, 200)
        section("Layers", self.layers, 330)
        self.stack.restore()
        ui.shrinkable(self.stack)
        self.layers.list.setMinimumHeight(170)
        self.d_side = QDockWidget("Panels", self.inner)
        self.d_side.setObjectName("Panels")
        self.d_side.setTitleBarWidget(QWidget())
        self.d_side.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.d_side.setWidget(ui.ScrollColumn(self.stack))
        self.inner.addDockWidget(Qt.RightDockWidgetArea, self.d_side)
        self.d_tools = QDockWidget("Tools", self.inner)
        self.d_tools.setObjectName("Tools")
        self.d_tools.setWidget(self.tool_bar)
        self.d_tools.setTitleBarWidget(QWidget())          # no title bar, no moving: a plain column
        self.d_tools.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.inner.addDockWidget(Qt.LeftDockWidgetArea, self.d_tools)
        self.inner.resizeDocks([self.d_side], [ui.dock_width_for(self.width(), self.stack.minimumSizeHint().width())], Qt.Horizontal)
        self.inner.resizeDocks([self.d_tools], [self.tool_bar.width()], Qt.Horizontal)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "d_side"):          # side panels follow the window size
            self.inner.resizeDocks([self.d_side], [ui.dock_width_for(self.width(), self.stack.minimumSizeHint().width())], Qt.Horizontal)

    def act(self, menu, text, sc=None, fn=None, enabled_doc=True):
        a = QAction(text, self)
        if sc:
            a.setShortcut(sc)
        if fn:
            a.triggered.connect(lambda _=False: fn())
        menu.addAction(a)
        if enabled_doc:
            self._doc_actions.append(a)
        return a

    def _menus(self):
        self._doc_actions = []
        mb = self.menuBar()
        act = self.act
        # File
        fm = ui.file_menu(self, [("New…", "Ctrl+N", self.new_dialog), ("Open…", "Ctrl+O", self.open_dialog)])
        # build the File menu in the right order by inserting before Exit
        first_exit = [a for a in fm.actions() if a.text() == "Exit"][0]
        for text, sc, fn, needs in (("Save project", "Ctrl+S", self.save, True), ("Save project as…", "Ctrl+Shift+S", self.save_as, True),
                                    ("Export picture…", "Ctrl+Alt+Shift+W", self.export, True), ("Print…", "Ctrl+P", self.print_doc, True), ("Two sides on one page (ID card)…", "", self.two_sides, False), ("Close project", "Ctrl+W", lambda: self.close_tab(self.tabs.currentIndex()), True)):
            a = QAction(text, self)
            a.setShortcut(sc)
            a.triggered.connect(lambda _=False, fn=fn: fn())
            fm.insertAction(first_exit, a)
            if needs:
                self._doc_actions.append(a)
        fm.insertSeparator(first_exit)
        # Edit
        em = mb.addMenu("Edit")
        self.a_undo = act(em, "Undo", "Ctrl+Z", lambda: self.cur_doc().undo())
        self.a_redo = act(em, "Redo", "Ctrl+Shift+Z", lambda: self.cur_doc().redo())
        self.a_redo.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        em.addSeparator()
        act(em, "Cut", "Ctrl+X", lambda: self.copy(True))
        act(em, "Copy", "Ctrl+C", lambda: self.copy(False))
        act(em, "Paste as new layer", "Ctrl+V", self.paste)
        clr = act(em, "Clear selected area", None, lambda: ops.clear_selection_pixels(self.cur_doc()))
        clr.setShortcuts([QKeySequence("Delete"), QKeySequence("Backspace")])      # the Mac "delete" key is Backspace
        act(em, "Fill with front colour", "Alt+Backspace", self.fill_front)
        act(em, "Fill with back colour", "Ctrl+Backspace", self.fill_back)
        em.addSeparator()
        act(em, "Layer via copy (or duplicate layer)", "Ctrl+J", lambda: ops.duplicate_or_copy(self.cur_doc()))
        act(em, "Layer via cut", "Ctrl+Shift+J", lambda: ops.new_from_selection(self.cur_doc(), True) or self._no_sel())
        act(em, "Free transform", "Ctrl+T", lambda: (self.state.set(tool="transform"), self.canvas.set_tool("transform")) if self.state.tool != "transform" else self.canvas.set_tool("transform"))
        act(em, "Transform layer (numbers)…", None, self.transform)
        # Select
        sm = mb.addMenu("Select")
        act(sm, "All", "Ctrl+A", lambda: self.sel_set(lambda d: Selection.all(d.w, d.h), "Select all"))
        act(sm, "None", "Ctrl+D", lambda: self._deselect())
        act(sm, "Reselect", "Ctrl+Shift+D", lambda: self._reselect())
        act(sm, "Inverse", "Ctrl+Shift+I", lambda: self.sel_set(lambda d: d.selection.inverted() if d.selection is not None else None, "Invert selection"))
        act(sm, "Colour range…", None, self.colour_range)
        sm.addSeparator()
        act(sm, "Soft edge (feather)…", "Shift+F6", lambda: self.sel_num("Soft edge", "Radius (px)", 5, 1, 300, lambda s, n: s.feathered(n)))
        act(sm, "Grow…", None, lambda: self.sel_num("Grow", "Pixels", 5, 1, 200, lambda s, n: s.grown(n)))
        act(sm, "Shrink…", None, lambda: self.sel_num("Shrink", "Pixels", 5, 1, 200, lambda s, n: s.grown(-n)))
        act(sm, "Smooth…", None, lambda: self.sel_num("Smooth", "Radius (px)", 4, 1, 100, lambda s, n: s.smoothed(n)))
        # Image
        im = mb.addMenu("Image")
        act(im, "Image size…", "Ctrl+Alt+I", self.image_size)
        act(im, "Canvas size…", "Ctrl+Alt+C", self.canvas_size)
        act(im, "Crop to selection", None, self.crop_selection)
        im.addSeparator()
        act(im, "Rotate 90° right", None, lambda: ops.rotate90(self.cur_doc(), True) or self.canvas.fit())
        act(im, "Rotate 90° left", None, lambda: ops.rotate90(self.cur_doc(), False) or self.canvas.fit())
        act(im, "Rotate 180°", None, lambda: (ops.rotate90(self.cur_doc(), True), ops.rotate90(self.cur_doc(), True)))
        act(im, "Flip horizontal", None, lambda: ops.flip(self.cur_doc(), True))
        act(im, "Flip vertical", None, lambda: ops.flip(self.cur_doc(), False))
        act(im, "Rotate by any angle (straighten)…", None, self.straighten)
        # Layer
        lm = mb.addMenu("Layer")
        act(lm, "New layer", "Ctrl+Shift+N", lambda: ops.add_layer(self.cur_doc()))
        act(lm, "Duplicate layer", None, lambda: ops.duplicate_layer(self.cur_doc()))
        act(lm, "Delete layer", None, lambda: ops.delete_layer(self.cur_doc()))
        act(lm, "Merge down", "Ctrl+E", lambda: ops.merge_down(self.cur_doc()))
        act(lm, "Create / release clipping mask", "Ctrl+Alt+G", lambda: ops.toggle_clip(self.cur_doc()) or self.statusBar().showMessage("The bottom layer can't be clipped", 3000))
        lm.addSeparator()
        mk = lm.addMenu("Layer mask")
        self._doc_actions.append(mk.menuAction())
        for txt, fn in (("Show all", lambda d: ops.add_mask(d, "reveal")), ("Hide all", lambda d: ops.add_mask(d, "hide")),
                        ("From selection", lambda d: ops.add_mask(d, "selection")), (None, None), ("Invert", ops.invert_mask),
                        ("Switch on / off", ops.toggle_mask), ("Apply to layer", lambda d: ops.delete_mask(d, True)), ("Delete", lambda d: ops.delete_mask(d, False))):
            if txt is None:
                mk.addSeparator()
            else:
                mk.addAction(txt, lambda fn=fn: fn(self.cur_doc()))
        act(lm, "Layer style (shadow, glow, outline)…", None, lambda: self.layers._style())
        na = lm.addMenu("New adjustment layer")
        self._doc_actions.append(na.menuAction())
        for kind, (nm, sp, _f) in adjlayers.KINDS.items():
            na.addAction(nm + ("…" if sp else ""), lambda kind=kind: self.layers._add_adj(kind))
        lm.addSeparator()
        act(lm, "Merge visible", "Ctrl+Shift+E", lambda: ops.merge_visible(self.cur_doc()))
        act(lm, "Stamp visible (new layer from everything)", "Ctrl+Alt+Shift+E", lambda: ops.stamp_visible(self.cur_doc()))
        act(lm, "Flatten picture", None, lambda: ops.flatten(self.cur_doc()))
        lm.addSeparator()
        act(lm, "Edit text…", None, self.edit_text)
        act(lm, "Flip layer horizontally", None, lambda: ops.flip_layer(self.cur_doc(), True))
        act(lm, "Flip layer vertically", None, lambda: ops.flip_layer(self.cur_doc(), False))
        act(lm, "Fill layer with front colour", None, lambda: ops.fill_layer(self.cur_doc(), self.state.fg))
        # Adjust
        am = mb.addMenu("Adjust")
        self._adj = {}

        def dlg(title, spec, fn, fast=True):
            return lambda: self.run_dialog(dialogs.AdjustDialog(self, self.cur_doc(), title, spec, fn, fast))
        act(am, "Brightness / Contrast…", None, dlg("Brightness / Contrast", [("brightness", "Brightness", -100, 100, 0), ("contrast", "Contrast", -100, 100, 0)],
                                                     lambda a, brightness, contrast: adjust.brightness_contrast(a, brightness, contrast)))
        act(am, "Levels…", "Ctrl+L", lambda: self.run_dialog(dialogs.levels_dialog(self, self.cur_doc())))
        act(am, "Curves…", "Ctrl+M", lambda: self.run_dialog(dialogs.curves_dialog(self, self.cur_doc())))
        act(am, "Hue / Saturation…", "Ctrl+U", dlg("Hue / Saturation", [("hue", "Hue", -180, 180, 0), ("saturation", "Saturation", -100, 100, 0), ("lightness", "Lightness", -100, 100, 0)],
                                                   lambda a, hue, saturation, lightness: adjust.hue_saturation(a, hue, saturation, lightness), False))
        act(am, "Vibrance…", None, dlg("Vibrance", [("amount", "Amount", -100, 100, 30)], lambda a, amount: adjust.vibrance(a, amount), False))
        act(am, "Temperature / Tint…", None, dlg("Temperature / Tint", [("temp", "Warm - cool", -100, 100, 0), ("tint", "Green - magenta", -100, 100, 0)],
                                                  lambda a, temp, tint: adjust.temperature(a, temp, tint)))
        act(am, "Colour balance…", "Ctrl+B", dlg("Colour balance", dialogs.COLOR_BALANCE, lambda a, **k: dialogs.color_balance_fn(a, **k)))
        am.addSeparator()
        act(am, "Auto levels", None, lambda: self.quick("Auto levels", adjust.auto_levels))
        act(am, "Auto contrast", None, lambda: self.quick("Auto contrast", adjust.auto_contrast))
        act(am, "Invert", "Ctrl+I", lambda: self.quick("Invert", adjust.invert))
        act(am, "Black and white (desaturate)", "Ctrl+Shift+U", lambda: self.quick("Black and white", adjust.desaturate))
        act(am, "Threshold…", None, dlg("Threshold", [("level", "Level", 0, 255, 128)], lambda a, level: adjust.threshold(a, level)))
        act(am, "Posterize…", None, dlg("Posterize", [("n", "Levels", 2, 16, 4)], lambda a, n: adjust.posterize(a, n)))
        act(am, "Sepia…", None, dlg("Sepia", [("amount", "Amount", 0, 100, 100)], lambda a, amount: adjust.sepia(a, amount)))
        act(am, "Gradient map (front to back colour)", None,
            lambda: self.quick("Gradient map", lambda a: adjust.gradient_map(a, arr.qcolor_rgba(self.state.fg)[:3], arr.qcolor_rgba(self.state.bg)[:3])))
        # Filter
        flm = mb.addMenu("Filter")
        act(flm, "Gaussian blur…", None, dlg("Gaussian blur", [("r", "Radius", 1, 100, 8)], lambda a, r: filters.gaussian_blur(a, r), False))
        act(flm, "Motion blur…", None, dlg("Motion blur", [("length", "Length", 2, 200, 25), ("angle", "Angle", -90, 90, 0)],
                                            lambda a, length, angle: filters.motion_blur(a, length, angle), False))
        act(flm, "Sharpen…", None, dlg("Sharpen", [("amount", "Amount %", 10, 400, 120), ("radius", "Radius", 1, 20, 2)],
                                        lambda a, amount, radius: filters.sharpen(a, amount, radius), False))
        act(flm, "Add noise…", None, dlg("Add noise", [("amount", "Amount", 1, 100, 15)], lambda a, amount: filters.add_noise(a, amount)))
        act(flm, "Remove noise (median)", None, lambda: self.quick("Remove noise", filters.median3))
        act(flm, "Pixelate…", None, dlg("Pixelate", [("size", "Cell size", 2, 100, 12)], lambda a, size: filters.pixelate(a, size)))
        act(flm, "Emboss", None, lambda: self.quick("Emboss", filters.emboss))
        act(flm, "Find edges", None, lambda: self.quick("Find edges", filters.find_edges))
        act(flm, "Vignette…", None, dlg("Vignette", [("amount", "Darkness", 0, 100, 50), ("size", "Size", 10, 100, 70)],
                                         lambda a, amount, size: filters.vignette(a, amount, size)))
        flm.addSeparator()
        act(flm, "Drop shadow (layer)…", None, dlg("Drop shadow", [("dx", "Across", -100, 100, 10), ("dy", "Down", -100, 100, 10), ("radius", "Soft", 0, 60, 10), ("opacity", "Opacity", 5, 100, 60)],
                                                    lambda a, dx, dy, radius, opacity: filters.drop_shadow(a, dx, dy, radius, (0, 0, 0), opacity), False))
        act(flm, "Outline (layer)…", None, dlg("Outline", [("width", "Width", 1, 60, 6)],
                                                lambda a, width: filters.outline(a, width, arr.qcolor_rgba(self.state.bg)[:3]), False))
        # View
        vm = mb.addMenu("View")
        act(vm, "Zoom in", "Ctrl+=", lambda: self.canvas.zoom_to(self.canvas.zoom * 1.25), False)
        act(vm, "Zoom out", "Ctrl+-", lambda: self.canvas.zoom_to(self.canvas.zoom / 1.25), False)
        act(vm, "Fit on screen", "Ctrl+0", self.canvas.fit, False)
        act(vm, "Actual size (100%)", "Ctrl+1", self.canvas.actual, False)
        vm.addSeparator()
        ta = self.d_side.toggleViewAction()
        ta.setText("Side panels (all)")
        vm.addAction(ta)
        wm = vm.addMenu("Windows")                      # turn single panels on and off
        from PySide6.QtCore import QSettings
        qs = QSettings("Digonto", "Images")
        for title, box in list(self.sections.items()) + [("Tools", self.d_tools)]:
            a = QAction(title, self, checkable=True)
            on = str(qs.value("panel_" + title, "true")).lower() != "false"
            a.setChecked(on)
            box.setVisible(on)

            def toggle(checked, b=box, t=title):
                b.setVisible(checked)
                QSettings("Digonto", "Images").setValue("panel_" + t, "true" if checked else "false")
            a.toggled.connect(toggle)
            ps_key = {"Layers": "F7", "Colour": "F6", "History": "Alt+F9"}.get(title)     # Photoshop's panel keys
            if ps_key:
                a.setShortcut(ps_key)
            wm.addAction(a)
        wm.addSeparator()
        wm.addAction(QAction("Show all panels", self, triggered=lambda: [x.setChecked(True) for x in wm.actions() if x.isCheckable()]))
        hm = mb.addMenu("Help")
        act(hm, "Keyboard shortcuts", None, self.shortcuts, False)
        act(hm, "About Digonto Images", None, self.about, False)

    # ------------------------------------------------------------------ helpers
    def cur_doc(self):
        i = self.tabs.currentIndex()
        return self.docs[i] if 0 <= i < len(self.docs) else None

    def _info(self, t):
        self.status_lbl.setText(t)

    def _no_sel(self):
        self.statusBar().showMessage("Make a selection first (Select or Wand tool).", 4000)

    def _enable(self):
        on = self.cur_doc() is not None
        for a in self._doc_actions:
            a.setEnabled(on)
        for k in ("save", "export", "print"):
            self.file_buttons[k].setEnabled(on)
        if on:
            self.centre.setCurrentIndex(1)
        else:
            self.start.refresh()
            self.centre.setCurrentIndex(0)

    def _state_changed(self, name):
        pass

    def run_dialog(self, d):
        d.exec()

    def quick(self, label, fn):
        ops.apply_array(self.cur_doc(), label, fn)

    # ------------------------------------------------------------------ documents
    def add_doc(self, doc, title=None):
        self.docs.append(doc)
        doc.on_change(self._schedule)
        i = self.tabs.addTab(title or os.path.basename(doc.path) or "Untitled")
        self.tabs.setCurrentIndex(i)
        self._enable()

    def _tab_changed(self, i):
        d = self.cur_doc()
        self.canvas.set_doc(d)
        self._refresh_panels()
        self._enable()

    def _schedule(self):
        self.refresh_timer.start(120)

    def _refresh_panels(self):
        d = self.cur_doc()
        self.layers.rebuild()
        self.history.rebuild()
        self.navigator.refresh()
        self.props.refresh()
        for i, dd in enumerate(self.docs):
            name = os.path.basename(dd.path) if dd.path else getattr(dd, "title", "Untitled")
            self.tabs.setTabText(i, name + (" *" if dd.dirty else ""))
        if d is not None:
            self.setWindowTitle(f"{os.path.basename(d.path) if d.path else getattr(d, 'title', 'Untitled')}{' *' if d.dirty else ''} - {APP_NAME}")
            self.a_undo.setEnabled(d.can_undo())
            self.a_redo.setEnabled(d.can_redo())
            self.a_undo.setText("Undo " + (d.history[d.pos - 1]["label"] if d.can_undo() else ""))
            self.a_redo.setText("Redo " + (d.history[d.pos]["label"] if d.can_redo() else ""))
        else:
            self.setWindowTitle(APP_NAME)

    def new_dialog(self):
        dlg = dialogs.NewDialog(self)
        if dlg.exec():
            w, h, c = dlg.values(self.state.fg)
            d = Document(w, h, c)
            if c is None:
                d.layers[0].name = "Layer 1"
            self.untitled += 1
            d.title = f"Untitled-{self.untitled}"
            self.add_doc(d, d.title)

    def open_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Open", "", fileio.OPEN_FILTER)
        for f in files:
            self.open_path(f)

    def open_path(self, path):
        try:
            d = fileio.open_any(path)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Cannot open this file.\n\n{path}\n\n{e}")
            return None
        if not path.lower().endswith((".dimg", ".pimg")):
            d.title = os.path.splitext(os.path.basename(path))[0]
        self.add_doc(d)
        ui.add_recent(SLUG, path)
        fams = [L.text.get("font") for L in d.layers if getattr(L, "text", None)]
        if any(not ui.font_installed(x) for x in fams):
            QTimer.singleShot(150, lambda: ui.note_missing_fonts(self, fams))
        return d

    def save(self):
        d = self.cur_doc()
        if d.path and d.path.lower().endswith((".dimg", ".pimg")):
            self._save_to(d, d.path)
        else:
            self.save_as()

    def save_as(self):
        d = self.cur_doc()
        start = (os.path.splitext(d.path)[0] if d.path else getattr(d, "title", "Untitled")) + ".dimg"
        p, _ = QFileDialog.getSaveFileName(self, "Save project", start, "Digonto Images project (*.dimg)")
        if p:
            if not p.lower().endswith((".dimg", ".pimg")):
                p += ".dimg"
            self._save_to(d, p)

    def _save_to(self, d, p):
        try:
            fileio.save_pimg(d, p)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Could not save.\n\n{e}")
            return
        ui.add_recent(SLUG, p)
        self.statusBar().showMessage("Saved " + p, 4000)
        self._refresh_panels()

    def print_doc(self):
        d = self.cur_doc()
        if d is None:
            return
        m = d.merged()
        img = QImage(m.size(), QImage.Format_RGB32)
        img.fill(QColor("white"))
        q = QPainter(img)
        q.drawImage(0, 0, m)
        q.end()

        def page(i, p, rect):
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(ui.fit_rect(img.width(), img.height(), rect), img)
        ui.print_pages(self, 1, page, getattr(d, "title", "Digonto Images"))

    def export(self):
        d = self.cur_doc()
        filt = ";;".join(f"{t} (*.{e})" for t, e in fileio.EXPORT_TYPES)
        base = os.path.splitext(d.path)[0] if d.path else getattr(d, "title", "picture")
        p, sel = QFileDialog.getSaveFileName(self, "Export picture", base + ".png", filt)
        if not p:
            return
        ext = os.path.splitext(p)[1].lower().lstrip(".")
        if not ext:
            ext = sel.split("*.")[-1].rstrip(")")
            p += "." + ext
        q, bg = 92, "#FFFFFF"
        if ext in ("jpg", "jpeg", "webp", "bmp"):
            ed = dialogs.ExportDialog(self, ext)
            if not ed.exec():
                return
            q, bg = ed.values()
        try:
            fileio.export_picture(d, p, q, bg)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Could not export.\n\n{e}")
            return
        ui.add_recent(SLUG, p)
        self.statusBar().showMessage("Exported " + p, 5000)

    def close_tab(self, i):
        if not (0 <= i < len(self.docs)):
            return True
        d = self.docs[i]
        if d.dirty:
            self.tabs.setCurrentIndex(i)
            r = QMessageBox.question(self, APP_NAME, f"Save changes to {os.path.basename(d.path) if d.path else getattr(d, 'title', 'this picture')}?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save:
                self.save()
                if d.dirty:
                    return False
        self.canvas.set_doc(None)
        self.docs.pop(i)
        self.tabs.blockSignals(True)
        self.tabs.removeTab(i)
        self.tabs.blockSignals(False)
        self._tab_changed(self.tabs.currentIndex())
        return True

    def closeEvent(self, ev):
        while self.docs:
            if not self.close_tab(len(self.docs) - 1):
                ev.ignore()
                return
        ev.accept()
        ui.force_exit_soon()

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
            if self.centre.currentIndex() == 0:
                self.start.set_dropping(True)

    def dragLeaveEvent(self, ev):
        self.start.set_dropping(False)

    def dropEvent(self, ev):
        self.start.set_dropping(False)
        for u in ev.mimeData().urls():
            if u.isLocalFile():
                self.open_path(u.toLocalFile())

    # ------------------------------------------------------------------ edit actions
    def copy(self, cut):
        d = self.cur_doc()
        img = d.flat_image(None)
        if d.selection is not None:
            b = d.selection.bbox()
            a = arr.to_array(img.copy(b))
            m = d.selection.mask[b.y():b.y() + b.height(), b.x():b.x() + b.width()]
            a[..., 3] = (a[..., 3].astype("float32") * m / 255.0).astype("uint8")
            img = arr.from_array(a)
        QApplication.clipboard().setImage(img.convertToFormat(QImage.Format_ARGB32))
        if cut:
            ops.clear_selection_pixels(d)

    def two_sides(self):
        import digonto_sides
        dlg = digonto_sides.SidesDialog(self, "images")
        if dlg.exec() != QDialog.Accepted or not dlg.items:
            return
        img = dlg.page_image(300)
        d = Document(img.width(), img.height(), None)
        d.layers[0].image = img.convertToFormat(arr.PM)
        d.layers[0].name = "Two sides"
        self.untitled += 1
        d.title = f"Untitled-{self.untitled}"
        self.add_doc(d, d.title)

    def paste(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            self.statusBar().showMessage("Nothing to paste.", 3000)
            return
        if self.cur_doc() is None:
            d = Document(img.width(), img.height(), None)
            d.layers[0].image = img.convertToFormat(arr.PM)
            d.layers[0].name = "Pasted"
            self.untitled += 1
            d.title = f"Untitled-{self.untitled}"
            self.add_doc(d, d.title)
        else:
            ops.paste_image(self.cur_doc(), img)

    def fill_front(self):
        from imgkit.tools import fill_mask
        d = self.cur_doc()
        import numpy as np
        mask = d.selection.mask if d.selection is not None else np.full((d.h, d.w), 255, np.uint8)
        fill_mask(self.canvas, "Fill", mask, QColor(self.state.fg))

    def fill_back(self):
        from imgkit.tools import fill_mask
        import numpy as np
        d = self.cur_doc()
        mask = d.selection.mask if d.selection is not None else np.full((d.h, d.w), 255, np.uint8)
        fill_mask(self.canvas, "Fill", mask, QColor(self.state.bg))

    def _deselect(self):
        d = self.cur_doc()
        if d is not None and d.selection is not None:
            d._last_selection = d.selection              # for Reselect (Ctrl+Shift+D)
        self.sel_set(lambda d: None, "Deselect")

    def _reselect(self):
        d = self.cur_doc()
        last = getattr(d, "_last_selection", None) if d is not None else None
        if last is not None:
            self.sel_set(lambda d: last, "Reselect")

    def sel_set(self, fn, label):
        d = self.cur_doc()
        self.canvas.set_selection(fn(d), label)

    def sel_num(self, title, label, default, lo, hi, fn):
        d = self.cur_doc()
        if d.selection is None:
            self._no_sel()
            return
        n, ok = QInputDialog.getInt(self, title, label, default, lo, hi)
        if ok:
            self.canvas.set_selection(fn(d.selection, n), title)

    def transform(self):
        d = self.cur_doc()
        dlg = dialogs.TransformDialog(self)
        if dlg.exec():
            ops.transform_layer(d, angle=dlg.ang.value(), sx=dlg.sx.value(), sy=dlg.sy.value())

    def image_size(self):
        d = self.cur_doc()
        dlg = dialogs.ImageSizeDialog(self, d.w, d.h)
        if dlg.exec():
            ops.resize(d, dlg.w.value(), dlg.h.value(), dlg.smooth.isChecked())
            self.canvas.fit()

    def colour_range(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QSlider, QPushButton, QColorDialog, QHBoxLayout
        from imgkit import transform as tf
        d = self.cur_doc()
        before = d.selection
        col = [QColor(self.state.fg)]
        dlg = QDialog(self)
        dlg.setWindowTitle("Colour range")
        f = QFormLayout(dlg)
        btn = QPushButton("Pick colour…")
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 200)
        sl.setValue(40)
        sl.setMinimumWidth(240)

        def paint():
            btn.setStyleSheet(f"background:{col[0].name()}; padding:6px;")

        def update():
            d.set_selection(tf.colour_range(d, col[0], sl.value()))
            d.changed(None)

        def pick():
            c = QColorDialog.getColor(col[0], dlg)
            if c.isValid():
                col[0] = c
                paint()
                update()
        btn.clicked.connect(pick)
        sl.valueChanged.connect(lambda _: update())
        f.addRow("Colour (starts as the front colour)", btn)
        f.addRow("Fuzziness", sl)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        paint()
        update()
        if dlg.exec():
            final = d.selection
            d.selection = before
            self.canvas.set_selection(final, "Colour range")
        else:
            d.selection = before
            d.changed(None)

    def straighten(self):
        from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout, QDialog, QDialogButtonBox
        d = self.cur_doc()
        dlg = QDialog(self)
        dlg.setWindowTitle("Rotate by any angle")
        f = QFormLayout(dlg)
        sp = QDoubleSpinBox()
        sp.setRange(-180, 180)
        sp.setDecimals(2)
        sp.setSuffix(" °")
        sp.setSingleStep(0.5)
        f.addRow("Angle (positive = clockwise)", sp)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() and sp.value() != 0:
            ops.rotate_canvas(d, sp.value())

    def canvas_size(self):
        d = self.cur_doc()
        dlg = dialogs.CanvasSizeDialog(self, d.w, d.h)
        if dlg.exec():
            ops.canvas_size(d, dlg.w.value(), dlg.h.value(), *dlg.anchor)
            self.canvas.fit()

    def crop_selection(self):
        d = self.cur_doc()
        if d.selection is None:
            self._no_sel()
            return
        self.canvas.crop_to(d.selection.bbox())

    # ------------------------------------------------------------------ text
    def new_text(self, p):
        d = self.cur_doc()
        if d is None:
            return
        s = self.state
        spec = dict(text="", font=s.font, size=s.font_size, bold=s.bold, italic=s.italic, align=s.align, color=s.fg.name())
        dlg = dialogs.TextDialog(self, spec)
        if dlg.exec() and dlg.spec()["text"].strip():
            sp = dlg.spec()
            s.set(font=sp["font"], font_size=sp["size"], bold=sp["bold"], italic=sp["italic"], align=sp["align"])
            with d.edit("Text"):
                L = Layer(render_text(sp), sp["text"].strip().splitlines()[0][:24], int(p.x()), int(p.y()))
                L.text = sp
                d.layers.insert(d.active + 1, L)
                d.active += 1

    def text_props(self, font, size):
        d = self.cur_doc()
        L = d.layer() if d else None
        if L is None or not L.text:
            return
        sp = dict(L.text, font=font, size=size)
        sp.pop("psd_anchor", None)                         # drawn again: the Photoshop text point is worked out anew
        with d.edit("Edit text", [L]):
            old = L.image
            L.image = render_text(sp)
            place_like(L, old, L.image, sp.get("align", "left"))
            L.text = sp

    def edit_text(self):
        d = self.cur_doc()
        L = d.layer()
        if L is None or not L.text:
            self.statusBar().showMessage("Select a text layer first.", 4000)
            return
        if not ui.warn_missing_font(self, L.text.get("font")):
            return
        dlg = dialogs.TextDialog(self, L.text)
        if dlg.exec():
            sp = dlg.spec()
            with d.edit("Edit text", [L]):
                old = L.image
                L.image = render_text(sp)
                place_like(L, old, L.image, sp.get("align", "left"))
                L.text = sp
                L.name = sp["text"].strip().splitlines()[0][:24] if sp["text"].strip() else L.name

    # ------------------------------------------------------------------ help
    def shortcuts(self):
        QMessageBox.information(self, "Keyboard shortcuts", (
            "<b>Tools</b>: V move, Ctrl+T free transform, A quick selection, M select, L lasso, W wand, B brush, E eraser, S clone stamp, J healing brush, R smudge, O dodge, K fill, G gradient, I picker, T text, U shape, C crop, H hand, Z zoom<br>"
            "<b>Clone / healing</b>: Alt + click chooses the part to copy, then paint where it should go<br><br>"
            "<b>Painting</b>: [ and ] change brush size, X swap colours, D black and white<br>"
            "<b>Selection</b>: Shift adds, Alt subtracts, Ctrl+A all, Ctrl+D none, Ctrl+Shift+I inverse<br>"
            "<b>View</b>: mouse wheel zooms, Space + drag moves around, Ctrl+0 fit, Ctrl+1 100%<br>"
            "<b>Masks</b>: Layers panel > Mask. Paint black to hide, white to show. Tick 'Paint on the mask' to edit it<br>"
            "<b>Layers</b>: Ctrl+J layer via copy, Ctrl+Shift+N new layer, Ctrl+Shift+E merge down<br>"
            "<b>File</b>: Ctrl+S save project (.dimg keeps layers), Ctrl+E export PNG / JPG / WebP"))

    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}", f"<h3>{APP_NAME} {VERSION}</h3><p>Layers, selections, brushes, adjustments and filters.<br>"
                          "Projects are saved as .dimg (a zip with one PNG per layer). Export to PNG, JPG, WebP, BMP and ICO.</p>"
                          "<p>Part of the Digonto family of programs.</p>")


def main():
    ui.mac_app_name(APP_NAME)
    app = QApplication(sys.argv)
    if ui.forward_to_running(SLUG, sys.argv[1:]):
        os._exit(0)
    ui.setup_app(app, APP_NAME, SLUG, ui.app_icon(HERE, SLUG), theme=True)
    w = Main()
    w.show()
    ui.serve_single(SLUG, w, w.open_path)
    for a in sys.argv[1:]:
        if os.path.isfile(a):
            w.open_path(a)
    os._exit(app.exec())


if __name__ == "__main__":
    main()
