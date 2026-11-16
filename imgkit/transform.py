"""Free transform with handles (Ctrl+T), quick selection brush, colour range."""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QTransform

from . import arr, ops
from .select import Selection
from .tools import Tool, selection_mode

HANDLE = 6          # half size of a handle square in pixels on screen


class TransformTool(Tool):
    """drag the handles to scale, drag inside to move, drag outside the box to rotate.
    Shift = keep proportions (corner handles) / 15° steps (rotate), Alt = from the centre. Enter applies, Esc cancels."""
    name = "transform"
    cursor = Qt.ArrowCursor

    def __init__(self):
        self.L = None
        self.mode = None

    # ---- session
    def start(self, c):
        d = c.doc
        L = d.layer() if d else None
        self.L = None
        if L is None or L.locked or L.adj or not L.visible:
            if d is not None:
                c.message.emit("Select an unlocked picture layer first.")
            return
        self.L = L
        self.oimg, self.omask, self.ox, self.oy = L._image, L._mask, L.x, L.y
        self.w0, self.h0 = L._image.width(), L._image.height()
        self.cx, self.cy = L.x + self.w0 / 2.0, L.y + self.h0 / 2.0
        self.sx = self.sy = 1.0
        self.ang = 0.0
        self.dirty = False
        # while you drag, the layer is drawn quickly on top of the picture instead of being recomputed; the real transform is made once at the end
        self.k = min(1.0, 1800.0 / max(self.w0, self.h0))
        self.proxy = self.oimg.scaled(max(1, int(self.w0 * self.k)), max(1, int(self.h0 * self.k)), Qt.IgnoreAspectRatio, Qt.FastTransformation) if self.k < 1 else self.oimg
        L._hide = True
        c.doc.invalidate(L.rect())
        c.message.emit("Free transform: drag handles (Shift = proportions, Alt = from centre), Enter = apply, Esc = cancel")
        c.update()

    def _apply_preview(self, smooth=False):
        L = self.L
        t = QTransform().rotate(self.ang).scale(self.sx, self.sy)
        mode = Qt.SmoothTransformation if smooth else Qt.FastTransformation
        L._image = self.oimg.transformed(t, mode).convertToFormat(arr.PM)
        L._mask = self.omask.transformed(t, mode).convertToFormat(arr.PM) if self.omask is not None else None
        L.x, L.y = int(round(self.cx - L._image.width() / 2.0)), int(round(self.cy - L._image.height() / 2.0))

    def _restore(self):
        L = self.L
        L._hide = False
        L._image, L._mask, L.x, L.y = self.oimg, self.omask, self.ox, self.oy

    def commit(self, c):
        if self.L is None:
            return
        L, d = self.L, c.doc
        if not self.dirty:
            L._hide = False
            self.L = None
            d.invalidate(L.rect())
            d.changed(L.rect())
            return
        self._apply_preview(True)
        img, mask, x, y = L._image, L._mask, L.x, L.y
        self._restore()
        self.L = None
        with d.edit("Free transform", [L]):
            L._image, L._mask, L.x, L.y = img, mask, x, y
            L.text = None

    def cancel(self, c):
        if self.L is None:
            return
        self._restore()
        self.L = None
        c.doc.invalidate()
        c.doc.changed()
        c.update()

    def finish(self, c):
        """leaving the tool applies the transform"""
        if self.L is not None and c.doc is not None and self.L in c.doc.layers:
            self.commit(c)
        else:
            self.L = None

    def double(self, c, p, ev):
        self.commit(c)
        c.update()

    def key(self, c, ev):
        if self.L is None:
            return False
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.commit(c)
            c.state.set(tool="move")
            return True
        if ev.key() == Qt.Key_Escape:
            self.cancel(c)
            c.state.set(tool="move")
            return True
        return False

    # ---- geometry (all in doc coordinates)
    def _rot(self, x, y, ang):
        a = math.radians(ang)
        return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)

    def _pt(self, lx, ly):
        """local box coordinate (-1..1 on each axis) -> doc point"""
        x, y = self._rot(lx * self.w0 * self.sx / 2.0, ly * self.h0 * self.sy / 2.0, self.ang)
        return QPointF(self.cx + x, self.cy + y)

    HANDLES = [(-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)]

    def _hit(self, c, p):
        w = c.to_w(p)
        for hx, hy in self.HANDLES:
            q = c.to_w(self._pt(hx, hy))
            if abs(q.x() - w.x()) <= HANDLE + 3 and abs(q.y() - w.y()) <= HANDLE + 3:
                return (hx, hy)
        return None

    def _inside(self, p):
        lx, ly = self._rot(p.x() - self.cx, p.y() - self.cy, -self.ang)
        return abs(lx) <= self.w0 * self.sx / 2.0 and abs(ly) <= self.h0 * self.sy / 2.0

    # ---- mouse
    def press(self, c, p, ev):
        if self.L is None or self.L not in c.doc.layers:
            self.start(c)
            if self.L is None:
                return
        h = self._hit(c, p)
        self.p0 = QPointF(p)
        self.start_state = (self.cx, self.cy, self.sx, self.sy, self.ang)
        if h is not None:
            self.mode, self.handle = "scale", h
        elif self._inside(p):
            self.mode = "move"
        else:
            self.mode = "rotate"
            self.a0 = math.degrees(math.atan2(p.y() - self.cy, p.x() - self.cx))

    def move(self, c, p, ev):
        if self.L is None or self.mode is None:
            return
        cx, cy, sx, sy, ang = self.start_state
        mods = ev.modifiers()
        if self.mode == "move":
            self.cx, self.cy = cx + p.x() - self.p0.x(), cy + p.y() - self.p0.y()
        elif self.mode == "rotate":
            a = math.degrees(math.atan2(p.y() - cy, p.x() - cx))
            na = ang + a - self.a0
            if mods & Qt.ShiftModifier:
                na = round(na / 15.0) * 15.0
            self.ang = na
        else:
            hx, hy = self.handle
            qx, qy = self._rot(p.x() - cx, p.y() - cy, -ang)         # mouse in the box's own axes, centre = 0
            W, H = self.w0 * sx, self.h0 * sy
            alt = bool(mods & Qt.AltModifier)
            ax = 0.0 if (alt or not hx) else -hx * W / 2.0              # the point that stays where it is
            ay = 0.0 if (alt or not hy) else -hy * H / 2.0
            fx = fy = 1.0
            if hx:
                fx = (abs(qx) * 2.0 / W) if alt else max(0.02, (qx - ax) * hx / W)
            if hy:
                fy = (abs(qy) * 2.0 / H) if alt else max(0.02, (qy - ay) * hy / H)
            if mods & Qt.ShiftModifier:                                # same on all sides: proportions kept
                f = max(fx, fy) if (hx and hy) else (fx if hx else fy)
                fx = fy = f
            fx, fy = max(0.02, fx), max(0.02, fy)
            self.sx, self.sy = sx * fx, sy * fy
            ncx = 0.0 if alt else (ax + hx * W * fx / 2.0 if hx else 0.0)
            ncy = 0.0 if alt else (ay + hy * H * fy / 2.0 if hy else 0.0)
            if mods & Qt.ShiftModifier and not alt:                    # an edge handle with Shift grows the other axis around the middle
                if hx and not hy:
                    ncy = 0.0
                if hy and not hx:
                    ncx = 0.0
            dx, dy = self._rot(ncx, ncy, ang)
            self.cx, self.cy = cx + dx, cy + dy
        self.dirty = True
        c.update()

    def release(self, c, p, ev):
        self.mode = None
        c.update()

    def overlay(self, c, painter):
        if self.L is None:
            return
        painter.save()
        tr = QTransform()
        tr.translate(c.offset.x(), c.offset.y())
        tr.scale(c.zoom, c.zoom)
        tr.translate(self.cx, self.cy)
        tr.rotate(self.ang)
        tr.scale(self.sx, self.sy)
        tr.translate(-self.w0 / 2.0, -self.h0 / 2.0)
        tr.scale(1.0 / self.k, 1.0 / self.k)
        painter.setClipRect(QRectF(c.offset.x(), c.offset.y(), c.doc.w * c.zoom, c.doc.h * c.zoom))
        painter.setTransform(tr)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, self.mode is None)
        painter.setOpacity(self.L.opacity)
        painter.drawImage(0, 0, self.proxy)
        painter.restore()
        painter.setOpacity(1.0)
        pts = [c.to_w(self._pt(*h)) for h in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0), 3))
        painter.drawPolygon(QPolygonF(pts))
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawPolygon(QPolygonF(pts))
        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        for hx, hy in self.HANDLES:
            q = c.to_w(self._pt(hx, hy))
            painter.drawRect(QRectF(q.x() - HANDLE, q.y() - HANDLE, HANDLE * 2, HANDLE * 2))
        m = c.to_w(QPointF(self.cx, self.cy))
        painter.drawLine(QPointF(m.x() - 6, m.y()), QPointF(m.x() + 6, m.y()))
        painter.drawLine(QPointF(m.x(), m.y() - 6), QPointF(m.x(), m.y() + 6))


class QuickSelectTool(Tool):
    """paint over the thing you want: the selection grows over similar colours (Alt = take away)"""
    name = "quickselect"
    cursor = Qt.CrossCursor

    def press(self, c, p, ev):
        d = c.doc
        self.sub = bool(ev.modifiers() & Qt.AltModifier)
        self.base = d.selection.copy() if d.selection is not None else None
        self.acc = np.zeros((d.h, d.w), np.uint8)
        self.src = arr.to_array(d.merged() if not c.state.sample_layer else d.layer().image) if not c.state.sample_layer else None
        self.edit = d.edit("Quick selection", [], pixels=False)
        self.edit.__enter__()
        self.last = p
        self._dab(c, p)

    def _dab(self, c, p):
        d, s = c.doc, c.state
        img = self.src
        if img is None:
            L = d.layer()
            full = np.zeros((d.h, d.w, 4), np.uint8)
            a = arr.to_array(L.image)
            x0, y0 = max(0, L.x), max(0, L.y)
            x1, y1 = min(d.w, L.x + a.shape[1]), min(d.h, L.y + a.shape[0])
            if x1 > x0 and y1 > y0:
                full[y0:y1, x0:x1] = a[y0 - L.y:y1 - L.y, x0 - L.x:x1 - L.x]
            img = self.src = full
        rad = max(3, int(s.size / 2))
        cx, cy = int(p.x()), int(p.y())
        x0, x1 = max(0, cx - rad), min(d.w, cx + rad + 1)
        y0, y1 = max(0, cy - rad), min(d.h, cy + rad + 1)
        if x1 <= x0 or y1 <= y0:
            return
        reg = img[y0:y1, x0:x1].astype(np.float32)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        circ = (xx - cx) ** 2 + (yy - cy) ** 2 <= rad * rad
        core = (xx - cx) ** 2 + (yy - cy) ** 2 <= max(2, rad * 0.35) ** 2
        ref = reg[core][:, :3].mean(0) if core.any() else reg[circ][:, :3].mean(0)
        dist = np.sqrt(((reg[..., :3] - ref) ** 2).sum(-1))
        ok = circ & (dist <= max(8, s.tolerance * 2.2)) & (reg[..., 3] > 0)
        # keep only the part connected to the brush centre so the selection does not leak into similar colours elsewhere
        ok = self._connected(ok, cx - x0, cy - y0)
        self.acc[y0:y1, x0:x1][ok] = 255
        self._show(c)

    @staticmethod
    def _connected(ok, sx, sy):
        h, w = ok.shape
        if not (0 <= sx < w and 0 <= sy < h):
            return ok
        if not ok[sy, sx]:
            ys, xs = np.nonzero(ok)
            if not len(xs):
                return ok
            i = int(np.argmin((xs - sx) ** 2 + (ys - sy) ** 2))
            sx, sy = int(xs[i]), int(ys[i])
        seen = np.zeros_like(ok)
        seen[sy, sx] = True
        for _ in range(max(h, w)):                       # grow from the centre inside the allowed pixels (vectorised flood fill)
            g = seen.copy()
            g[1:] |= seen[:-1]
            g[:-1] |= seen[1:]
            g[:, 1:] |= seen[:, :-1]
            g[:, :-1] |= seen[:, 1:]
            g &= ok
            if (g == seen).all():
                break
            seen = g
        return seen

    def _show(self, c, force=False):
        import time
        now = time.time()
        if not force and now - getattr(self, "_t", 0) < 0.09:         # showing the selection is the slow part: at most ~10 times a second
            return
        self._t = now
        new = Selection(self.acc.copy())
        base = self.base
        if base is not None:
            new = base.combine(new, "sub" if self.sub else "add")
        elif self.sub:
            new = Selection(np.zeros_like(self.acc))
        c.doc.set_selection(new)
        c.doc.changed(None)

    def move(self, c, p, ev):
        a, b = self.last, p
        dist = math.hypot(b.x() - a.x(), b.y() - a.y())
        step = max(2.0, c.state.size * 0.25)
        n = int(dist // step)
        for i in range(1, n + 1):
            t = i * step / dist
            self._dab(c, QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t))
        if n:
            t = n * step / dist
            self.last = QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)

    def release(self, c, p, ev):
        self._show(c, True)
        self.edit.__exit__(None, None, None)
        s = c.state
        if c.doc.selection is not None and s.feather > 0:
            c.doc.set_selection(c.doc.selection.feathered(s.feather))
        c.update()

    def overlay(self, c, painter):
        if c.hover is not None:
            r = c.state.size * c.zoom / 2.0
            w = c.to_w(c.hover)
            painter.setPen(QPen(QColor(0, 0, 0, 200), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(w, r, r)


def colour_range(doc, color, fuzz, mode="new", sample=None):
    """select every pixel of the picture whose colour is close to `color` (fuzz 0..200)"""
    img = sample if sample is not None else doc.merged()
    a = arr.to_array(img).astype(np.float32)
    ref = np.array([color.red(), color.green(), color.blue()], np.float32)
    dist = np.sqrt(((a[..., :3] - ref) ** 2).sum(-1))
    m = np.clip(1.0 - np.maximum(dist - fuzz * 0.4, 0) / max(1.0, fuzz * 0.6 + 1), 0, 1) * (a[..., 3] > 0)
    new = Selection((m * 255).astype(np.uint8))
    if mode != "new" and doc.selection is not None:
        new = doc.selection.combine(new, mode)
    return new
