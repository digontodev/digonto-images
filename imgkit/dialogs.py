"""Dialogs: new picture, sizes, adjustments with live preview, curves, levels, text."""
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFontComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QRadioButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from . import adjust, arr, ops


def _buttons(dlg, ok="OK"):
    b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    b.button(QDialogButtonBox.Ok).setText(ok)
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    return b


class NewDialog(QDialog):
    PRESETS = [("Custom", 0, 0), ("Web banner  1920 x 1080", 1920, 1080), ("Square post  1080 x 1080", 1080, 1080),
               ("Story  1080 x 1920", 1080, 1920), ("A4 at 300 dpi  2480 x 3508", 2480, 3508), ("Icon  512 x 512", 512, 512),
               ("Photo 3:2  3000 x 2000", 3000, 2000)]

    def __init__(self, parent, w=1920, h=1080):
        super().__init__(parent)
        self.setWindowTitle("New picture")
        f = QFormLayout(self)
        self.pre = QComboBox()
        for t, _w, _h in self.PRESETS:
            self.pre.addItem(t)
        self.w, self.h = QSpinBox(), QSpinBox()
        for s in (self.w, self.h):
            s.setRange(1, 20000)
        self.w.setValue(w)
        self.h.setValue(h)
        self.bg = QComboBox()
        self.bg.addItems(["White", "Transparent", "Front colour", "Black"])
        self.pre.currentIndexChanged.connect(self._pre)
        f.addRow("Preset", self.pre)
        f.addRow("Width (px)", self.w)
        f.addRow("Height (px)", self.h)
        f.addRow("Background", self.bg)
        f.addRow(_buttons(self, "Create"))

    def _pre(self, i):
        _t, w, h = self.PRESETS[i]
        if w:
            self.w.setValue(w)
            self.h.setValue(h)

    def values(self, fg):
        c = {"White": "#FFFFFF", "Transparent": None, "Front colour": fg.name(), "Black": "#000000"}[self.bg.currentText()]
        return self.w.value(), self.h.value(), c


class ImageSizeDialog(QDialog):
    def __init__(self, parent, w, h):
        super().__init__(parent)
        self.setWindowTitle("Image size")
        self.r = w / h
        f = QFormLayout(self)
        self.w, self.h = QSpinBox(), QSpinBox()
        for s in (self.w, self.h):
            s.setRange(1, 30000)
        self.w.setValue(w)
        self.h.setValue(h)
        self.keep = QCheckBox("Keep proportions")
        self.keep.setChecked(True)
        self.smooth = QCheckBox("Smooth (better for photos)")
        self.smooth.setChecked(True)
        self.w.valueChanged.connect(lambda v: self._link(True, v))
        self.h.valueChanged.connect(lambda v: self._link(False, v))
        f.addRow("Width (px)", self.w)
        f.addRow("Height (px)", self.h)
        f.addRow(self.keep)
        f.addRow(self.smooth)
        f.addRow(_buttons(self, "Resize"))

    def _link(self, from_w, v):
        if not self.keep.isChecked():
            return
        tgt, val = (self.h, round(v / self.r)) if from_w else (self.w, round(v * self.r))
        tgt.blockSignals(True)
        tgt.setValue(max(1, val))
        tgt.blockSignals(False)


class CanvasSizeDialog(QDialog):
    def __init__(self, parent, w, h):
        super().__init__(parent)
        self.setWindowTitle("Canvas size")
        f = QFormLayout(self)
        self.w, self.h = QSpinBox(), QSpinBox()
        for s in (self.w, self.h):
            s.setRange(1, 30000)
        self.w.setValue(w)
        self.h.setValue(h)
        f.addRow("Width (px)", self.w)
        f.addRow("Height (px)", self.h)
        g = QGridLayout()
        self.anchor = (0.5, 0.5)
        self.btns = []
        for r in range(3):
            for c in range(3):
                b = QRadioButton()
                b.setChecked(r == 1 and c == 1)
                b.toggled.connect(lambda on, r=r, c=c: on and setattr(self, "anchor", (c / 2.0, r / 2.0)))
                g.addWidget(b, r, c)
        f.addRow("Keep the picture at", g)
        f.addRow(QLabel("The new area is transparent."))
        f.addRow(_buttons(self, "Apply"))


class TextDialog(QDialog):
    def __init__(self, parent, spec):
        super().__init__(parent)
        self.setWindowTitle("Text")
        self.resize(460, 380)
        lay = QVBoxLayout(self)
        self.txt = QPlainTextEdit()
        self.txt.setPlainText(spec.get("text", ""))
        self.txt.setMinimumHeight(110)
        lay.addWidget(self.txt)
        row = QHBoxLayout()
        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(spec.get("font", "Sans Serif")))
        self.size = QSpinBox()
        self.size.setRange(4, 2000)
        self.size.setValue(int(spec.get("size", 64)))
        self.size.setSuffix(" px")
        row.addWidget(self.font, 1)
        row.addWidget(self.size)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.bold = QCheckBox("Bold")
        self.bold.setChecked(bool(spec.get("bold")))
        self.italic = QCheckBox("Italic")
        self.italic.setChecked(bool(spec.get("italic")))
        self.align = QComboBox()
        for k in ("left", "center", "right"):
            self.align.addItem(k.title(), k)
        self.align.setCurrentIndex(max(0, self.align.findData(spec.get("align", "left"))))
        self.color = QColor(spec.get("color", "#000000"))
        self.cbtn = QPushButton("Colour")
        self.cbtn.clicked.connect(self._color)
        self._paint_btn()
        for w in (self.bold, self.italic, self.align, self.cbtn):
            row.addWidget(w)
        lay.addLayout(row)
        self.preview = QLabel()
        self.preview.setMinimumHeight(90)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#fff; border:1px solid #aaa;")
        lay.addWidget(self.preview)
        for w, sig in ((self.txt, "textChanged"), (self.font, "currentFontChanged"), (self.size, "valueChanged"), (self.bold, "toggled"),
                       (self.italic, "toggled"), (self.align, "currentIndexChanged")):
            getattr(w, sig).connect(self._prev)
        lay.addWidget(_buttons(self, "OK"))
        self._prev()

    def _paint_btn(self):
        self.cbtn.setStyleSheet(f"background:{self.color.name()}; color:{'#000' if self.color.lightness() > 128 else '#fff'};")

    def _color(self):
        c = QColorDialog.getColor(self.color, self, "Text colour")
        if c.isValid():
            self.color = c
            self._paint_btn()
            self._prev()

    def spec(self):
        return dict(text=self.txt.toPlainText(), font=self.font.currentFont().family(), size=self.size.value(), bold=self.bold.isChecked(),
                    italic=self.italic.isChecked(), align=self.align.currentData(), color=self.color.name())

    def _prev(self, *_):
        from .tools import render_text
        s = self.spec()
        s["size"] = min(s["size"], 40)
        from PySide6.QtGui import QPixmap
        self.preview.setPixmap(QPixmap.fromImage(render_text(s)).scaled(self.preview.width() - 8, 84, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class TransformDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Transform layer")
        f = QFormLayout(self)
        self.sx, self.sy = QDoubleSpinBox(), QDoubleSpinBox()
        for s in (self.sx, self.sy):
            s.setRange(1, 2000)
            s.setValue(100)
            s.setSuffix(" %")
        self.keep = QCheckBox("Same scale for both")
        self.keep.setChecked(True)
        self.sx.valueChanged.connect(lambda v: self.keep.isChecked() and self.sy.setValue(v))
        self.ang = QDoubleSpinBox()
        self.ang.setRange(-360, 360)
        self.ang.setSuffix(" °")
        f.addRow("Width", self.sx)
        f.addRow("Height", self.sy)
        f.addRow(self.keep)
        f.addRow("Rotate", self.ang)
        f.addRow(_buttons(self, "Apply"))


class ExportDialog(QDialog):
    def __init__(self, parent, ext):
        super().__init__(parent)
        self.setWindowTitle("Export options")
        f = QFormLayout(self)
        self.q = QSlider(Qt.Horizontal)
        self.q.setRange(10, 100)
        self.q.setValue(90)
        self.lbl = QLabel("90")
        self.q.valueChanged.connect(lambda v: self.lbl.setText(str(v)))
        row = QHBoxLayout()
        row.addWidget(self.q)
        row.addWidget(self.lbl)
        f.addRow("Quality", row)
        self.bg = QComboBox()
        self.bg.addItems(["White", "Black"])
        if ext in ("jpg", "jpeg", "bmp"):
            f.addRow("Transparent parts become", self.bg)
        f.addRow(_buttons(self, "Export"))

    def values(self):
        return self.q.value(), "#FFFFFF" if self.bg.currentText() == "White" else "#000000"


# ---------------------------------------------------------------------------------------------- adjustments
class AdjustDialog(QDialog):
    """sliders -> fn(array, **values). The result shows live on the picture; Cancel puts everything back."""

    def __init__(self, parent, doc, title, spec, fn, fast=True, header=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.doc, self.fn, self.spec = doc, fn, spec
        self.layer = doc.layer()
        self.orig_image = self.layer.image
        self.base = arr.to_array(self.layer.image)
        big = self.base.shape[0] * self.base.shape[1] > 1_200_000
        self.live = fast or not big
        lay = QVBoxLayout(self)
        if header is not None:
            lay.addWidget(header)
        form = QFormLayout()
        self.ctrl = {}
        for key, label, lo, hi, de, *scale in spec:
            sc = scale[0] if scale else 1
            row = QHBoxLayout()
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setValue(de)
            s.setMinimumWidth(240)
            v = QLabel(self._fmt(de, sc))
            v.setFixedWidth(52)
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            s.valueChanged.connect(lambda val, v=v, sc=sc: v.setText(self._fmt(val, sc)))
            s.valueChanged.connect(self._changed)
            rb = QPushButton("↺")
            rb.setFixedWidth(28)
            rb.setToolTip("Reset")
            rb.clicked.connect(lambda _=False, s=s, de=de: s.setValue(de))
            row.addWidget(s, 1)
            row.addWidget(v)
            row.addWidget(rb)
            form.addRow(label, row)
            self.ctrl[key] = (s, sc)
        lay.addLayout(form)
        pr = QHBoxLayout()
        self.pv = QCheckBox("Preview")
        self.pv.setChecked(self.live)
        self.pv.toggled.connect(self._changed)
        pr.addWidget(self.pv)
        if not self.live:
            pr.addWidget(QLabel("(large picture: preview is slow)"))
        pr.addStretch()
        lay.addLayout(pr)
        lay.addWidget(_buttons(self, "Apply"))
        self.t = QTimer(self)
        self.t.setSingleShot(True)
        self.t.timeout.connect(self._preview)
        self.finished.connect(self._done)
        self._changed()

    @staticmethod
    def _fmt(v, sc):
        return f"{v / sc:.2f}" if sc != 1 else str(v)

    def values(self):
        return {k: s.value() / sc if sc != 1 else s.value() for k, (s, sc) in self.ctrl.items()}

    def _changed(self, *_):
        self.t.start(60)

    def _preview(self):
        if not self.pv.isChecked():
            self._restore()
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = ops.masked(self.doc, self.layer, self.base, self.fn(self.base, **self.values()))
            self.layer.image = arr.from_array(res)
        finally:
            QApplication.restoreOverrideCursor()
        self.doc.invalidate()
        self.doc.changed(None)

    def _restore(self):
        self.layer.image = self.orig_image
        self.doc.invalidate()
        self.doc.changed(None)

    def _done(self, code):
        self.layer.image = self.orig_image            # back to the real picture; Apply makes one clean history step
        self.doc.invalidate()
        if code == QDialog.Accepted:
            vals = self.values()
            ops.apply_array(self.doc, self.windowTitle(), lambda a: self.fn(a, **vals))
        else:
            self.doc.changed(None)
            self.doc.dirty = getattr(self, "_was_dirty", self.doc.dirty)


class HistogramView(QWidget):
    def __init__(self, a):
        super().__init__()
        self.setFixedHeight(80)
        h = adjust.histogram(a)[3].astype(np.float64)
        self.h = np.log1p(h) / max(1e-9, np.log1p(h).max())

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#F4F4F4"))
        p.setPen(QPen(QColor("#777"), 1))
        w, hh = self.width(), self.height()
        for x in range(256):
            bh = self.h[x] * (hh - 4)
            xx = x * (w - 1) / 255.0
            p.drawLine(QPointF(xx, hh), QPointF(xx, hh - bh))


def levels_dialog(parent, doc):
    a = arr.to_array(doc.layer().image)
    spec = [("black", "Shadows", 0, 250, 0), ("gamma", "Midtones", 10, 400, 100, 100), ("white", "Highlights", 5, 255, 255)]
    return AdjustDialog(parent, doc, "Levels", spec, lambda a, black, gamma, white: adjust.levels(a, int(black), int(max(black + 1, white)), gamma),
                        header=HistogramView(a))


class CurveWidget(QWidget):
    def __init__(self, on_change):
        super().__init__()
        self.setFixedSize(260, 260)
        self.pts = [(0, 0), (255, 255)]
        self.on_change = on_change
        self.drag = None

    def _w(self, p):
        return QPointF(4 + p[0] * 252 / 255.0, 256 - p[1] * 252 / 255.0)

    def _p(self, w):
        return (max(0, min(255, int(round((w.x() - 4) * 255 / 252.0)))), max(0, min(255, int(round((256 - w.y()) * 255 / 252.0)))))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#FAFAFA"))
        p.setPen(QPen(QColor("#DDD"), 1))
        for i in range(5):
            p.drawLine(QPointF(4 + i * 63, 4), QPointF(4 + i * 63, 256))
            p.drawLine(QPointF(4, 4 + i * 63), QPointF(256, 4 + i * 63))
        lut = adjust.lut_from_points(self.pts)
        path = QPainterPath(self._w((0, int(lut[0]))))
        for x in range(1, 256):
            path.lineTo(self._w((x, int(lut[x]))))
        p.setPen(QPen(QColor("#C2395C"), 2))
        p.drawPath(path)
        p.setBrush(QColor("#fff"))
        p.setPen(QPen(QColor("#4A1F6E"), 2))
        for q in self.pts:
            p.drawEllipse(self._w(q), 5, 5)

    def _hit(self, pos):
        for i, q in enumerate(self.pts):
            w = self._w(q)
            if abs(w.x() - pos.x()) < 8 and abs(w.y() - pos.y()) < 8:
                return i
        return None

    def mousePressEvent(self, ev):
        i = self._hit(ev.position())
        if ev.button() == Qt.RightButton:
            if i is not None and 0 < i < len(self.pts) - 1:
                del self.pts[i]
                self.update()
                self.on_change()
            return
        if i is None:
            q = self._p(ev.position())
            self.pts.append(q)
            self.pts.sort()
            i = self.pts.index(q)
        self.drag = i
        self.update()

    def mouseMoveEvent(self, ev):
        if self.drag is None:
            return
        q = self._p(ev.position())
        i = self.drag
        lo = self.pts[i - 1][0] + 1 if i > 0 else 0
        hi = self.pts[i + 1][0] - 1 if i < len(self.pts) - 1 else 255
        x = q[0] if 0 < i < len(self.pts) - 1 else self.pts[i][0]
        self.pts[i] = (max(lo, min(hi, x)), q[1])
        self.update()
        self.on_change()

    def mouseReleaseEvent(self, ev):
        self.drag = None


def curves_dialog(parent, doc):
    holder = {}
    cw = CurveWidget(lambda: holder["d"]._changed())
    hint = QLabel("Click to add a point, drag to bend, right-click a point to remove it.")
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.addWidget(cw, 0, Qt.AlignHCenter)
    v.addWidget(hint)
    d = AdjustDialog(parent, doc, "Curves", [("dummy", "", 0, 1, 0)], lambda a, dummy: adjust.curves(a, list(cw.pts)), header=box)
    holder["d"] = d
    return d


COLOR_BALANCE = [(f"{r}{c}", f"{rn} {cn}", -100, 100, 0) for r, rn in (("s", "Shadows"), ("m", "Midtones"), ("h", "Highlights"))
                 for c, cn in (("r", "red"), ("g", "green"), ("b", "blue"))]


def color_balance_fn(a, **k):
    return adjust.color_balance(a, (k["sr"], k["sg"], k["sb"]), (k["mr"], k["mg"], k["mb"]), (k["hr"], k["hg"], k["hb"]))
