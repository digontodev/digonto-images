"""Side panels: Navigator, Colour, Layers, History, and the tool options bar."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QMenu, QGroupBox, QMessageBox, QCheckBox, QColorDialog, QComboBox, QFontComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import adjlayers, fx, ops, render
from .doc import BLEND


class Navigator(QWidget):
    """a small picture of the whole image; the red frame is what you see - drag it to move around"""

    def __init__(self, canvas):
        super().__init__()
        self.c = canvas
        self.setMinimumHeight(110)
        self._img = None
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.timeout.connect(self._rebuild)
        canvas.viewChanged.connect(self.refresh)
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(-40, 40)           # steps of 1/10 octave around 100 %
        self.zoom.valueChanged.connect(self._slider)
        self._lock = False
        self.lbl = QLabel("100%")
        self.lbl.setFixedWidth(38)
        self.lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.box = QWidget()
        lay = QVBoxLayout(self.box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self)
        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 4, 4)
        row.setSpacing(3)
        mn = QToolButton(); mn.setText("−"); mn.clicked.connect(lambda: canvas.zoom_to(canvas.zoom / 1.25))
        pl = QToolButton(); pl.setText("+"); pl.clicked.connect(lambda: canvas.zoom_to(canvas.zoom * 1.25))
        fit = QToolButton(); fit.setText("Fit"); fit.clicked.connect(canvas.fit)
        one = QToolButton(); one.setText("1:1"); one.clicked.connect(canvas.actual)
        for w in (mn, self.zoom, pl, self.lbl, fit, one):
            row.addWidget(w, 1 if w is self.zoom else 0)
        lay.addLayout(row)

    def refresh(self):
        self._t.start(120)
        self.update()
        self._lock = True
        import math
        self.zoom.setValue(int(round(math.log2(max(0.02, self.c.zoom)) * 10)))
        self._lock = False
        self.lbl.setText(f"{self.c.zoom * 100:.0f}%")

    def _slider(self, v):
        if not self._lock:
            self.c.zoom_to(2 ** (v / 10.0))

    def _rebuild(self):
        d = self.c.doc
        if d is None:
            self._img = None
        else:
            m = d.merged()
            w_, h_ = max(1, self.width()), max(1, self.height())
            if max(m.width(), m.height()) > max(w_, h_) * 6:
                m = m.scaled(w_ * 4, h_ * 4, Qt.KeepAspectRatio, Qt.FastTransformation)
            self._img = m.scaled(w_, h_, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.update()

    def _frame(self):
        d = self.c.doc
        if d is None or self._img is None:
            return None, 1.0, QPointF()
        k = self._img.width() / d.w
        o = QPointF((self.width() - self._img.width()) / 2, (self.height() - self._img.height()) / 2)
        return d, k, o

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#2E3331"))
        d, k, o = self._frame()
        if d is None:
            return
        p.drawImage(o, self._img)
        v = self.c.view_rect_doc().intersected(QRectF(0, 0, d.w, d.h))
        r = QRectF(o.x() + v.x() * k, o.y() + v.y() * k, v.width() * k, v.height() * k)
        p.fillRect(r, QColor(255, 60, 60, 35))
        p.setPen(QPen(QColor("#FF3B30"), 2))
        p.drawRect(r)

    def resizeEvent(self, e):
        self._t.start(60)

    def _go(self, ev):
        d, k, o = self._frame()
        if d is not None:
            self.c.center_on(QPointF((ev.position().x() - o.x()) / k, (ev.position().y() - o.y()) / k))

    mousePressEvent = mouseMoveEvent = _go


class Swatch(QWidget):
    clicked = Signal()

    def __init__(self, get):
        super().__init__()
        self.get = get
        self.setFixedSize(30, 30)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QPen(QColor("#555"), 1))
        p.setBrush(self.get())
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def mousePressEvent(self, e):
        self.clicked.emit()


class ColorPanel(QWidget):
    PALETTE = ["#000000", "#404040", "#808080", "#BFBFBF", "#FFFFFF", "#E8304F", "#FF7A3D", "#FFC94A", "#7BD389", "#C2395C", "#FF6F8E",
               "#1FB5C4", "#2F5BEA", "#6B3FD0", "#C23FD0", "#8B5A2B"]

    def __init__(self, state):
        super().__init__()
        self.s = state
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        row = QHBoxLayout()
        self.fg = Swatch(lambda: self.s.fg)
        self.bg = Swatch(lambda: self.s.bg)
        self.fg.clicked.connect(lambda: self.pick("fg"))
        self.bg.clicked.connect(lambda: self.pick("bg"))
        self.fg.setToolTip("Front colour")
        self.bg.setToolTip("Back colour")
        row.addWidget(self.fg)
        row.addWidget(self.bg)
        sw = QToolButton(); sw.setText("⇄"); sw.setToolTip("Swap (X)"); sw.clicked.connect(state.swap)
        rs = QToolButton(); rs.setText("B/W"); rs.setToolTip("Black and white (D)"); rs.clicked.connect(state.reset_colors)
        row.addWidget(sw)
        row.addWidget(rs)
        row.addStretch()
        lay.addLayout(row)
        self.sl = {}
        for key, lab, hi in (("h", "Hue", 359), ("s", "Saturation", 255), ("v", "Brightness", 255)):
            r = QHBoxLayout()
            l = QLabel(lab)
            l.setFixedWidth(70)
            s = QSlider(Qt.Horizontal)
            s.setRange(0, hi)
            s.valueChanged.connect(self._slide)
            r.addWidget(l)
            r.addWidget(s)
            lay.addLayout(r)
            self.sl[key] = s
        hr = QHBoxLayout()
        hr.addWidget(QLabel("Hex"))
        self.hex = QLineEdit()
        self.hex.setMaximumWidth(90)
        self.hex.editingFinished.connect(self._hex)
        hr.addWidget(self.hex)
        hr.addStretch()
        lay.addLayout(hr)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(3)
        from PySide6.QtWidgets import QScrollArea
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(self.grid_host)
        sa.setMinimumHeight(70)
        sa.setFrameShape(QScrollArea.NoFrame)
        lay.addWidget(sa, 1)
        ld = QPushButton("Load swatches…")
        ld.clicked.connect(self.load_swatches)
        lay.addWidget(ld)
        self._swatches()
        state.changed.connect(lambda n: n == "swatches" and self._swatches())
        state.changed.connect(self._sync)
        self._sync("fg")

    def _swatches(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        items = self.s.swatches or [(c, QColor(c)) for c in self.PALETTE]
        for i, (name, c) in enumerate(items[:512]):
            b = QPushButton()
            b.setFixedSize(20, 20)
            b.setToolTip(name)
            b.setStyleSheet(f"background:{c.name()}; border:1px solid #777;")
            b.clicked.connect(lambda _=False, c=c: self.s.set(fg=QColor(c)))
            self.grid.addWidget(b, i // 9, i % 9)

    def load_swatches(self):
        from .presets import read_swatches
        from PySide6.QtCore import QSettings
        f, _ = QFileDialog.getOpenFileName(self, "Load swatches", "", "Photoshop swatches (*.aco *.act)")
        if not f:
            return
        try:
            self.s.set(swatches=read_swatches(f))
            QSettings("Digonto", "Images").setValue("presets/swatches", f)
        except Exception as e:
            QMessageBox.warning(self, "Swatches", f"Could not read this file.\n\n{e}")

    def pick(self, which):
        c = QColorDialog.getColor(getattr(self.s, which), self, "Pick a colour")
        if c.isValid():
            self.s.set(**{which: c})

    def _sync(self, name):
        if name not in ("fg", "bg"):
            return
        self.fg.update()
        self.bg.update()
        c = self.s.fg
        for k, v in zip("hsv", (max(0, c.hsvHue()), c.hsvSaturation(), c.value())):
            self.sl[k].blockSignals(True)
            self.sl[k].setValue(v)
            self.sl[k].blockSignals(False)
        self.hex.setText(c.name().upper())

    def _slide(self):
        c = QColor.fromHsv(self.sl["h"].value(), self.sl["s"].value(), self.sl["v"].value())
        self.s.fg = c
        self.hex.setText(c.name().upper())
        self.fg.update()
        self.s.changed.emit("fg_live")

    def _hex(self):
        c = QColor(self.hex.text())
        if c.isValid():
            self.s.set(fg=c)


class LayersPanel(QWidget):
    def __init__(self, get_doc):
        super().__init__()
        self.get_doc = get_doc
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        top = QHBoxLayout()
        self.blend = QComboBox()
        for k, n in BLEND:
            self.blend.addItem(n, k)
        self.blend.currentIndexChanged.connect(self._blend)
        top.addWidget(self.blend, 1)
        self.lock = QCheckBox("Lock")
        self.lock.toggled.connect(self._lock)
        top.addWidget(self.lock)
        lay.addLayout(top)
        orow = QHBoxLayout()
        orow.addWidget(QLabel("Opacity"))
        self.op = QSlider(Qt.Horizontal)
        self.op.setRange(0, 100)
        self.op.sliderPressed.connect(self._op_begin)
        self.op.valueChanged.connect(self._op)
        self.op.sliderReleased.connect(self._op_end)
        self.op_lbl = QLabel("100")
        self.op_lbl.setFixedWidth(28)
        orow.addWidget(self.op)
        orow.addWidget(self.op_lbl)
        lay.addLayout(orow)
        self.list = QListWidget()
        self.list.setIconSize(QSize(44, 44))
        self.list.setSpacing(1)
        self.list.currentRowChanged.connect(self._select)
        self.list.itemClicked.connect(self._clicked)
        self.list.itemChanged.connect(self._vis)
        self.list.itemDoubleClicked.connect(self._rename)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)       # drag a layer up or down
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.model().rowsMoved.connect(self._moved)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.buttons = {}
        for key, txt, tip in (("new", "＋", "New layer"), ("dup", "⧉", "Duplicate"), ("up", "▲", "Move up"), ("down", "▼", "Move down"),
                              ("merge", "⤓", "Merge down"), ("del", "🗑", "Delete layer")):
            b = QToolButton()
            b.setText(txt)
            b.setToolTip(tip)
            row.addWidget(b)
            self.buttons[key] = b
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.mask_btn = QToolButton()
        self.mask_btn.setText("Mask ▾")
        self.mask_btn.setPopupMode(QToolButton.InstantPopup)
        self.mask_btn.setToolTip("Layer mask: paint black to hide, white to show")
        mm = QMenu(self.mask_btn)
        for txt, fn in (("Add mask - show all", lambda d: ops.add_mask(d, "reveal")), ("Add mask - hide all", lambda d: ops.add_mask(d, "hide")),
                        ("Add mask from selection", lambda d: ops.add_mask(d, "selection")), (None, None),
                        ("Invert mask", ops.invert_mask), ("Switch mask on / off", ops.toggle_mask),
                        ("Apply mask to layer", lambda d: ops.delete_mask(d, True)), ("Delete mask", lambda d: ops.delete_mask(d, False))):
            if txt is None:
                mm.addSeparator()
            else:
                mm.addAction(txt, lambda fn=fn: self._do(fn))
        self.mask_btn.setMenu(mm)
        row2.addWidget(self.mask_btn)
        self.fx_btn = QToolButton()
        self.fx_btn.setText("fx")
        self.fx_btn.setToolTip("Layer style: shadow, glow, outline, colour overlay")
        self.fx_btn.clicked.connect(self._style)
        row2.addWidget(self.fx_btn)
        self.clip_btn = QToolButton()
        self.clip_btn.setText("↳ Clip")
        self.clip_btn.setToolTip("Clipping mask (Ctrl+Alt+G): this layer only shows inside the layer below")
        self.clip_btn.clicked.connect(lambda: self._do(ops.toggle_clip))
        row2.addWidget(self.clip_btn)
        self.adj_btn = QToolButton()
        self.adj_btn.setText("Adjustment ▾")
        self.adj_btn.setPopupMode(QToolButton.InstantPopup)
        self.adj_btn.setToolTip("Adjustment layer: a colour change you can edit later")
        am = QMenu(self.adj_btn)
        for kind, (nm, _sp, _fn) in adjlayers.KINDS.items():
            am.addAction(nm + ("…" if _sp else ""), lambda kind=kind: self._add_adj(kind))
        self.adj_btn.setMenu(am)
        row2.addWidget(self.adj_btn)
        lay.addLayout(row2)
        self.edit_mask = QCheckBox("Paint on the mask")
        self.edit_mask.toggled.connect(self._edit_mask)
        lay.addWidget(self.edit_mask)
        b = self.buttons
        b["new"].clicked.connect(lambda: self._do(ops.add_layer))
        b["dup"].clicked.connect(lambda: self._do(ops.duplicate_layer))
        b["up"].clicked.connect(lambda: self._do(lambda d: ops.move_layer(d, 1)))
        b["down"].clicked.connect(lambda: self._do(lambda d: ops.move_layer(d, -1)))
        b["merge"].clicked.connect(lambda: self._do(ops.merge_down))
        b["del"].clicked.connect(lambda: self._do(ops.delete_layer))
        self._busy = False
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.timeout.connect(self.rebuild)
        self._op_edit = None

    def schedule(self):
        self._t.start(150)

    def _do(self, fn):
        d = self.get_doc()
        if d is not None:
            fn(d)

    def _icon(self, L):
        t = L.thumb(44)
        if L._mask is None:
            return QIcon(QPixmap.fromImage(t))
        m = L.mask_thumb(44)
        pm = QPixmap(92, 46)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.drawImage(1, 1, t)
        p.drawImage(47, 1, m)
        p.setPen(QPen(QColor("#C2395C"), 2) if L.edit_mask else QPen(QColor("#999"), 1))
        p.drawRect(46, 0, 45, 45)
        p.end()
        return QIcon(pm)

    def _style(self):
        d = self.get_doc()
        if d is not None and d.layer() is not None and not d.layer().adj:
            fx.StyleDialog(self.window(), d).exec()

    def _add_adj(self, kind):
        d = self.get_doc()
        if d is None:
            return
        n = ops.add_adjustment(d, kind, adjlayers.defaults(kind))
        if adjlayers.KINDS[kind][1]:
            fx.AdjustLayerDialog(self.window(), d, n).exec()

    def _edit_mask(self, on):
        d = self.get_doc()
        L = d.layer() if d else None
        if L is None or self._busy or L._mask is None:
            return
        L.edit_mask = on
        if on:
            self.window().state.set(fg=QColor("#000000"), bg=QColor("#FFFFFF"))     # black hides, white shows
        d.changed(None)
        self.rebuild()

    def rebuild(self):
        d = self.get_doc()
        self._busy = True
        self.list.clear()
        if d is not None:
            folded = {l.gid for l in d.layers if l.is_group and l.collapsed}
            for i in range(len(d.layers) - 1, -1, -1):
                L = d.layers[i]
                if L.parent in folded and not L.is_group:
                    continue                                  # inside a folded group
                if L.is_group:
                    label = ("▸  " if L.collapsed else "▾  ") + "📁  " + L.name + (f"  {int(round(L.opacity * 100))} %" if L.opacity < 0.999 else "")
                    it = QListWidgetItem(label)
                    it.setToolTip("Group: click the arrow side twice to fold / unfold, double-click the name to rename")
                else:
                    it = QListWidgetItem(self._icon(L), ("      " if L.parent else "") + ("↳ " if getattr(L, "clip", False) else "") + ("◐  " if L.adj else "T  " if L.text else "") + L.name + ("  fx" if render.style_active(L.style) else "")
                                         + ("  🔒" if L.locked else "") + ("  ▣ smart" if L.smart else ""))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if L.visible else Qt.Unchecked)
                it.setData(Qt.UserRole, i)
                self.list.addItem(it)
                if i == d.active:
                    self.list.setCurrentItem(it)
            L = d.layer()
            if L is not None:
                self.blend.blockSignals(True)
                self.blend.setCurrentIndex(max(0, self.blend.findData(L.blend)))
                self.blend.blockSignals(False)
                self.op.blockSignals(True)
                self.op.setValue(int(round(L.opacity * 100)))
                self.op.blockSignals(False)
                self.op_lbl.setText(str(int(round(L.opacity * 100))))
                self.lock.blockSignals(True)
                self.lock.setChecked(L.locked)
                self.lock.blockSignals(False)
                self.edit_mask.blockSignals(True)
                self.edit_mask.setEnabled(L._mask is not None)
                self.edit_mask.setChecked(L.edit_mask and L._mask is not None)
                self.edit_mask.blockSignals(False)
                self.fx_btn.setEnabled(not L.adj)
        self._busy = False

    def _moved(self, *a):
        d = self.get_doc()
        if self._busy or d is None:
            return
        order = [self.list.item(r).data(Qt.UserRole) for r in range(self.list.count())]       # top first
        old = list(d.layers)
        if len(set(order)) == len(order) and all(0 <= i < len(old) for i in order):
            new = [old[i] for i in reversed(order)]
            new += [l for l in old if l not in new]           # layers of folded groups: tidy_groups puts them back under their group
            ops.reorder_layers(d, new)
        QTimer.singleShot(0, self.rebuild)

    def _select(self, row):
        d = self.get_doc()
        if self._busy or d is None or row < 0:
            return
        i = self.list.item(row).data(Qt.UserRole)
        if i != d.active:
            d.set_active(i)
            self.rebuild()

    def _clicked(self, it):
        """a click on the arrow of a group folds or unfolds it"""
        d = self.get_doc()
        if d is None or self._busy:
            return
        i = it.data(Qt.UserRole)
        if 0 <= i < len(d.layers) and d.layers[i].is_group and self.list.viewport().mapFromGlobal(QCursor.pos()).x() < 40:
            d.layers[i].collapsed = not d.layers[i].collapsed
            QTimer.singleShot(0, self.rebuild)

    def _vis(self, it):
        d = self.get_doc()
        if self._busy or d is None:
            return
        i = it.data(Qt.UserRole)
        vis = it.checkState() == Qt.Checked
        if d.layers[i].visible != vis:
            with d.edit("Show / hide layer"):
                d.layers[i].visible = vis

    def _rename(self, it):
        d = self.get_doc()
        from PySide6.QtWidgets import QInputDialog
        i = it.data(Qt.UserRole)
        if d.layers[i].is_group and self.list.viewport().mapFromGlobal(QCursor.pos()).x() < 40:
            return                                            # a double click on the arrow only folds
        if d.layers[i].adj and adjlayers.KINDS[d.layers[i].adj["kind"]][1]:
            d.set_active(i)
            fx.AdjustLayerDialog(self.window(), d, d.layers[i]).exec()
            return
        n, ok = QInputDialog.getText(self, "Layer name", "Name:", text=d.layers[i].name)
        if ok and n.strip():
            with d.edit("Rename layer"):
                d.layers[i].name = n.strip()

    def _blend(self):
        d = self.get_doc()
        L = d.layer() if d else None
        if L is not None and not self._busy:
            with d.edit("Blend mode"):
                L.blend = self.blend.currentData()

    def _lock(self, on):
        d = self.get_doc()
        L = d.layer() if d else None
        if L is not None and not self._busy:
            with d.edit("Lock layer", pixels=False):
                L.locked = on

    def _op_begin(self):
        d = self.get_doc()
        if d is not None:
            self._op_edit = d.edit("Layer opacity")
            self._op_edit.__enter__()

    def _op(self, v):
        d = self.get_doc()
        L = d.layer() if d else None
        if L is None or self._busy:
            return
        self.op_lbl.setText(str(v))
        if self._op_edit is None:           # keyboard / click on the groove
            with d.edit("Layer opacity"):
                L.opacity = v / 100.0
        else:
            L.opacity = v / 100.0
            d.invalidate()
            d.changed()

    def _op_end(self):
        if self._op_edit is not None:
            self._op_edit.__exit__(None, None, None)
            self._op_edit = None


class HistoryPanel(QWidget):
    def __init__(self, get_doc):
        super().__init__()
        self.get_doc = get_doc
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._go)
        lay.addWidget(self.list)
        self._busy = False

    def rebuild(self):
        d = self.get_doc()
        self._busy = True
        self.list.clear()
        if d is not None:
            self.list.addItem("Open")
            for e in d.history:
                self.list.addItem(e["label"])
            self.list.setCurrentRow(d.pos)
            for i in range(self.list.count()):
                if i > d.pos:
                    self.list.item(i).setForeground(QColor("#999"))
        self._busy = False

    def _go(self, row):
        d = self.get_doc()
        if not self._busy and d is not None and row >= 0:
            d.goto(row)


class OptionsBar(QWidget):
    """settings for the active tool; only the controls that matter are shown"""

    def __init__(self, state):
        super().__init__()
        self.s = state
        from digonto_ui import FlowLayout
        lay = FlowLayout(self, 8, 12, 3)            # wraps onto more rows when the window is narrow
        self.groups = {}

        def slider(name, label, lo, hi, tip=""):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(QLabel(label))
            sl = QSlider(Qt.Horizontal)
            sl.setRange(lo, hi)
            sl.setFixedWidth(110)
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sl.setValue(getattr(state, name))
            sp.setValue(getattr(state, name))
            sl.valueChanged.connect(sp.setValue)
            sp.valueChanged.connect(sl.setValue)
            sp.valueChanged.connect(lambda v: state.set(**{name: v}))
            state.changed.connect(lambda n, sl=sl, sp=sp, name=name: (n == name) and (sp.setValue(getattr(state, name))))
            h.addWidget(sl)
            h.addWidget(sp)
            if tip:
                w.setToolTip(tip)
            lay.addWidget(w)
            return w

        def check(name, label, tip=""):
            c = QCheckBox(label)
            c.setChecked(getattr(state, name))
            c.toggled.connect(lambda v: state.set(**{name: v}))
            if tip:
                c.setToolTip(tip)
            lay.addWidget(c)
            return c

        def combo(name, items, label=""):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            if label:
                h.addWidget(QLabel(label))
            cb = QComboBox()
            for k, t in items:
                cb.addItem(t, k)
            cb.setCurrentIndex(max(0, cb.findData(getattr(state, name))))
            cb.currentIndexChanged.connect(lambda _i: state.set(**{name: cb.currentData()}))
            h.addWidget(cb)
            lay.addWidget(w)
            return w

        W = {}
        W["size"] = slider("size", "Size", 1, 500)
        W["hardness"] = slider("hardness", "Hardness", 0, 100)
        W["opacity"] = slider("opacity", "Opacity", 1, 100)
        W["tolerance"] = slider("tolerance", "Tolerance", 0, 255)
        W["contiguous"] = check("contiguous", "Touching only")
        W["sample_layer"] = check("sample_layer", "This layer only", "Off = look at the whole picture")
        W["sel_kind"] = combo("sel_kind", [("rect", "Rectangle"), ("ellipse", "Round (ellipse)"), ("rounded", "Rounded rectangle"), ("lasso", "Freehand lasso"), ("poly", "Polygon lasso")], "Shape")
        W["feather"] = slider("feather", "Soft edge", 0, 100)
        W["shape"] = combo("shape", [("rect", "Rectangle"), ("rounded", "Rounded"), ("ellipse", "Ellipse"), ("line", "Line")], "Shape")
        W["fill"] = check("fill", "Fill (front colour)")
        W["stroke"] = check("stroke", "Outline (back colour)")
        W["stroke_w"] = slider("stroke_w", "Width", 1, 100)
        W["radius"] = slider("radius", "Corner", 0, 300)
        W["grad"] = combo("grad", [("linear", "Linear"), ("radial", "Radial")], "Gradient")
        W["grad_mode"] = combo("grad_mode", [("fg-bg", "Front to back"), ("fg-clear", "Front to clear")])
        W["grad_preset"] = self._grad_preset(lay)
        W["brush_preset"] = self._brush_preset(lay)
        W["tool_preset"] = self._tool_preset(lay)
        W["pen_actions"] = self._pen_actions(lay)
        self.W = W
        self.hint = QLabel("")
        self.hint.setStyleSheet("color:#6A7A72;")
        self.hint.setMaximumWidth(360)
        lay.addWidget(self.hint)
        self.show_for("brush")
        state.changed.connect(lambda n: n == "tool" and self.show_for(state.tool))

    def _stable(self):
        import digonto_ui as ui
        self._tool = getattr(self, "_tool", None)
        ui.stabilize_bar(self, self.layout(), list(self.SHOW) + [None], self.show_for, lambda: self._tool)

    def _brush_preset(self, lay):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel("Brush"))
        self.bcb = QComboBox()
        self.bcb.setMinimumWidth(150)
        self.bcb.setIconSize(QSize(28, 28))
        self.bcb.currentIndexChanged.connect(self._brush_pick)
        h.addWidget(self.bcb)
        b = QToolButton()
        b.setText("Load .abr…")
        b.clicked.connect(self._load_abr)
        h.addWidget(b)
        lay.addWidget(w)
        self.s.changed.connect(lambda n: n == "brush_presets" and self._fill_brushes())
        self._fill_brushes()
        return w

    def _pen_actions(self, lay):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel("Path →"))
        for t, fn, tip in (("Selection", "to_selection", "Make a selection from the path (Enter)"), ("Fill", "fill", "Fill the path with the front colour"),
                           ("Stroke", "stroke", "Draw along the path with the brush size and front colour")):
            b = QToolButton(); b.setText(t); b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: self._pen_do(f))
            h.addWidget(b)
        lay.addWidget(w)
        return w

    def _pen_do(self, fn):
        from .tools import TOOLS
        win = self.window()
        c = getattr(win, "canvas", None) or (win.cur_canvas() if hasattr(win, "cur_canvas") else None)
        if c is not None:
            getattr(TOOLS["pen"], fn)(c)

    # ---- tool presets (as in Photoshop): size, hardness, opacity and tip saved under a name
    def _tool_preset(self, lay):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel("Preset"))
        self.tpcb = QComboBox()
        self.tpcb.setMinimumWidth(130)
        self.tpcb.activated.connect(self._tool_preset_pick)
        h.addWidget(self.tpcb)
        b = QToolButton(); b.setText("Save…"); b.setToolTip("Save the current brush settings under a name"); b.clicked.connect(self._tool_preset_save)
        h.addWidget(b)
        x = QToolButton(); x.setText("✕"); x.setToolTip("Delete the chosen preset"); x.clicked.connect(self._tool_preset_delete)
        h.addWidget(x)
        lay.addWidget(w)
        self._fill_tool_presets()
        return w

    @staticmethod
    def _tp_load():
        import json
        from PySide6.QtCore import QSettings
        try:
            return json.loads(QSettings("Digonto", "Images").value("presets/tool_presets", "[]") or "[]")
        except Exception:
            return []

    @staticmethod
    def _tp_store(items):
        import json
        from PySide6.QtCore import QSettings
        QSettings("Digonto", "Images").setValue("presets/tool_presets", json.dumps(items))

    def _fill_tool_presets(self):
        self.tpcb.blockSignals(True)
        self.tpcb.clear()
        self.tpcb.addItem("—")
        for p in self._tp_load():
            self.tpcb.addItem(f"{p['name']}  ({p['size']} px)")
        self.tpcb.blockSignals(False)

    def _tool_preset_pick(self, i):
        items = self._tp_load()
        if i <= 0 or i > len(items):
            return
        p = items[i - 1]
        self.s.set(size=int(p["size"]), hardness=int(p["hardness"]), opacity=int(p["opacity"]))
        tip = p.get("tip")
        self.s.tip = next((t for t in self.s.brush_presets if t["name"] == tip), None) if tip else None
        self.s.changed.emit("tip")
        self.s.changed.emit("brush_presets")

    def _tool_preset_save(self):
        from PySide6.QtWidgets import QInputDialog
        n, ok = QInputDialog.getText(self, "Save preset", "Name:", text=f"Brush {self.s.size} px")
        if not ok or not n.strip():
            return
        items = [p for p in self._tp_load() if p["name"] != n.strip()]
        items.append(dict(name=n.strip(), size=self.s.size, hardness=self.s.hardness, opacity=self.s.opacity,
                          tip=self.s.tip["name"] if self.s.tip else None))
        self._tp_store(items)
        self._fill_tool_presets()
        self.tpcb.setCurrentIndex(len(items))

    def _tool_preset_delete(self):
        i = self.tpcb.currentIndex()
        items = self._tp_load()
        if 0 < i <= len(items):
            del items[i - 1]
            self._tp_store(items)
            self._fill_tool_presets()

    def _fill_brushes(self):
        from . import arr
        self.bcb.blockSignals(True)
        self.bcb.clear()
        self.bcb.addItem("Round (soft)")
        for t in self.s.brush_presets:
            a = t["alpha"]
            im = arr.from_mask(255 - a).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.bcb.addItem(QIcon(QPixmap.fromImage(im)), t["name"])
        cur = self.s.tip
        idx = 0
        if cur is not None:
            for i, t in enumerate(self.s.brush_presets):
                if t is cur:
                    idx = i + 1
        self.bcb.setCurrentIndex(idx)
        self.bcb.blockSignals(False)

    def _brush_pick(self, i):
        self.s.tip = self.s.brush_presets[i - 1] if i > 0 else None
        self.s.changed.emit("tip")

    def _load_abr(self):
        from .presets import read_abr
        from PySide6.QtCore import QSettings
        f, _ = QFileDialog.getOpenFileName(self, "Load Photoshop brushes", "", "Photoshop brushes (*.abr)")
        if not f:
            return
        try:
            got = read_abr(f)
        except Exception as e:
            QMessageBox.warning(self, "Brushes", f"Could not read this file.\n\n{e}")
            return
        self.s.brush_presets = self.s.brush_presets + got
        self.s.tip = got[0]
        self.s.changed.emit("brush_presets")
        st = QSettings("Digonto", "Images")
        st.setValue("presets/brushes", list({*(st.value("presets/brushes") or []), f}) if isinstance(st.value("presets/brushes"), list) else [f])

    def _grad_preset(self, lay):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self.gcb = QComboBox()
        self.gcb.setIconSize(QSize(96, 16))
        self.gcb.setMinimumWidth(190)
        self.gcb.currentIndexChanged.connect(self._grad_pick)
        h.addWidget(self.gcb)
        b = QToolButton()
        b.setText("Load .grd…")
        b.clicked.connect(self._load_grd)
        h.addWidget(b)
        lay.addWidget(w)
        self.s.changed.connect(lambda n: n in ("gradients", "fg", "bg") and self._fill_grads())
        self._fill_grads()
        return w

    def _fill_grads(self):
        from .presets import gradient_icon
        i0 = max(0, self.gcb.currentIndex())
        self.gcb.blockSignals(True)
        self.gcb.clear()
        for g in self.s.gradients:
            self.gcb.addItem(QIcon(gradient_icon(g, self.s.fg, self.s.bg)), g["name"])
        self.gcb.setCurrentIndex(min(i0, self.gcb.count() - 1))
        self.gcb.blockSignals(False)

    def _grad_pick(self, i):
        self.s.gradient = None if i <= 0 else self.s.gradients[i]

    def _load_grd(self):
        from .presets import read_grd
        from PySide6.QtCore import QSettings
        f, _ = QFileDialog.getOpenFileName(self, "Load Photoshop gradients", "", "Photoshop gradients (*.grd)")
        if not f:
            return
        try:
            got = read_grd(f)
        except Exception as e:
            QMessageBox.warning(self, "Gradients", f"Could not read this file.\n\n{e}")
            return
        n0 = len(self.s.gradients)
        self.s.gradients = self.s.gradients + got
        self.s.changed.emit("gradients")
        self.gcb.setCurrentIndex(n0)
        st = QSettings("Digonto", "Images")
        old = st.value("presets/gradients")
        st.setValue("presets/gradients", list({*(old if isinstance(old, list) else []), f}))

    SHOW = {
        "brush": ["tool_preset", "brush_preset", "size", "hardness", "opacity"], "eraser": ["tool_preset", "size", "hardness", "opacity"],
        "fill": ["tolerance", "contiguous", "sample_layer", "opacity"], "wand": ["tolerance", "contiguous", "sample_layer", "feather"],
        "select": ["sel_kind", "radius", "feather"], "shape": ["shape", "fill", "stroke", "stroke_w", "radius", "opacity"],
        "gradient": ["grad_preset", "grad", "opacity"],
        "quickselect": ["size", "tolerance", "sample_layer", "feather"], "transform": [],
        "clone": ["size", "hardness", "opacity", "sample_layer"], "heal": ["size", "hardness", "opacity", "sample_layer"], "spot": ["size", "sample_layer"],
        "smudge": ["size", "hardness", "opacity"], "blurbrush": ["size", "hardness", "opacity"], "sharpenbrush": ["size", "hardness", "opacity"],
        "dodge": ["size", "hardness", "opacity"], "burn": ["size", "hardness", "opacity"], "eyedropper": ["sample_layer"], "move": [], "crop": [], "text": [], "hand": [], "zoom": [],
        "pen": ["pen_actions", "size", "opacity", "feather"],
    }
    HINT = {
        "move": "Drag to move the layer. Arrow keys nudge (Shift = 10 px).", "crop": "Drag the area to keep, Enter = crop, Esc = cancel.",
        "text": "Click on the picture to type.",
        "pen": "Click = corner point, drag = curve, click the first point to close. Enter = selection, Backspace = undo point, Esc = clear.", "select": "Shift = add, Alt = subtract, click = deselect. Polygon: click points, double-click or Enter to finish.",
        "wand": "Shift = add, Alt = subtract.", "eyedropper": "Click = front colour, Alt-click = back colour.",
        "hand": "Drag to move around. Space does the same in any tool.", "zoom": "Click = zoom in, Alt-click = zoom out.",
        "quickselect": "Paint over the object; it grows over similar colours. Alt = take away.",
        "transform": "Drag handles to scale, inside to move, outside to rotate. Shift = proportions. Enter = apply, Esc = cancel.",
        "clone": "Alt + click = choose the part to copy, then paint.", "heal": "Alt + click = choose the part to copy; colours and light are matched.",
        "spot": "Paint over a spot or blemish and let go.", "smudge": "Drag to smear colours. Opacity = strength.",
        "blurbrush": "Paint to soften.", "sharpenbrush": "Paint to sharpen.", "dodge": "Paint to lighten.", "burn": "Paint to darken.",
        "brush": "[ and ] change the size.", "eraser": "[ and ] change the size.",
    }

    def show_for(self, tool):
        self._tool = tool
        want = self.SHOW.get(tool, [])
        for k, w in self.W.items():
            w.setVisible(k in want)
        self.hint.setText(self.HINT.get(tool, ""))
