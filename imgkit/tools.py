"""The tools. Each tool gets mouse events in picture coordinates from the canvas (c)."""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

from . import arr
from .select import Selection, flood

MOD_ADD, MOD_SUB = Qt.ShiftModifier, Qt.AltModifier


def selection_mode(mods):
    if mods & MOD_ADD and mods & MOD_SUB:
        return "and"
    if mods & MOD_ADD:
        return "add"
    if mods & MOD_SUB:
        return "sub"
    return "new"


def render_text(spec):
    """text layer picture from a spec dict: text, font, size, bold, italic, color, align"""
    f = QFont(spec.get("font", "Sans Serif"))
    f.setPixelSize(max(4, int(spec.get("size", 48))))
    f.setBold(bool(spec.get("bold")))
    f.setItalic(bool(spec.get("italic")))
    txt = spec.get("text", "") or " "
    al = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}.get(spec.get("align", "left"), Qt.AlignLeft)
    flags = int(al | Qt.TextDontClip)
    r = QFontMetricsF(f).boundingRect(QRectF(0, 0, 20000, 20000), flags, txt)
    pad = 6
    w, h = max(8, int(math.ceil(r.width())) + pad * 2), max(8, int(math.ceil(r.height())) + pad * 2)
    img = arr.new_image(w, h)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setFont(f)
    p.setPen(QColor(spec.get("color", "#000000")))
    p.drawText(QRectF(pad, pad, w - pad * 2, h - pad * 2), flags, txt)
    p.end()
    return img


def ink_rect(img):
    """the part of a layer picture that is not transparent (QRect) or None"""
    import numpy as np
    from PySide6.QtCore import QRect
    a = arr.to_array(img)
    if a.size == 0:
        return None
    al = a[..., 3] > 8
    ys, xs = np.nonzero(al.any(axis=1))[0], np.nonzero(al.any(axis=0))[0]
    if not len(ys) or not len(xs):
        return None
    return QRect(int(xs[0]), int(ys[0]), int(xs[-1] - xs[0] + 1), int(ys[-1] - ys[0] + 1))


def place_like(layer, old_img, new_img, align="left"):
    """after a text is drawn again: keep it where it was (left, centre or right edge, and the top) instead of jumping"""
    o, n = ink_rect(old_img), ink_rect(new_img)
    if o is None or n is None:
        return
    if align == "center":
        dx = (o.x() + o.width() / 2) - (n.x() + n.width() / 2)
    elif align == "right":
        dx = (o.x() + o.width()) - (n.x() + n.width())
    else:
        dx = o.x() - n.x()
    layer.x = int(round(layer.x + dx))
    layer.y = int(round(layer.y + o.y() - n.y()))


def _clip(p, c, layer):
    """paint only inside the selection (soft edges of a selection are not used by brush strokes)"""
    sel = c.doc.selection
    if sel is not None:
        path = sel.outline()
        p.setClipPath(path.translated(-layer.x, -layer.y))


def paint_layer(c, label, fn):
    """fn(painter, layer) paints into the active layer; one history step"""
    d = c.doc
    L = d.layer()
    if L is None or not c.layer_ok():
        return
    with d.edit(label, [L]):
        p = QPainter(L.image)
        p.setRenderHint(QPainter.Antialiasing)
        _clip(p, c, L)
        fn(p, L)
        p.end()


class Tool:
    name = "tool"
    cursor = Qt.CrossCursor

    def press(self, c, p, ev): pass
    def move(self, c, p, ev): pass
    def release(self, c, p, ev): pass
    def key(self, c, ev): return False
    def overlay(self, c, painter): pass
    def finish(self, c): pass


class HandTool(Tool):
    name, cursor = "hand", Qt.OpenHandCursor

    def press(self, c, p, ev):
        self.start = (ev.position(), QPointF(c.offset))

    def move(self, c, p, ev):
        s, o = self.start
        c.offset = o + (ev.position() - s)
        c.view_changed()


class ZoomTool(Tool):
    name, cursor = "zoom", Qt.PointingHandCursor

    def press(self, c, p, ev):
        c.zoom_at(ev.position(), 0.5 if ev.modifiers() & Qt.AltModifier else 2.0)


class MoveTool(Tool):
    """drag the active layer. While you drag it is only drawn on top (fast); the picture is recomputed once when you let go."""
    name, cursor = "move", Qt.SizeAllCursor

    def press(self, c, p, ev):
        L = c.doc.layer()
        self.edit = None
        if L is None or L.locked or not L.visible:
            return
        self.layer, self.p0, self.pos0 = L, p, (L.x, L.y)
        self.dx = self.dy = 0
        self.moved = False
        self.edit = c.doc.edit("Move layer", [])
        self.edit.__enter__()

    def move(self, c, p, ev):
        if self.edit is None:
            return
        d = p - self.p0
        dx, dy = int(round(d.x())), int(round(d.y()))
        if (dx, dy) == (self.dx, self.dy) and self.moved:
            return
        if not self.moved:
            self.moved = True
            self.layer._hide = True                       # the rest of the picture is composed once without this layer
            c.doc.invalidate(self.layer.rect())
        self.dx, self.dy = dx, dy
        c.update()

    def release(self, c, p, ev):
        if self.edit is None:
            return
        L = self.layer
        L._hide = False
        L.x, L.y = self.pos0[0] + self.dx, self.pos0[1] + self.dy
        self.edit.__exit__(None, None, None)
        self.edit = None
        c.update()

    def overlay(self, c, painter):
        if getattr(self, "edit", None) is None or not self.moved:
            return
        L = self.layer
        painter.save()
        painter.setClipRect(QRectF(c.offset.x(), c.offset.y(), c.doc.w * c.zoom, c.doc.h * c.zoom))
        painter.translate(c.offset)
        painter.scale(c.zoom, c.zoom)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.setOpacity(L.opacity)
        painter.drawImage(self.pos0[0] + self.dx, self.pos0[1] + self.dy, L._image)
        painter.restore()
        painter.setOpacity(1.0)


class _Dabs:
    cache = {}

    @classmethod
    def get(cls, size, hardness, color, tip=None):
        key = (int(size), int(hardness), color.rgba(), id(tip["alpha"]) if tip else 0)
        im = cls.cache.get(key)
        if im is None:
            if len(cls.cache) > 60:
                cls.cache.clear()
            im = cls._tip_dab(size, color, tip) if tip else cls._round_dab(size, hardness, color)
            cls.cache[key] = im
        return im

    @staticmethod
    def _tip_dab(size, color, tip):
        a = tip["alpha"]
        h, w = a.shape
        k = max(1, int(size)) / float(max(h, w))
        nw, nh = max(1, int(round(w * k))), max(1, int(round(h * k)))
        m = arr.to_mask(arr.from_mask(a).scaled(nw, nh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        rgba = np.zeros((nh, nw, 4), np.uint8)
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = color.red(), color.green(), color.blue()
        rgba[..., 3] = m
        return arr.from_array(rgba)

    @staticmethod
    def _round_dab(size, hardness, color):
        d = max(1, int(size))
        im = QImage(d + 2, d + 2, QImage.Format_ARGB32_Premultiplied)
        im.fill(Qt.transparent)
        p = QPainter(im)
        p.setRenderHint(QPainter.Antialiasing)
        r = d / 2.0
        g = QRadialGradient(QPointF(r + 1, r + 1), r)
        h = max(0.0, min(0.99, hardness / 100.0))
        c0, c1 = QColor(color), QColor(color)
        c1.setAlpha(0)
        g.setColorAt(0, c0)
        g.setColorAt(h, c0)
        g.setColorAt(1, c1)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(r + 1, r + 1), r, r)
        p.end()
        return im


class BrushTool(Tool):
    name = "brush"
    erase = False
    cursor = Qt.CrossCursor

    def press(self, c, p, ev):
        d = c.doc
        L = d.layer()
        if L is None or not c.layer_ok():
            self.edit = None
            return
        self.layer, self.last = L, p
        self.edit = d.edit("Eraser" if self.erase else "Brush", [L])
        self.edit.__enter__()
        self.painter = QPainter(L.image)
        self.painter.setRenderHint(QPainter.SmoothPixmapTransform)
        _clip(self.painter, c, L)
        self.painter.setCompositionMode(QPainter.CompositionMode_DestinationOut if self.erase else QPainter.CompositionMode_SourceOver)
        self.painter.setOpacity(c.state.opacity / 100.0)
        self.dab(c, p)
        self.dirty = self._r(p, p, c)

    def _r(self, a, b, c):
        s = c.state.size + 4
        return QRectF(a, b).normalized().adjusted(-s, -s, s, s).toAlignedRect()

    def dab(self, c, p):
        s = c.state
        col = QColor(0, 0, 0) if self.erase else QColor(s.fg)
        im = _Dabs.get(s.size, s.hardness, col, None if self.erase and False else getattr(s, "tip", None))
        self.painter.drawImage(QPointF(p.x() - self.layer.x - im.width() / 2.0, p.y() - self.layer.y - im.height() / 2.0), im)

    def move(self, c, p, ev):
        if getattr(self, "edit", None) is None:
            return
        tip = getattr(c.state, "tip", None)
        step = max(1.0, c.state.size * (tip["spacing"] / 100.0 if tip else 0.12))
        a, b = self.last, p
        dist = math.hypot(b.x() - a.x(), b.y() - a.y())
        n = int(dist // step)
        for i in range(1, n + 1):
            t = i * step / dist
            self.dab(c, QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t))
        if n:
            t = n * step / dist
            self.last = QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)
        r = self._r(a, b, c)
        c.doc.invalidate(r)
        c.update_rect(r)

    def release(self, c, p, ev):
        if getattr(self, "edit", None) is None:
            return
        self.painter.end()
        self.edit.__exit__(None, None, None)
        self.edit = None

    def overlay(self, c, painter):
        if c.hover is not None and c.state.tool in ("brush", "eraser"):
            r = c.state.size * c.zoom / 2.0
            w = c.to_w(c.hover)
            painter.setPen(QPen(QColor(0, 0, 0, 200), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(w, r, r)
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1, Qt.DotLine))
            painter.drawEllipse(w, r, r)


class EraserTool(BrushTool):
    name = "eraser"
    erase = True


class FillTool(Tool):
    name = "fill"

    def press(self, c, p, ev):
        d = c.doc
        L = d.layer()
        if L is None or not c.layer_ok():
            return
        s = c.state
        x, y = int(p.x()), int(p.y())
        if not (0 <= x < d.w and 0 <= y < d.h):
            return
        if s.sample_layer:
            m = flood(L.image, x - L.x, y - L.y, s.tolerance, s.contiguous)
            full = np.zeros((d.h, d.w), np.uint8)
            self._place(full, m, L)
            mask = full
        else:
            mask = flood(d.merged(), x, y, s.tolerance, s.contiguous)
        if d.selection is not None:
            mask = (mask.astype(np.uint16) * d.selection.mask // 255).astype(np.uint8)
        fill_mask(c, "Fill", mask, QColor(s.fg), s.opacity / 100.0)

    @staticmethod
    def _place(full, m, L):
        h, w = m.shape
        x0, y0 = max(0, L.x), max(0, L.y)
        x1, y1 = min(full.shape[1], L.x + w), min(full.shape[0], L.y + h)
        if x1 > x0 and y1 > y0:
            full[y0:y1, x0:x1] = m[y0 - L.y:y1 - L.y, x0 - L.x:x1 - L.x]


def fill_mask(c, label, mask, color, opacity=1.0):
    """paint color through a picture-sized mask (0-255) into the active layer"""
    d = c.doc
    L = d.layer()
    if L is None or not c.layer_ok():
        return
    h, w = L.image.height(), L.image.width()
    sub = np.zeros((h, w), np.uint8)
    x0, y0 = max(0, L.x), max(0, L.y)
    x1, y1 = min(d.w, L.x + w), min(d.h, L.y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sub[y0 - L.y:y1 - L.y, x0 - L.x:x1 - L.x] = mask[y0:y1, x0:x1]
    ov = np.zeros((h, w, 4), np.uint8)
    ov[..., 0], ov[..., 1], ov[..., 2] = color.red(), color.green(), color.blue()
    ov[..., 3] = (sub.astype(np.float32) * opacity * color.alphaF()).astype(np.uint8)
    img = arr.from_array(ov)
    with d.edit(label, [L]):
        p = QPainter(L.image)
        p.drawImage(0, 0, img)
        p.end()


class GradientTool(Tool):
    name = "gradient"

    def press(self, c, p, ev):
        self.a, self.b = p, p

    def move(self, c, p, ev):
        self.b = p
        c.update()

    def release(self, c, p, ev):
        self.b = p
        if math.hypot(self.b.x() - self.a.x(), self.b.y() - self.a.y()) < 2:
            self.a = None
            return
        s = c.state
        c0 = QColor(s.fg)
        c1 = QColor(s.bg) if s.grad_mode == "fg-bg" else QColor(s.fg.red(), s.fg.green(), s.fg.blue(), 0)
        preset = getattr(s, "gradient", None)

        def paint(pt, L):
            a = QPointF(self.a.x() - L.x, self.a.y() - L.y)
            b = QPointF(self.b.x() - L.x, self.b.y() - L.y)
            if s.grad == "radial":
                g = QRadialGradient(a, math.hypot(b.x() - a.x(), b.y() - a.y()))
            else:
                g = QLinearGradient(a, b)
            if preset:
                from .presets import gradient_stops
                for pos, col in gradient_stops(preset, s.fg, s.bg):
                    g.setColorAt(max(0.0, min(1.0, pos)), col)
            else:
                g.setColorAt(0, c0)
                g.setColorAt(1, c1)
            pt.setOpacity(s.opacity / 100.0)
            pt.fillRect(QRectF(0, 0, L.image.width(), L.image.height()), QBrush(g))
        paint_layer(c, "Gradient", paint)
        self.a = None
        c.update()

    def overlay(self, c, painter):
        if getattr(self, "a", None) is not None:
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawLine(c.to_w(self.a), c.to_w(self.b))
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            painter.drawLine(c.to_w(self.a), c.to_w(self.b))


class EyedropperTool(Tool):
    name = "eyedropper"

    def _pick(self, c, p, ev):
        d = c.doc
        col = d.sample(p.x(), p.y(), not c.state.sample_layer)
        if col.alpha() == 0:
            return
        col.setAlpha(255)
        if ev.modifiers() & Qt.AltModifier or ev.buttons() & Qt.RightButton:
            c.state.set(bg=col)
        else:
            c.state.set(fg=col)

    press = move = _pick


class SelectTool(Tool):
    """rectangle / ellipse / rounded rectangle / freehand lasso / polygon lasso"""
    name = "select"

    def __init__(self):
        self.poly = []
        self.active = False

    def finish(self, c):
        self.poly = []
        self.active = False

    def press(self, c, p, ev):
        self.mods = ev.modifiers()
        if c.state.sel_kind == "poly":
            first = self.poly[0] if self.poly else None
            if first is not None and len(self.poly) > 2 and math.hypot(*(c.to_w(first) - c.to_w(p)).toTuple()) < 9:
                self._close_poly(c)
            else:
                self.poly.append(p)
            self.b = p
            c.update()
            return
        self.poly = []
        self.a, self.b = p, p
        self.pts = [p]
        self.active = True

    def move(self, c, p, ev):
        if c.state.sel_kind == "poly":
            self.b = p
            c.update()
            return
        if not self.active:
            return
        self.b = p
        if c.state.sel_kind == "lasso":
            self.pts.append(p)
        if ev.modifiers() & Qt.ShiftModifier and c.state.sel_kind in ("rect", "ellipse", "rounded"):
            ax, ay = self.a.x(), self.a.y()
            dx, dy = p.x() - ax, p.y() - ay
            m = max(abs(dx), abs(dy))
            self.b = QPointF(ax + math.copysign(m, dx), ay + math.copysign(m, dy))
        c.update()

    def hover(self, c, p):
        if c.state.sel_kind == "poly" and self.poly:
            self.b = p
            c.update()

    def path(self, c):
        from PySide6.QtGui import QPolygonF
        k = c.state.sel_kind
        pa = QPainterPath()
        if k == "lasso":
            pa.addPolygon(QPolygonF(self.pts))
            pa.closeSubpath()
            return pa
        r = QRectF(self.a, self.b).normalized()
        if k == "ellipse":
            pa.addEllipse(r)
        elif k == "rounded":
            rad = min(c.state.radius, r.width() / 2, r.height() / 2)
            pa.addRoundedRect(r, rad, rad)
        else:
            pa.addRect(r)
        return pa

    def _close_poly(self, c):
        from PySide6.QtGui import QPolygonF
        if len(self.poly) < 3:
            self.poly = []
            return
        pa = QPainterPath()
        pa.addPolygon(QPolygonF(self.poly))
        pa.closeSubpath()
        d = c.doc
        new = Selection.from_path(pa, d.w, d.h)
        if c.state.feather > 0:
            new = new.feathered(c.state.feather)
        self.poly = []
        c.combine_selection(new, selection_mode(self.mods))

    def double(self, c, p, ev):
        if c.state.sel_kind == "poly":
            if self.poly:
                self.poly.pop() if len(self.poly) > 3 else None       # the double click added the last point twice
            self._close_poly(c)
            c.update()

    def key(self, c, ev):
        if c.state.sel_kind == "poly" and self.poly:
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._close_poly(c)
                c.update()
                return True
            if ev.key() == Qt.Key_Escape:
                self.poly = []
                c.update()
                return True
        return False

    def release(self, c, p, ev):
        if c.state.sel_kind == "poly" or not self.active:
            return
        self.active = False
        d = c.doc
        small = abs(self.b.x() - self.a.x()) < 2 and abs(self.b.y() - self.a.y()) < 2 and c.state.sel_kind != "lasso"
        if small:
            if not (self.mods & (MOD_ADD | MOD_SUB)):
                c.set_selection(None, "Deselect")
            c.update()
            return
        new = Selection.from_path(self.path(c), d.w, d.h, antialias=c.state.sel_kind != "rect")
        if c.state.feather > 0:
            new = new.feathered(c.state.feather)
        c.combine_selection(new, selection_mode(self.mods))
        c.update()

    def overlay(self, c, painter):
        from PySide6.QtGui import QPolygonF
        if c.state.sel_kind == "poly":
            if not self.poly:
                return
            pts = [c.to_w(q) for q in self.poly] + [c.to_w(self.b)]
            for col, st in ((QColor(255, 255, 255), Qt.SolidLine), (QColor(0, 0, 0), Qt.DashLine)):
                painter.setPen(QPen(col, 1, st))
                painter.drawPolyline(QPolygonF(pts))
            painter.setBrush(QColor(255, 255, 255))
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            for i, q in enumerate(pts[:-1]):
                painter.drawRect(QRectF(q.x() - 3, q.y() - 3, 6, 6) if i else QRectF(q.x() - 5, q.y() - 5, 10, 10))
            return
        if self.active:
            pa = self.path(c)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawPath(c.path_to_w(pa))
            painter.setPen(QPen(QColor(0, 0, 0), 1, Qt.DashLine))
            painter.drawPath(c.path_to_w(pa))


class WandTool(Tool):
    name = "wand"

    def press(self, c, p, ev):
        d, s = c.doc, c.state
        x, y = int(p.x()), int(p.y())
        if not (0 <= x < d.w and 0 <= y < d.h):
            return
        if s.sample_layer and d.layer() is not None:
            L = d.layer()
            m = flood(L.image, x - L.x, y - L.y, s.tolerance, s.contiguous)
            full = np.zeros((d.h, d.w), np.uint8)
            FillTool._place(full, m, L)
        else:
            full = flood(d.merged(), x, y, s.tolerance, s.contiguous)
        new = Selection(full)
        if s.feather > 0:
            new = new.feathered(s.feather)
        c.combine_selection(new, selection_mode(ev.modifiers()))


class ShapeTool(Tool):
    name = "shape"

    def press(self, c, p, ev):
        self.a, self.b, self.active = p, p, True

    def move(self, c, p, ev):
        if not getattr(self, "active", False):
            return
        self.b = p
        if ev.modifiers() & Qt.ShiftModifier and c.state.shape != "line":
            dx, dy = p.x() - self.a.x(), p.y() - self.a.y()
            m = max(abs(dx), abs(dy))
            self.b = QPointF(self.a.x() + math.copysign(m, dx), self.a.y() + math.copysign(m, dy))
        c.update()

    def draw(self, p, c, off=(0, 0)):
        s = c.state
        a = QPointF(self.a.x() - off[0], self.a.y() - off[1])
        b = QPointF(self.b.x() - off[0], self.b.y() - off[1])
        r = QRectF(a, b).normalized()
        p.setRenderHint(QPainter.Antialiasing)
        if s.shape == "line":
            p.setPen(QPen(QColor(s.fg), max(1, s.stroke_w), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(a, b)
            return
        p.setBrush(QBrush(QColor(s.fg)) if s.fill else Qt.NoBrush)
        p.setPen(QPen(QColor(s.bg), s.stroke_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin) if s.stroke else Qt.NoPen)
        if s.shape == "ellipse":
            p.drawEllipse(r)
        elif s.shape == "rounded":
            p.drawRoundedRect(r, s.radius, s.radius)
        else:
            p.drawRect(r)

    def release(self, c, p, ev):
        if not getattr(self, "active", False):
            return
        self.active = False
        if abs(self.b.x() - self.a.x()) < 2 and abs(self.b.y() - self.a.y()) < 2:
            c.update()
            return
        s = c.state
        paint_layer(c, "Shape", lambda pt, L: (pt.setOpacity(s.opacity / 100.0), self.draw(pt, c, (L.x, L.y))))
        c.update()

    def overlay(self, c, painter):
        if getattr(self, "active", False):
            painter.save()
            painter.translate(c.offset)
            painter.scale(c.zoom, c.zoom)
            painter.setOpacity(c.state.opacity / 100.0)
            self.draw(painter, c)
            painter.restore()


class CropTool(Tool):
    name = "crop"

    def press(self, c, p, ev):
        self.a = QPointF(max(0, min(c.doc.w, p.x())), max(0, min(c.doc.h, p.y())))
        self.b = self.a
        self.active = True

    def move(self, c, p, ev):
        if getattr(self, "active", False):
            self.b = QPointF(max(0, min(c.doc.w, p.x())), max(0, min(c.doc.h, p.y())))
            c.update()

    def release(self, c, p, ev):
        self.active = False
        if abs(self.b.x() - self.a.x()) < 4 or abs(self.b.y() - self.a.y()) < 4:
            self.a = None

    def rect(self):
        if getattr(self, "a", None) is None:
            return None
        return QRectF(self.a, self.b).normalized().toRect()

    def key(self, c, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and self.rect():
            c.crop_to(self.rect())
            self.a = None
            return True
        if ev.key() == Qt.Key_Escape:
            self.a = None
            c.update()
            return True
        return False

    def finish(self, c):
        self.a = None

    def overlay(self, c, painter):
        r = self.rect()
        if r is None:
            return
        wr = c.rect_to_w(QRectF(r))
        full = c.rect_to_w(QRectF(0, 0, c.doc.w, c.doc.h))
        path = QPainterPath()
        path.addRect(full)
        inner = QPainterPath()
        inner.addRect(wr)
        painter.fillPath(path.subtracted(inner), QColor(0, 0, 0, 130))
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(wr)
        painter.setPen(QPen(QColor(255, 255, 255, 120), 1, Qt.DotLine))
        for i in (1, 2):
            painter.drawLine(QPointF(wr.left() + wr.width() * i / 3, wr.top()), QPointF(wr.left() + wr.width() * i / 3, wr.bottom()))
            painter.drawLine(QPointF(wr.left(), wr.top() + wr.height() * i / 3), QPointF(wr.right(), wr.top() + wr.height() * i / 3))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(wr.topLeft() + QPointF(4, -6), f"{r.width()} x {r.height()}   Enter = crop, Esc = cancel")


class TextTool(Tool):
    name = "text"
    cursor = Qt.IBeamCursor

    def press(self, c, p, ev):
        c.new_text_at(p)


class PenTool(Tool):
    """Pen (as in Photoshop): click = corner point, click and drag = smooth point, click the first point to close.
    Enter = make a selection from the path, Backspace = remove the last point, Esc = clear the path.
    The options bar has Selection, Fill, Stroke (with the brush size and front colour)."""
    name = "pen"
    cursor = Qt.CrossCursor

    def __init__(self):
        self.nodes = []          # [anchor, handle_in, handle_out] in picture coordinates
        self.closed = False
        self.drag = None
        self.hov = None

    def finish(self, c):
        self.drag = None

    def press(self, c, p, ev):
        if self.closed:
            self.nodes, self.closed = [], False
        if len(self.nodes) > 1 and math.hypot(*(c.to_w(self.nodes[0][0]) - c.to_w(p)).toTuple()) < 9:
            self.closed = True
            self.drag = self.nodes[0]
            c.update()
            return
        n = [QPointF(p), QPointF(p), QPointF(p)]
        self.nodes.append(n)
        self.drag = n
        c.update()

    def move(self, c, p, ev):
        self.hov = QPointF(p)
        if self.drag is not None and ev.buttons() & Qt.LeftButton:
            a = self.drag[0]
            self.drag[2] = QPointF(p)                                  # out handle follows the mouse
            self.drag[1] = QPointF(2 * a.x() - p.x(), 2 * a.y() - p.y())   # in handle mirrored: a smooth curve
        c.update()

    def release(self, c, p, ev):
        self.drag = None
        c.update()

    def path(self):
        pa = QPainterPath()
        if not self.nodes:
            return pa
        pa.moveTo(self.nodes[0][0])
        segs = list(zip(self.nodes, self.nodes[1:]))
        if self.closed:
            segs.append((self.nodes[-1], self.nodes[0]))
        for a, b in segs:
            pa.cubicTo(a[2], b[1], b[0])
        if self.closed:
            pa.closeSubpath()
        return pa

    def key(self, c, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.to_selection(c)
            return True
        if ev.key() == Qt.Key_Escape:
            self.nodes, self.closed = [], False
            c.update()
            return True
        if ev.key() == Qt.Key_Backspace and self.nodes:
            self.nodes.pop()
            self.closed = False
            c.update()
            return True
        return False

    def _ready(self, c):
        if len(self.nodes) < 2:
            c.message.emit("Draw a path first: click points (drag for curves).")
            return False
        return True

    def to_selection(self, c):
        if not self._ready(c):
            return
        new = Selection.from_path(self.path(), c.doc.w, c.doc.h, antialias=True)
        if c.state.feather > 0:
            new = new.feathered(c.state.feather)
        c.combine_selection(new, "new")
        c.update()

    def fill(self, c):
        if not self._ready(c):
            return
        sel = Selection.from_path(self.path(), c.doc.w, c.doc.h, antialias=True)
        fill_mask(c, "Fill path", sel.mask, QColor(c.state.fg), c.state.opacity / 100.0)

    def stroke(self, c):
        if not self._ready(c) or not c.layer_ok():
            return
        L = c.doc.layer()
        with c.doc.edit("Stroke path", [L]):
            q = QPainter(L.image)
            q.setRenderHint(QPainter.Antialiasing)
            q.translate(-L.x, -L.y)
            col = QColor(c.state.fg)
            col.setAlphaF(c.state.opacity / 100.0)
            q.setPen(QPen(col, max(1, c.state.size), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            q.setBrush(Qt.NoBrush)
            q.drawPath(self.path())
            q.end()

    def overlay(self, c, painter):
        if not self.nodes:
            return
        pa = self.path()
        if not self.closed and self.hov is not None and self.drag is None:
            last = self.nodes[-1]
            pa.cubicTo(last[2], self.hov, self.hov)                    # where the next point would go
        w = c.path_to_w(pa)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255), 3))
        painter.drawPath(w)
        painter.setPen(QPen(QColor("#2D6CDF"), 1.4))
        painter.drawPath(w)
        for k, (a, hi, ho) in enumerate(self.nodes):
            aw, iw, ow = c.to_w(a), c.to_w(hi), c.to_w(ho)
            if (ho - a).manhattanLength() > 0.5:
                painter.setPen(QPen(QColor("#2D6CDF"), 1))
                painter.drawLine(iw, ow)
                painter.setBrush(QColor("#2D6CDF"))
                painter.drawEllipse(iw, 2.5, 2.5)
                painter.drawEllipse(ow, 2.5, 2.5)
            painter.setPen(QPen(QColor("#2D6CDF"), 1))
            painter.setBrush(QColor(255, 255, 255) if k else QColor("#2D6CDF"))
            painter.drawRect(QRectF(aw.x() - 3.5, aw.y() - 3.5, 7, 7))


TOOLS = {t.name: t for t in (MoveTool(), SelectTool(), WandTool(), BrushTool(), EraserTool(), FillTool(), GradientTool(), EyedropperTool(),
                              TextTool(), ShapeTool(), CropTool(), HandTool(), ZoomTool(), PenTool())}
from . import retouch as _rt          # noqa: E402  (clone, heal, smudge, ...)
from . import transform as _tf         # noqa: E402
for _t in (_tf.TransformTool(), _tf.QuickSelectTool(), _rt.CloneTool(), _rt.HealTool(), _rt.SpotHealTool(), _rt.SmudgeTool(), _rt.BlurBrush(), _rt.SharpenBrush(), _rt.DodgeTool(), _rt.BurnTool()):
    TOOLS[_t.name] = _t
