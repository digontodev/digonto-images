"""Retouching brushes: clone stamp, healing brush, spot healing, smudge, blur, sharpen, dodge, burn."""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

from . import arr
from .select import blur
from .tools import Tool


def _f(img, r):
    """premultiplied float RGBA (0..1) of rect r of a picture; outside the picture = empty"""
    return arr.to_array(img.copy(r), straight=False).astype(np.float32) / 255.0


def _put(L, r, a):
    out = arr.from_array(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8), straight=False)
    p = QPainter(L.image)
    p.setCompositionMode(QPainter.CompositionMode_Source)
    p.drawImage(r.x(), r.y(), out)
    p.end()


def _fix(a):
    a[..., :3] = np.minimum(a[..., :3], a[..., 3:4])      # premultiplied: colour never above alpha
    return np.clip(a, 0, 1)


def _lowpass(a, radius):
    return blur(a, max(1.0, radius))


def _brush_mask(r, cx, cy, rad, hardness):
    h, w = r.height(), r.width()
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.hypot(xx + r.x() + 0.5 - cx, yy + r.y() + 0.5 - cy) / max(0.5, rad)
    hd = max(0.0, min(0.98, hardness / 100.0))
    return np.clip((1.0 - d) / (1.0 - hd), 0, 1)


def _sel_region(doc, L, r):
    sel = doc.selection
    if sel is None:
        return None
    out = np.zeros((r.height(), r.width()), np.float32)
    x0, y0 = max(0, r.x() + L.x), max(0, r.y() + L.y)
    x1, y1 = min(doc.w, r.x() + L.x + r.width()), min(doc.h, r.y() + L.y + r.height())
    if x1 > x0 and y1 > y0:
        out[y0 - r.y() - L.y:y1 - r.y() - L.y, x0 - r.x() - L.x:x1 - r.x() - L.x] = sel.mask[y0:y1, x0:x1] / 255.0
    return out


class _Stroke(Tool):
    """base: a brush that changes the pixels under it dab by dab"""
    label = "Retouch"
    spacing = 0.12
    cursor = Qt.CrossCursor

    def press(self, c, p, ev):
        self.edit = None
        d = c.doc
        L = d.layer()
        if L is None or not c.layer_ok():
            return
        if not self.begin(c, p, ev, L):
            return
        self.layer, self.last = L, p
        self.edit = d.edit(self.label, [L])
        self.edit.__enter__()
        self.dab(c, p, True)
        c.doc.invalidate(self._r(p, p, c))
        c.update_rect(self._r(p, p, c))

    def begin(self, c, p, ev, L):
        return True

    def _r(self, a, b, c):
        s = c.state.size + 6
        return QRectF(a, b).normalized().adjusted(-s, -s, s, s).toAlignedRect()

    def move(self, c, p, ev):
        if self.edit is None:
            return
        step = max(1.0, c.state.size * self.spacing)
        a, b = self.last, p
        dist = math.hypot(b.x() - a.x(), b.y() - a.y())
        n = int(dist // step)
        for i in range(1, n + 1):
            t = i * step / dist
            self.dab(c, QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t), False)
        if n:
            t = n * step / dist
            self.last = QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)
        r = self._r(a, b, c)
        c.doc.invalidate(r)
        c.update_rect(r)

    def release(self, c, p, ev):
        if self.edit is None:
            return
        self.end(c)
        self.edit.__exit__(None, None, None)
        self.edit = None

    def end(self, c):
        pass

    def dab_rect(self, c, p, L):
        rad = c.state.size / 2.0
        r = QRect(int(math.floor(p.x() - L.x - rad)), int(math.floor(p.y() - L.y - rad)), int(math.ceil(rad * 2)) + 1, int(math.ceil(rad * 2)) + 1)
        r = r.intersected(QRect(0, 0, L.image.width(), L.image.height()))
        return r, rad

    def dab(self, c, p, first):
        L, s = self.layer, c.state
        r, rad = self.dab_rect(c, p, L)
        if r.isEmpty():
            return
        m = _brush_mask(r, p.x() - L.x, p.y() - L.y, rad, s.hardness)
        sel = _sel_region(c.doc, L, r)
        if sel is not None:
            m = m * sel
        dst = _f(L.image, r)
        new = self.process(c, p, L, r, dst, m, first)
        if new is None:
            return
        m4 = (m * (s.opacity / 100.0 if self.use_opacity else 1.0))[..., None]
        _put(L, r, _fix(dst * (1 - m4) + new * m4))

    use_opacity = True

    def process(self, c, p, L, r, dst, m, first):
        return None

    def overlay(self, c, painter):
        if c.hover is not None:
            rr = c.state.size * c.zoom / 2.0
            w = c.to_w(c.hover)
            painter.setPen(QPen(QColor(0, 0, 0, 200), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(w, rr, rr)
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1, Qt.DotLine))
            painter.drawEllipse(w, rr, rr)


class CloneTool(_Stroke):
    """Alt + click = choose what to copy, then paint where it should go"""
    name = "clone"
    label = "Clone stamp"
    heal = False
    spacing = 0.1

    def __init__(self):
        self.source = None            # doc point chosen with Alt-click
        self.offset = None            # source - first paint point

    def begin(self, c, p, ev, L):
        if ev.modifiers() & Qt.AltModifier:
            self.source, self.offset = QPointF(p), None
            c.message.emit("Source set. Now paint where it should be copied to.")
            c.update()
            return False
        if self.source is None:
            c.message.emit("Alt + click first, to choose the part to copy.")
            return False
        if self.offset is None:
            self.offset = QPointF(self.source.x() - p.x(), self.source.y() - p.y())
        return True

    def _source(self, c, L, r):
        dx, dy = int(round(self.offset.x())), int(round(self.offset.y()))
        if c.state.sample_layer:
            return _f(L.image, QRect(r.x() + dx, r.y() + dy, r.width(), r.height()))
        return _f(c.doc.merged(), QRect(r.x() + L.x + dx, r.y() + L.y + dy, r.width(), r.height()))

    def process(self, c, p, L, r, dst, m, first):
        src = self._source(c, L, r)
        if not self.heal:
            return src
        rl = max(2.0, c.state.size / 3.0)
        k = ((1 - m) ** 2)[..., None] + 1e-4              # colour and light come from the edge of the brush, not from the spot itself
        low = _lowpass(dst * k, rl) / np.maximum(_lowpass(k, rl), 1e-4)
        return _fix(src - _lowpass(src, rl) + low)

    def overlay(self, c, painter):
        super().overlay(c, painter)
        pts = []
        if self.source is not None and self.offset is None:
            pts.append(self.source)
        elif self.offset is not None and c.hover is not None:
            pts.append(QPointF(c.hover.x() + self.offset.x(), c.hover.y() + self.offset.y()))
        for q in pts:
            w = c.to_w(q)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawLine(QPointF(w.x() - 9, w.y()), QPointF(w.x() + 9, w.y()))
            painter.drawLine(QPointF(w.x(), w.y() - 9), QPointF(w.x(), w.y() + 9))
            painter.setPen(QPen(QColor(0, 128, 90), 1))
            painter.drawLine(QPointF(w.x() - 9, w.y()), QPointF(w.x() + 9, w.y()))
            painter.drawLine(QPointF(w.x(), w.y() - 9), QPointF(w.x(), w.y() + 9))


class HealTool(CloneTool):
    name = "heal"
    label = "Healing brush"
    heal = True


class SmudgeTool(_Stroke):
    name = "smudge"
    label = "Smudge"
    spacing = 0.08

    def process(self, c, p, L, r, dst, m, first):
        s = c.state.opacity / 100.0
        if first or getattr(self, "buf", None) is None or self.buf.shape != dst.shape:
            self.buf = dst.copy()
            return None
        k = (m * s)[..., None]
        out = dst * (1 - k) + self.buf * k
        self.buf = self.buf * 0.5 + out * 0.5            # the finger picks up what it touches
        return out

    use_opacity = False

    def begin(self, c, p, ev, L):
        self.buf = None
        return True


class _Filter(_Stroke):
    spacing = 0.1


class BlurBrush(_Filter):
    name = "blurbrush"
    label = "Blur brush"

    def process(self, c, p, L, r, dst, m, first):
        return _lowpass(dst, max(1.5, c.state.size / 14.0))


class SharpenBrush(_Filter):
    name = "sharpenbrush"
    label = "Sharpen brush"

    def process(self, c, p, L, r, dst, m, first):
        low = _lowpass(dst, max(1.5, c.state.size / 14.0))
        return _fix(dst + (dst - low) * 1.5)


class DodgeTool(_Filter):
    name = "dodge"
    label = "Dodge (lighten)"
    sign = 1

    def process(self, c, p, L, r, dst, m, first):
        out = dst.copy()
        e = 0.12
        a = dst[..., 3:4]
        out[..., :3] = dst[..., :3] + (a - dst[..., :3]) * e if self.sign > 0 else dst[..., :3] * (1 - e)
        return out


class BurnTool(DodgeTool):
    name = "burn"
    label = "Burn (darken)"
    sign = -1


class SpotHealTool(Tool):
    """paint over a spot or blemish: it is filled with the surrounding picture and blended in"""
    name = "spot"
    cursor = Qt.CrossCursor

    def __init__(self):
        self.pts = []
        self.active = False

    def press(self, c, p, ev):
        if not c.layer_ok():
            return
        self.pts, self.active = [QPointF(p)], True
        self.hover_pt = p

    def move(self, c, p, ev):
        if self.active:
            self.pts.append(QPointF(p))
            c.update()

    def overlay(self, c, painter):
        if c.hover is not None:
            rr = c.state.size * c.zoom / 2.0
            w = c.to_w(c.hover)
            painter.setPen(QPen(QColor(0, 0, 0, 200), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(w, rr, rr)
        if self.active and self.pts:
            path = QPainterPath()
            path.moveTo(c.to_w(self.pts[0]))
            for q in self.pts[1:]:
                path.lineTo(c.to_w(q))
            painter.setPen(QPen(QColor(0, 128, 90, 120), max(2.0, c.state.size * c.zoom), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

    def release(self, c, p, ev):
        if not self.active:
            return
        self.active = False
        pts, self.pts = self.pts, []
        d, L = c.doc, c.doc.layer()
        if L is None or not pts:
            return
        s = c.state
        size = max(3, s.size)
        pad = max(10, int(size * 0.9))
        xs, ys = [q.x() - L.x for q in pts], [q.y() - L.y for q in pts]
        box = QRect(int(min(xs) - size / 2 - pad), int(min(ys) - size / 2 - pad), int(max(xs) - min(xs) + size + 2 * pad), int(max(ys) - min(ys) + size + 2 * pad))
        box = box.intersected(QRect(0, 0, L.image.width(), L.image.height()))
        if box.width() < 4 or box.height() < 4:
            return
        mi = QImage(box.width(), box.height(), QImage.Format_Grayscale8)
        mi.fill(0)
        qp = QPainter(mi)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setPen(QPen(QColor(255, 255, 255), size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        path = QPainterPath()
        path.moveTo(xs[0] - box.x(), ys[0] - box.y())
        for x, y in zip(xs[1:], ys[1:]):
            path.lineTo(x - box.x(), y - box.y())
        if len(xs) == 1:
            path.lineTo(xs[0] - box.x() + 0.01, ys[0] - box.y())
        qp.drawPath(path)
        qp.end()
        mask = arr.to_mask(mi).astype(np.float32) / 255.0
        sel = _sel_region(d, L, box)
        if sel is not None:
            mask = mask * sel
        if mask.max() <= 0:
            return
        dst = _f(L.image, box)
        src_img = L.image if s.sample_layer else None
        ring = (blur(mask, 4) > 0.02) & (mask < 0.5)
        if ring.sum() < 8:
            return
        bw, bh = box.width(), box.height()
        base = QRect(0, 0, L.image.width(), L.image.height())
        ys_, xs_ = np.nonzero(mask > 0.05)
        mx0, mx1, my0, my1 = xs_.min(), xs_.max(), ys_.min(), ys_.max()
        step = max(4, size // 2)
        cands = []
        for dy in range(-box.y(), base.height() - box.y() - bh + 1, step):
            for dx in range(-box.x(), base.width() - box.x() - bw + 1, step):
                # the source must not contain the spot itself
                if abs(dx) > (mx1 - mx0 + 4) or abs(dy) > (my1 - my0 + 4):
                    cands.append((dx, dy))
        if len(cands) > 160:
            rng = np.random.RandomState(7)
            cands = [cands[i] for i in rng.choice(len(cands), 160, replace=False)]
        best, best_cost = None, 1e30
        for dx, dy in cands:
            rr = QRect(box.x() + dx, box.y() + dy, bw, bh)
            cand = _f(L.image, rr)
            cost = float(((cand - dst)[ring][:, :3] ** 2).sum() / ring.sum())
            if cost < best_cost:
                best, best_cost = cand, cost
        if best is None:
            return
        rl = max(2.0, size / 5.0)
        k = (1 - np.clip(blur(mask, 2), 0, 1))[..., None]
        low = _lowpass(dst * k, rl) / np.maximum(_lowpass(k, rl), 1e-3)
        new = _fix(best - _lowpass(best, rl) + low)
        mf = np.clip(blur(mask, max(1.0, size / 8.0)) * 1.2, 0, 1)
        mf = np.maximum(mf, mask)[..., None]
        with d.edit("Spot healing", [L]):
            _put(L, box, _fix(dst * (1 - mf) + new * mf))
