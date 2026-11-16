"""The picture view: zoom, pan, checkerboard, selection outline, and the active tool."""
import math

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QWidget

from . import ops
from .tools import TOOLS


def _checker():
    pm = QPixmap(16, 16)
    pm.fill(QColor("#FFFFFF"))
    p = QPainter(pm)
    p.fillRect(0, 0, 8, 8, QColor("#D9D9D9"))
    p.fillRect(8, 8, 8, 8, QColor("#D9D9D9"))
    p.end()
    return pm


class Canvas(QWidget):
    viewChanged = Signal()
    info = Signal(str)
    textRequested = Signal(QPointF)
    textEditRequested = Signal()
    message = Signal(str)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.doc = None
        self.zoom, self.offset = 1.0, QPointF(40, 40)
        self.hover = None
        self._space = False
        self._pan = None
        self._tool = None
        self._checker = _checker()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(200, 150)
        self.setAutoFillBackground(False)
        self._ants = 0
        self._moving = False
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(self._settled)
        self._last_cursor = None
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(300)
        state.changed.connect(self._state_changed)
        self.set_tool(state.tool)

    # ---- document
    def set_doc(self, doc):
        if self.doc is not None and self._tool is not None:
            self._tool.finish(self)
        if self.doc is not None:
            try:
                self.doc.listeners.remove(self._doc_changed)
            except ValueError:
                pass
            self.doc.view = (self.zoom, QPointF(self.offset))
        self.doc = doc
        if doc is not None:
            doc.on_change(self._doc_changed)
            v = getattr(doc, "view", None)
            if v:
                self.zoom, self.offset = v[0], QPointF(v[1])
            else:
                self.fit()
        self.update()
        self.viewChanged.emit()

    def _doc_changed(self):
        r = getattr(self.doc, "last_rect", None)
        if r is not None and not r.isEmpty():
            self.update(self.rect_to_w(QRectF(r)).toAlignedRect().adjusted(-3, -3, 3, 3))      # only the changed part
        else:
            self.update()
        self.viewChanged.emit()

    def _tick(self):
        if self.doc is not None and self.doc.selection is not None and not getattr(self, "_down", False) and self.isVisible():
            self._ants = (self._ants + 1) % 16
            b = self.doc.selection.bbox()             # only the part of the picture that has the dashed line is redrawn
            self.update(self.rect_to_w(QRectF(b)).toAlignedRect().adjusted(-4, -4, 4, 4) if not b.isEmpty() else self.rect())

    def _state_changed(self, name):
        if name == "tool":
            self.set_tool(self.state.tool)

    # ---- tools
    def set_tool(self, name):
        if self._tool is not None:
            self._tool.finish(self)
        self._tool = TOOLS.get(name, TOOLS["brush"])
        self.setCursor(self._tool.cursor)
        if hasattr(self._tool, "start") and self.doc is not None:
            self._tool.start(self)
        self.update()

    def layer_ok(self):
        L = self.doc.layer() if self.doc else None
        if L is None:
            return False
        if L.locked:
            self.message.emit("This layer is locked.")
            return False
        if not L.visible:
            self.message.emit("This layer is hidden. Show it first.")
            return False
        if L.adj and not (L.edit_mask and L._mask is not None):
            self.message.emit("An adjustment layer has no pixels. Add a mask and paint on it, or edit it with a double-click.")
            return False
        return True

    def set_selection(self, sel, label="Select"):
        with self.doc.edit(label, pixels=False):
            self.doc.set_selection(sel)

    def combine_selection(self, new, mode):
        old = self.doc.selection
        if mode != "new" and old is not None:
            new = old.combine(new, mode)
        self.set_selection(new, "Select")

    def crop_to(self, rect):
        ops.crop(self.doc, rect)
        self.fit()

    def text_layer_at(self, p):
        """the top-most visible text layer under the point (index) or -1"""
        d = self.doc
        if d is None:
            return -1
        for i in range(len(d.layers) - 1, -1, -1):
            L = d.layers[i]
            if L.text and L.visible and L.x <= p.x() < L.x + L.image.width() and L.y <= p.y() < L.y + L.image.height():
                return i
        return -1

    def edit_text_at(self, p):
        i = self.text_layer_at(p)
        if i < 0:
            return False
        self.doc.set_active(i)
        self.doc.changed(QRect())
        self.textEditRequested.emit()
        return True

    def new_text_at(self, p):
        if self.edit_text_at(p):          # clicking a text again edits it
            return
        self.textRequested.emit(p)

    # ---- coordinates
    def to_w(self, p):
        return QPointF(self.offset.x() + p.x() * self.zoom, self.offset.y() + p.y() * self.zoom)

    def to_doc(self, w):
        return QPointF((w.x() - self.offset.x()) / self.zoom, (w.y() - self.offset.y()) / self.zoom)

    def rect_to_w(self, r):
        return QRectF(self.to_w(r.topLeft()), self.to_w(r.bottomRight()))

    def path_to_w(self, path):
        return QTransform().translate(self.offset.x(), self.offset.y()).scale(self.zoom, self.zoom).map(path)

    def update_rect(self, r):
        w = self.rect_to_w(QRectF(r)).toAlignedRect().adjusted(-2, -2, 2, 2)
        self.update(w)

    def view_rect_doc(self):
        return QRectF(self.to_doc(QPointF(0, 0)), self.to_doc(QPointF(self.width(), self.height())))

    # ---- view
    def view_changed(self):
        self._moving = True                 # pan / zoom: draw quickly now, smooth when the view stops
        self._settle.start(140)
        self.update()
        self.viewChanged.emit()

    def _settled(self):
        self._moving = False
        self.update()

    def fit(self, margin=24):
        if self.doc is None:
            return
        self.zoom = max(0.02, min(16.0, min((self.width() - margin * 2) / self.doc.w, (self.height() - margin * 2) / self.doc.h, 8.0)))
        self.offset = QPointF((self.width() - self.doc.w * self.zoom) / 2, (self.height() - self.doc.h * self.zoom) / 2)
        self.view_changed()

    def actual(self):
        self.zoom_to(1.0)

    def zoom_to(self, z, anchor=None):
        if self.doc is None:
            return
        z = max(0.02, min(64.0, z))
        a = anchor if anchor is not None else QPointF(self.width() / 2, self.height() / 2)
        d = self.to_doc(a)
        self.zoom = z
        self.offset = QPointF(a.x() - d.x() * z, a.y() - d.y() * z)
        self.view_changed()

    def zoom_at(self, wpos, factor):
        self.zoom_to(self.zoom * factor, wpos)

    def center_on(self, p):
        self.offset = QPointF(self.width() / 2 - p.x() * self.zoom, self.height() / 2 - p.y() * self.zoom)
        self.view_changed()

    def resizeEvent(self, e):
        old = e.oldSize()
        if old.isValid() and self.doc is not None:          # keep the picture where it is relative to the middle
            self.offset = self.offset + QPointF((self.width() - old.width()) / 2, (self.height() - old.height()) / 2)
        self.viewChanged.emit()

    # ---- painting
    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#3D3A3F"))
        d = self.doc
        if d is None:
            p.setPen(QColor("#A099A5"))
            p.drawText(self.rect(), Qt.AlignCenter, "Open a picture or make a new one\nFile > New (Ctrl+N)   File > Open (Ctrl+O)")
            return
        target = QRectF(self.offset.x(), self.offset.y(), d.w * self.zoom, d.h * self.zoom)
        p.fillRect(QRectF(target.left() + 4, target.top() + 4, target.width(), target.height()), QColor(0, 0, 0, 70))
        p.save()
        p.setClipRect(target.intersected(QRectF(self.rect())))
        p.setBrushOrigin(target.topLeft())
        p.fillRect(target, QBrush(self._checker))
        big = d.w * d.h > 6_000_000
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.zoom < 2.5 and not (self._moving and big) and not (getattr(self, "_down", False) and big and self.zoom < 1))
        src = target.intersected(QRectF(self.rect()))
        sx0, sy0 = (src.left() - target.left()) / self.zoom, (src.top() - target.top()) / self.zoom
        sw, sh = src.width() / self.zoom, src.height() / self.zoom
        p.drawImage(src, d.merged(), QRectF(sx0, sy0, sw, sh))
        p.restore()
        p.setRenderHint(QPainter.Antialiasing)
        if self.zoom >= 8:
            self._pixel_grid(p, target)
        if d.selection is not None:
            path = self.path_to_w(d.selection.outline())
            pen = QPen(QColor(255, 255, 255), 1)
            p.setPen(pen)
            p.drawPath(path)
            pen = QPen(QColor(0, 0, 0), 1, Qt.CustomDashLine)
            pen.setDashPattern([4, 4])
            pen.setDashOffset(self._ants / 2.0)
            p.setPen(pen)
            p.drawPath(path)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(target)
        self._tool.overlay(self, p)

    def _pixel_grid(self, p, target):
        p.setPen(QPen(QColor(0, 0, 0, 50), 1))
        view = self.rect()
        x0 = max(0, int((view.left() - target.left()) / self.zoom))
        x1 = min(self.doc.w, int((view.right() - target.left()) / self.zoom) + 1)
        y0 = max(0, int((view.top() - target.top()) / self.zoom))
        y1 = min(self.doc.h, int((view.bottom() - target.top()) / self.zoom) + 1)
        for x in range(x0, x1 + 1):
            wx = target.left() + x * self.zoom
            p.drawLine(QPointF(wx, max(view.top(), target.top())), QPointF(wx, min(view.bottom(), target.bottom())))
        for y in range(y0, y1 + 1):
            wy = target.top() + y * self.zoom
            p.drawLine(QPointF(max(view.left(), target.left()), wy), QPointF(min(view.right(), target.right()), wy))

    # ---- mouse
    def _hand(self):
        return self._space or self._pan is not None

    def mousePressEvent(self, ev):
        self.setFocus()
        if self.doc is None:
            return
        if ev.button() == Qt.MiddleButton or (ev.button() == Qt.LeftButton and self._space):
            self._pan = (ev.position(), QPointF(self.offset))
            self.setCursor(Qt.ClosedHandCursor)
            return
        if ev.button() in (Qt.LeftButton, Qt.RightButton):
            self._down = True
            self._tool.press(self, self.to_doc(ev.position()), ev)
            self.update()

    def mouseDoubleClickEvent(self, ev):
        if self.doc is not None and ev.button() == Qt.LeftButton:
            if hasattr(self._tool, "double"):
                self._tool.double(self, self.to_doc(ev.position()), ev)
            elif getattr(self._tool, "name", "") in ("move", "text", "select", "wand"):
                self.edit_text_at(self.to_doc(ev.position()))

    def mouseMoveEvent(self, ev):
        if self.doc is None:
            return
        if self._pan is not None:
            s, o = self._pan
            self.offset = o + (ev.position() - s)
            self.view_changed()
            return
        p = self.to_doc(ev.position())
        self.hover = p
        if hasattr(self._tool, "hover"):
            self._tool.hover(self, p)
        x, y = int(math.floor(p.x())), int(math.floor(p.y()))
        if getattr(self, "_down", False):
            pass                                 # no pixel read-out while painting (keeps strokes smooth)
        elif 0 <= x < self.doc.w and 0 <= y < self.doc.h:
            c = self.doc.sample(x, y, True)
            self.info.emit(f"x {x}   y {y}     R {c.red()}  G {c.green()}  B {c.blue()}  A {c.alpha()}     zoom {self.zoom * 100:.0f}%")
        else:
            self.info.emit(f"zoom {self.zoom * 100:.0f}%")
        if ev.buttons() & (Qt.LeftButton | Qt.RightButton) and getattr(self, "_down", False):
            self._tool.move(self, p, ev)
        if self.state.tool in ("brush", "eraser", "clone", "heal", "spot", "smudge", "blurbrush", "sharpenbrush", "dodge", "burn"):
            r = int(self.state.size * self.zoom / 2.0) + 6
            pos = ev.position().toPoint()
            for q in (pos, self._last_cursor):
                if q is not None:
                    self.update(QRect(q.x() - r, q.y() - r, 2 * r + 1, 2 * r + 1))
            self._last_cursor = pos

    def mouseReleaseEvent(self, ev):
        if self._pan is not None:
            self._pan = None
            self.setCursor(Qt.OpenHandCursor if self._space else self._tool.cursor)
            return
        if getattr(self, "_down", False) and self.doc is not None:
            self._down = False
            self._tool.release(self, self.to_doc(ev.position()), ev)
            self.update()

    def leaveEvent(self, ev):
        self.hover = None
        self._last_cursor = None
        self.update()

    def wheelEvent(self, ev):
        if self.doc is None:
            return
        dy = ev.angleDelta().y()
        if ev.modifiers() & Qt.ControlModifier or not (ev.modifiers() & (Qt.ShiftModifier | Qt.AltModifier)):
            self.zoom_at(ev.position(), 1.15 ** (dy / 120.0))
        elif ev.modifiers() & Qt.ShiftModifier:
            self.offset += QPointF(dy / 2.0, 0)
            self.view_changed()
        else:
            self.offset += QPointF(0, dy / 2.0)
            self.view_changed()

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Space and not ev.isAutoRepeat():
            self._space = True
            self.setCursor(Qt.OpenHandCursor)
            return
        if self.doc is not None and self._tool.key(self, ev):
            return
        if k == Qt.Key_BracketLeft:
            self.state.set(size=max(1, int(self.state.size * 0.85) - 1))
        elif k == Qt.Key_BracketRight:
            self.state.set(size=min(500, int(self.state.size * 1.15) + 1))
        elif k == Qt.Key_X:
            self.state.swap()
        elif k == Qt.Key_D:
            self.state.reset_colors()
        elif k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and self.state.tool == "move" and self.doc:
            L = self.doc.layer()
            if L is not None and not L.locked:
                n = 10 if ev.modifiers() & Qt.ShiftModifier else 1
                with self.doc.edit("Nudge", []):
                    L.x += {Qt.Key_Left: -n, Qt.Key_Right: n}.get(k, 0)
                    L.y += {Qt.Key_Up: -n, Qt.Key_Down: n}.get(k, 0)
        else:
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat():
            self._space = False
            self.setCursor(self._tool.cursor)
            return
        super().keyReleaseEvent(ev)
