"""Tool buttons (fixed size, so the column never changes width) and the Properties panel."""
import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFontComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

import copy
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QComboBox, QSlider

from . import ops, render
from .doc import BLEND
from .tools import render_text
from .toolicons import icon as tool_icon


def icon_key(tool, extra):
    """which drawn icon belongs to a tool (and to the chosen variant of a flyout tool)"""
    if tool == "select":
        return {"rect": "select_rect", "ellipse": "select_ellipse", "rounded": "select_rounded", "lasso": "lasso", "poly": "poly"}.get(extra.get("sel_kind"), "select_rect")
    if tool == "shape":
        return "shape_" + extra.get("shape", "rect")
    if tool in ("clone", "retouch"):
        return extra.get("tool", tool)
    return tool

# one button per tool; a tool with a flyout shows its variants when you click it
# (label, shortcut, tool, state changes)  or  (label, shortcut, tool, None, [variants])
SELECTS = [("Rectangle", "M", {"sel_kind": "rect"}), ("Round (ellipse)", "", {"sel_kind": "ellipse"}), ("Rounded rectangle", "", {"sel_kind": "rounded"}),
           ("Lasso", "L", {"sel_kind": "lasso"}), ("Polygon lasso", "", {"sel_kind": "poly"})]
SHAPES = [("Rectangle", "U", {"shape": "rect"}), ("Rounded rectangle", "", {"shape": "rounded"}), ("Ellipse", "", {"shape": "ellipse"}), ("Line", "", {"shape": "line"})]
CLONES = [("Clone stamp", "S", {"tool": "clone"}), ("Healing brush", "J", {"tool": "heal"}), ("Spot healing", "", {"tool": "spot"})]
RETOUCH = [("Smudge", "R", {"tool": "smudge"}), ("Blur brush", "", {"tool": "blurbrush"}), ("Sharpen brush", "", {"tool": "sharpenbrush"}),
           ("Dodge (lighten)", "O", {"tool": "dodge"}), ("Burn (darken)", "", {"tool": "burn"})]
GROUP_TOOLS = {"select": ("select", "quickselect"), "shape": ("shape",), "clone": ("clone", "heal", "spot"), "retouch": ("smudge", "blurbrush", "sharpenbrush", "dodge", "burn")}
TOOLS = [("Move", "V", "move", None), ("Select", "", "select", SELECTS), ("Wand", "W", "wand", None), ("Brush", "B", "brush", None),
         ("Eraser", "E", "eraser", None), ("Clone", "", "clone", CLONES), ("Retouch", "", "retouch", RETOUCH), ("Fill", "K", "fill", None), ("Gradient", "G", "gradient", None), ("Picker", "I", "eyedropper", None),
         ("Pen", "P", "pen", None), ("Text", "T", "text", None), ("Shape", "", "shape", SHAPES), ("Crop", "C", "crop", None), ("Transform", "", "transform", None), ("Hand", "H", "hand", None), ("Zoom", "Z", "zoom", None)]
STYLE = ("QPushButton{border:1px solid transparent; border-radius:5px; padding:0 2px; text-align:center;}"
         "QPushButton:hover{background:#EFE7F5;}"
         "QPushButton:checked{background:#FBDCE5; border:1px solid #C2395C;}")


class ToolsPanel(QScrollArea):
    def __init__(self, state, shortcut_parent):
        super().__init__()
        self.s = state
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)
        self.buttons = {}          # tool -> (button, label, variants)
        self.sub = {"select": SELECTS[0], "shape": SHAPES[0], "clone": CLONES[0], "retouch": RETOUCH[0]}
        from PySide6.QtGui import QKeySequence, QShortcut
        for label, sc, tool, subs in TOOLS:
            b = QPushButton()
            b.setIcon(tool_icon(icon_key(tool, subs[0][2] if subs else {})))
            b.setIconSize(QSize(26, 26))
            b.setCheckable(True)
            b.setFixedSize(40, 36)
            b.setStyleSheet(STYLE)
            b.setToolTip(label + (f"  ({sc})" if sc else "") + ("  - click for more" if subs else ""))
            v.addWidget(b)
            self.buttons[tool] = (b, label, subs)
            if subs:
                b.clicked.connect(lambda _=False, t=tool: self._flyout(t))
                b.setProperty("grp", tool)
            else:
                b.clicked.connect(lambda _=False, t=tool: self.s.set(tool=t))
            if sc:
                QShortcut(QKeySequence(sc), shortcut_parent, activated=lambda t=tool, e=(subs[0][2] if subs else {}): self._go(t, e))
        # shortcuts for the variants that have one
        for tool, subs in (("select", SELECTS), ("shape", SHAPES), ("clone", CLONES), ("retouch", RETOUCH)):
            for name, sc, extra in subs:
                if sc and not any(sc == t[1] for t in TOOLS):
                    QShortcut(QKeySequence(sc), shortcut_parent, activated=lambda t=tool, it=(name, sc, extra): self._choose(t, it))
        v.addStretch()
        self.setWidget(inner)
        self.setFixedWidth(58)
        state.changed.connect(lambda n: self.sync())
        self.sync()

    def _flyout(self, tool):
        from PySide6.QtGui import QAction
        b, label, subs = self.buttons[tool]
        m = QMenu(b)
        cur = self.sub[tool]
        for item in subs:
            a = QAction(item[0], m)
            a.setCheckable(True)
            a.setChecked(item is cur)
            a.triggered.connect(lambda _=False, it=item: self._choose(tool, it))
            m.addAction(a)
        m.exec(b.mapToGlobal(b.rect().topRight()))
        self.sync()

    def _go(self, tool, extra):
        extra = dict(extra)
        self.s.set(tool=extra.pop("tool", tool), **extra)

    def _choose(self, tool, item):
        self.sub[tool] = item
        self._go(tool, item[2])

    def sync(self):
        s = self.s
        for tool, (b, label, subs) in self.buttons.items():
            if subs:
                for item in subs:           # remember which variant is active (also when changed from the options bar)
                    ex = dict(item[2])
                    t = ex.pop("tool", tool)
                    if s.tool == t and all(getattr(s, k) == v for k, v in ex.items()):
                        self.sub[tool] = item
                it = self.sub[tool]
                b.setIcon(tool_icon(icon_key(tool, it[2])))
                b.setToolTip(f"{label}: {it[0]}" + (f"  ({it[1]})" if it[1] else "") + "  - click for more")
            on = s.tool in GROUP_TOOLS.get(tool, (tool,))
            if b.isChecked() != on:
                b.setChecked(on)


class ArrowScroll(QWidget):
    """a scroll area with an up arrow on top and a down arrow below it, next to the usual bar"""

    def __init__(self, inner):
        super().__init__()
        from PySide6.QtCore import QTimer
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.sa = QScrollArea()
        self.sa.setWidgetResizable(True)
        self.sa.setFrameShape(QScrollArea.NoFrame)
        self.sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.sa.setWidget(inner)
        self.sa.verticalScrollBar().setStyleSheet("QScrollBar:vertical{width:14px;}")
        self.up, self.down = QPushButton("\u25B2"), QPushButton("\u25BC")
        for b, d in ((self.up, -1), (self.down, 1)):
            b.setFixedHeight(22)
            b.setAutoRepeat(True)
            b.setAutoRepeatInterval(40)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, d=d: self.sa.verticalScrollBar().setValue(self.sa.verticalScrollBar().value() + d * 40))
        v.addWidget(self.up)
        v.addWidget(self.sa, 1)
        v.addWidget(self.down)
        self.setMinimumSize(150, 120)
        bar = self.sa.verticalScrollBar()
        bar.rangeChanged.connect(lambda lo, hi: (self.up.setVisible(hi > lo), self.down.setVisible(hi > lo)))
        self.up.hide()
        self.down.hide()


class PropertiesPanel(QWidget):
    """size and position of the picture, the active layer and the selection - like Photoshop's Properties"""

    def __init__(self, get_doc):
        super().__init__()
        self.get_doc = get_doc
        self._busy = False
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 4, 8, 6)
        v.setSpacing(4)
        self.doc_lbl = QLabel()
        self.doc_lbl.setWordWrap(True)
        v.addWidget(self.doc_lbl)
        self.lay_lbl = QLabel()
        self.lay_lbl.setStyleSheet("color:#C2395C; font-weight:bold; padding-top:2px;")
        self.lay_lbl.setWordWrap(True)
        v.addWidget(self.lay_lbl)
        g = QGridLayout()
        self.x, self.y, self.w, self.h = (QSpinBox() for _ in range(4))
        for sb in (self.x, self.y):
            sb.setRange(-100000, 100000)
            sb.setSuffix(" px")
        for sb in (self.w, self.h):
            sb.setRange(1, 100000)
            sb.setSuffix(" px")
        g.setHorizontalSpacing(4)
        for (t, sb, r, c) in (("X", self.x, 0, 0), ("W", self.w, 0, 2), ("Y", self.y, 1, 0), ("H", self.h, 1, 2)):
            g.addWidget(QLabel(t), r, c)
            sb.setSuffix("")
            sb.setMinimumWidth(52)
            sb.setMaximumWidth(86)
            g.addWidget(sb, r, c + 1)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        v.addLayout(g)
        self.keep = QCheckBox("Keep proportions")
        self.keep.setChecked(True)
        v.addWidget(self.keep)
        self.apply = QPushButton("Apply size")
        self.apply.clicked.connect(self._apply_size)
        v.addWidget(self.apply)
        # ---- Fill / Outline / Object (like the Vector program); hidden until a picture is open
        self.fx_box = QWidget()
        fv = QVBoxLayout(self.fx_box)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(4)
        def head(t):
            lb = QLabel(t)
            lb.setStyleSheet("font-weight:bold; padding-top:6px;")
            fv.addWidget(lb)
        head("Fill")
        fr = QHBoxLayout()
        self.fill_on = QCheckBox("Colour")
        self.fill_btn = QPushButton()
        self.fill_btn.setFixedSize(38, 24)
        self.fill_btn.clicked.connect(lambda: self._pick("fill"))
        fr.addWidget(self.fill_on)
        fr.addStretch()
        fr.addWidget(self.fill_btn)
        fv.addLayout(fr)
        self.fill_on.toggled.connect(self._fill_toggle)
        head("Outline")
        orow = QHBoxLayout()
        self.out_on = QCheckBox("Outline")
        self.out_btn = QPushButton()
        self.out_btn.setFixedSize(38, 24)
        self.out_btn.clicked.connect(lambda: self._pick("out"))
        self.out_w = QSpinBox()
        self.out_w.setRange(1, 60)
        self.out_w.setMaximumWidth(60)
        orow.addWidget(self.out_on)
        orow.addStretch()
        orow.addWidget(self.out_w)
        orow.addWidget(self.out_btn)
        fv.addLayout(orow)
        self.out_on.toggled.connect(lambda on: self._style_set("stroke", on=on))
        self.out_w.editingFinished.connect(lambda: self._style_set("stroke", size=self.out_w.value(), on=True))
        head("Object")
        orow = QHBoxLayout()
        orow.addWidget(QLabel("Opacity"))
        self.obj_op = QSlider(Qt.Horizontal)
        self.obj_op.setRange(0, 100)
        self.obj_op.setValue(100)
        orow.addWidget(self.obj_op, 1)
        self.obj_lbl = QLabel("100")
        orow.addWidget(self.obj_lbl)
        fv.addLayout(orow)
        self.obj_op.sliderPressed.connect(self._op_begin)
        self.obj_op.valueChanged.connect(self._op_change)
        self.obj_op.sliderReleased.connect(self._op_end)
        self._op_edit = None
        self.obj_blend = QComboBox()
        for k, n in BLEND:
            self.obj_blend.addItem(n, k)
        self.obj_blend.currentIndexChanged.connect(self._blend)
        fv.addWidget(self.obj_blend)
        v.addWidget(self.fx_box)
        self.x.editingFinished.connect(self._apply_pos)
        self.y.editingFinished.connect(self._apply_pos)
        self.w.valueChanged.connect(lambda _: self._prop("w"))
        self.h.valueChanged.connect(lambda _: self._prop("h"))
        self.txt = QWidget()
        t = QVBoxLayout(self.txt)
        t.setContentsMargins(0, 6, 0, 0)
        t.addWidget(QLabel("Text layer"))
        self.font = QFontComboBox()
        self.font.setSizeAdjustPolicy(QFontComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.font.setMinimumContentsLength(6)
        self.fsize = QSpinBox()
        self.fsize.setRange(4, 2000)
        self.fsize.setSuffix(" px")
        t.addWidget(self.font)
        t.addWidget(self.fsize)
        b = QPushButton("Change text")
        b.clicked.connect(self._text_apply)
        t.addWidget(b)
        v.addWidget(self.txt)
        self.sel_lbl = QLabel()
        self.sel_lbl.setStyleSheet("padding-top:6px;")
        self.sel_lbl.setWordWrap(True)
        v.addWidget(self.sel_lbl)
        v.addStretch()
        self.ratio = 1.0
        self.text_hook = None             # set by the main window: re-render a text layer with new font/size

    def _cur(self):
        d = self.get_doc()
        return d, (d.layer() if d else None)

    def refresh(self):
        d, l = self._cur()
        self._busy = True
        if d is None:
            self.doc_lbl.setText("")
            self.lay_lbl.setText("")
            self.doc_lbl.hide()
            self.lay_lbl.hide()
            self.sel_lbl.setText("")
            self.txt.hide()
            self.fx_box.hide()
            for w in (self.x, self.y, self.w, self.h, self.apply):
                w.setEnabled(False)
            self._busy = False
            return
        self.doc_lbl.show()
        self.fx_box.show()
        self.lay_lbl.setVisible(l is not None)
        self.doc_lbl.setText(f"<b>Picture</b><br>{d.w} × {d.h} px   ·   {len(d.layers)} layer(s)")
        if l is not None:
            kind = "Text layer" if l.text else "Pixel layer"
            self.lay_lbl.setText(f"{l.name}  ({kind})")
            self.x.setValue(l.x)
            self.y.setValue(l.y)
            self.w.setValue(l.image.width())
            self.h.setValue(l.image.height())
            self.ratio = l.image.width() / max(1, l.image.height())
            for w in (self.x, self.y, self.w, self.h, self.apply):
                w.setEnabled(not l.locked)
            st = l.style or render.new_style()
            if l.text:
                self.fill_on.setChecked(True)
                self.fill_on.setEnabled(False)
                self._paint_btn(self.fill_btn, l.text.get("color", "#000000"))
            else:
                self.fill_on.setEnabled(not l.adj)
                self.fill_on.setChecked(bool(st["overlay"]["on"]))
                self._paint_btn(self.fill_btn, st["overlay"]["color"])
            self.out_on.setChecked(bool(st["stroke"]["on"]))
            self.out_w.setValue(int(st["stroke"]["size"]))
            self._paint_btn(self.out_btn, st["stroke"]["color"])
            self.obj_op.setValue(int(round(l.opacity * 100)))
            self.obj_lbl.setText(str(int(round(l.opacity * 100))))
            self.obj_blend.setCurrentIndex(max(0, self.obj_blend.findData(l.blend)))
            self.txt.setVisible(bool(l.text))
            if l.text:
                self.fsize.setValue(int(l.text.get("size", 48)))
                f = l.text.get("font")
                if f:
                    self.font.setCurrentText(str(f))
        sel = d.selection
        if sel is not None:
            b = sel.bbox()
            if not b.isEmpty():
                self.sel_lbl.setText(f"<b>Selection</b><br>{b.x()}, {b.y()}  ·  {b.width()} × {b.height()} px")
            else:
                self.sel_lbl.setText("<b>Selection</b><br>empty")
        else:
            self.sel_lbl.setText("<b>Selection</b><br>none")
        self._busy = False

    def _prop(self, which):
        if self._busy or not self.keep.isChecked():
            return
        self._busy = True
        if which == "w":
            self.h.setValue(max(1, round(self.w.value() / self.ratio)))
        else:
            self.w.setValue(max(1, round(self.h.value() * self.ratio)))
        self._busy = False

    # ---- fill / outline / object
    @staticmethod
    def _paint_btn(btn, color):
        btn.setStyleSheet(f"background:{color}; border:1px solid #888; border-radius:4px;")
        btn.setProperty("col", color)

    def _style_set(self, key, **kw):
        d, l = self._cur()
        if d is None or l is None or self._busy or l.adj:
            return
        st = copy.deepcopy(l.style) if l.style else render.new_style()
        st[key].update(kw)
        with d.edit("Layer style", [l]):
            l.style = st if render.style_active(st) else None

    def _pick(self, which):
        d, l = self._cur()
        if d is None or l is None or l.adj:
            return
        btn = self.fill_btn if which == "fill" else self.out_btn
        c = QColorDialog.getColor(QColor(btn.property("col") or "#000000"), self.window(), "Colour")
        if not c.isValid():
            return
        self._paint_btn(btn, c.name())
        if which == "fill":
            if l.text:
                sp = dict(l.text, color=c.name())
                with d.edit("Text colour", [l]):
                    l.image = render_text(sp)
                    l.text = sp
            else:
                self.fill_on.blockSignals(True)
                self.fill_on.setChecked(True)
                self.fill_on.blockSignals(False)
                self._style_set("overlay", on=True, color=c.name())
        else:
            self._style_set("stroke", on=True, color=c.name())

    def _fill_toggle(self, on):
        d, l = self._cur()
        if l is not None and not l.text and not self._busy:
            self._style_set("overlay", on=on)

    def _op_begin(self):
        d, l = self._cur()
        if d is not None and l is not None:
            self._op_edit = d.edit("Opacity")
            self._op_edit.__enter__()

    def _op_change(self, val):
        d, l = self._cur()
        if d is None or l is None or self._busy:
            return
        self.obj_lbl.setText(str(val))
        if self._op_edit is None:
            with d.edit("Opacity"):
                l.opacity = val / 100.0
        else:
            l.opacity = val / 100.0
            d.invalidate()
            d.changed()

    def _op_end(self):
        if self._op_edit is not None:
            self._op_edit.__exit__(None, None, None)
            self._op_edit = None

    def _blend(self):
        d, l = self._cur()
        if d is not None and l is not None and not self._busy:
            with d.edit("Blend mode"):
                l.blend = self.obj_blend.currentData()

    def _apply_pos(self):
        d, l = self._cur()
        if d is not None and l is not None and not self._busy and (self.x.value(), self.y.value()) != (l.x, l.y):
            ops.move_layer_to(d, self.x.value(), self.y.value())

    def _apply_size(self):
        d, l = self._cur()
        if d is not None and l is not None and (self.w.value(), self.h.value()) != (l.image.width(), l.image.height()):
            ops.resize_layer(d, self.w.value(), self.h.value())

    def _text_apply(self):
        if self.text_hook:
            self.text_hook(self.font.currentFont().family(), self.fsize.value())
