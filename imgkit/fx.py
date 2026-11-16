"""Dialogs for layer styles and for adjustment layers (live preview, Cancel puts everything back)."""
import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout)

from . import adjlayers, ops, render


class _Color(QPushButton):
    def __init__(self, value, on_change):
        super().__init__()
        self.value = value
        self.on_change = on_change
        self.setFixedSize(46, 22)
        self._paint()
        self.clicked.connect(self._pick)

    def _paint(self):
        self.setStyleSheet(f"background:{self.value}; border:1px solid #666;")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.value), self)
        if c.isValid():
            self.value = c.name()
            self._paint()
            self.on_change()


class StyleDialog(QDialog):
    """drop shadow, outer glow, stroke, colour overlay of the active layer"""
    SPEC = {
        "shadow": ("Drop shadow", [("dx", "Right", -100, 100), ("dy", "Down", -100, 100), ("blur", "Blur", 0, 60), ("opacity", "Opacity", 0, 100)], True),
        "glow": ("Outer glow", [("size", "Size", 1, 80), ("opacity", "Opacity", 0, 100)], True),
        "stroke": ("Stroke (outline)", [("size", "Size", 1, 60), ("opacity", "Opacity", 0, 100)], True),
        "overlay": ("Colour overlay", [("opacity", "Opacity", 0, 100)], True),
    }

    def __init__(self, parent, doc):
        super().__init__(parent)
        self.setWindowTitle("Layer style")
        self.doc, self.layer = doc, doc.layer()
        self.orig = copy.deepcopy(self.layer.style)
        self.st = copy.deepcopy(self.layer.style) if self.layer.style else render.new_style()
        for k, v in render.new_style().items():
            self.st.setdefault(k, v)
        lay = QVBoxLayout(self)
        self.boxes = {}
        for key, (title, sliders, color) in self.SPEC.items():
            g = QGroupBox()
            gl = QVBoxLayout(g)
            top = QHBoxLayout()
            cb = QCheckBox(title)
            cb.setStyleSheet("font-weight:bold;")
            cb.setChecked(self.st[key]["on"])
            cb.toggled.connect(lambda on, k=key: self._set(k, "on", on))
            top.addWidget(cb)
            top.addStretch()
            top.addWidget(QLabel("Colour"))
            top.addWidget(_Color(self.st[key]["color"], lambda k=key: None))
            col = top.itemAt(top.count() - 1).widget()
            col.on_change = lambda k=key, c=col: self._set(k, "color", c.value)
            gl.addLayout(top)
            form = QFormLayout()
            for sk, label, lo, hi in sliders:
                s = QSlider(Qt.Horizontal)
                s.setRange(lo, hi)
                s.setValue(int(self.st[key][sk]))
                s.setMinimumWidth(220)
                s.valueChanged.connect(lambda v, k=key, sk=sk: self._set(k, sk, v))
                form.addRow(label, s)
            gl.addLayout(form)
            lay.addWidget(g)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.finished.connect(self._done)

    def _set(self, k, sk, v):
        self.st[k][sk] = v
        self.layer.style = copy.deepcopy(self.st)
        self.doc.invalidate()
        self.doc.changed()

    def _done(self, code):
        self.layer.style = copy.deepcopy(self.orig)
        if code:
            ops.set_style(self.doc, self.st if render.style_active(self.st) else None)
        else:
            self.doc.invalidate()
            self.doc.changed()


class AdjustLayerDialog(QDialog):
    """edit the settings of an adjustment layer; the picture changes while you move the sliders"""

    def __init__(self, parent, doc, layer):
        super().__init__(parent)
        self.doc, self.layer = doc, layer
        kind = layer.adj["kind"]
        name, spec, _fn = adjlayers.KINDS[kind]
        self.setWindowTitle(name)
        self.orig = copy.deepcopy(layer.adj)
        self.params = dict(adjlayers.defaults(kind))
        self.params.update(layer.adj.get("params", {}))
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.sl = {}
        for key, label, lo, hi, de, *scale in spec:
            sc = scale[0] if scale else 1
            row = QHBoxLayout()
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setValue(int(round(self.params.get(key, de / sc) * sc)))
            s.setMinimumWidth(240)
            v = QLabel(self._fmt(s.value(), sc))
            v.setFixedWidth(52)
            s.valueChanged.connect(lambda val, v=v, sc=sc: v.setText(self._fmt(val, sc)))
            s.valueChanged.connect(lambda val, key=key, sc=sc: self._set(key, val / sc if sc != 1 else val))
            rb = QPushButton("↺")
            rb.setFixedWidth(28)
            rb.clicked.connect(lambda _=False, s=s, de=de: s.setValue(de))
            row.addWidget(s, 1)
            row.addWidget(v)
            row.addWidget(rb)
            form.addRow(label, row)
        if not spec:
            lay.addWidget(QLabel("This adjustment has no settings. Use the layer opacity and the mask to control it."))
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.finished.connect(self._done)

    @staticmethod
    def _fmt(v, sc):
        return f"{v / sc:.2f}" if sc != 1 else str(v)

    def _set(self, key, val):
        self.params[key] = val
        self.layer.adj = {"kind": self.orig["kind"], "params": dict(self.params)}
        self.doc.invalidate()
        self.doc.changed()

    def _done(self, code):
        self.layer.adj = copy.deepcopy(self.orig)
        if code:
            ops.set_adjustment(self.doc, self.layer, self.params)
        else:
            self.doc.invalidate()
            self.doc.changed()
