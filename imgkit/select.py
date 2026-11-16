"""Selections: a 0-255 mask the size of the picture, plus an outline for the marching ants."""
import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

from . import arr


def _box(a, r, axis):
    """running mean over a window of 2r+1 along an axis (edges repeat)"""
    if r <= 0:
        return a
    a = np.moveaxis(a, axis, 0)
    n = a.shape[0]
    pad = np.concatenate([np.repeat(a[:1], r, 0), a, np.repeat(a[-1:], r, 0)], 0)
    c = np.cumsum(pad, 0, dtype=np.float64)
    c = np.concatenate([np.zeros((1,) + a.shape[1:]), c], 0)
    out = (c[2 * r + 1:2 * r + 1 + n] - c[:n]) / (2 * r + 1)
    return np.moveaxis(out, 0, axis)


def blur(a, radius, passes=3):
    """close to a gaussian: three box blurs"""
    a = a.astype(np.float32)
    r = max(1, int(round(radius * 0.58)))
    for _ in range(passes):
        a = _box(a, r, 0)
        a = _box(a, r, 1)
    return a


class Selection:
    def __init__(self, mask, path=None):
        self.mask = mask                      # uint8 (h, w)
        self._path = path
        self._bbox = None

    # ---- construction
    @staticmethod
    def from_path(path, w, h, antialias=True):
        im = QImage(w, h, QImage.Format_Grayscale8)
        im.fill(0)
        p = QPainter(im)
        p.setRenderHint(QPainter.Antialiasing, antialias)
        p.fillPath(path, QColor(255, 255, 255))
        p.end()
        return Selection(arr.to_mask(im), QPainterPath(path))

    @staticmethod
    def all(w, h):
        return Selection(np.full((h, w), 255, np.uint8))

    # ---- info
    @property
    def size(self):
        return self.mask.shape[1], self.mask.shape[0]

    def bbox(self):
        if self._bbox is None:
            on = self.mask > 127
            rows, cols = np.flatnonzero(on.any(1)), np.flatnonzero(on.any(0))          # no giant index arrays
            self._bbox = QRect(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1)) if len(rows) else QRect()
        return self._bbox

    def empty(self):
        return not (self.mask > 127).any()

    def outline(self):
        """QPainterPath around the selected area (for the dashed line)"""
        if self._path is not None:
            return self._path
        h, w = self.mask.shape
        on = self.mask > 127
        if not on.any():
            self._path = QPainterPath()
            return self._path
        step = max(1, int((h * w / 1.6e6) ** 0.5))     # big pictures are traced on a coarser grid (fast)
        while True:                                   # very detailed masks are traced on a coarser grid
            m = on[::step, ::step]
            rects = self._runs(m)
            if len(rects) < 12000 or step >= 8:
                break
            step += 1
        p = QPainterPath()
        for x0, y0, x1, y1 in rects:
            p.addRect(QRectF(x0 * step, y0 * step, (x1 - x0) * step, (y1 - y0) * step))
        self._path = p.simplified()
        return self._path

    @staticmethod
    def _runs(m):
        """rectangles (x0, y0, x1, y1) covering the True pixels: horizontal runs merged down while they repeat"""
        h, w = m.shape
        out, open_ = [], {}
        pad = np.zeros((h, w + 2), np.int8)
        pad[:, 1:-1] = m
        d = np.diff(pad, axis=1)
        for y in range(h + 1):
            if y < h:
                st, en = np.flatnonzero(d[y] == 1), np.flatnonzero(d[y] == -1)
                cur = set(zip(st.tolist(), en.tolist()))
            else:
                cur = set()
            for key in list(open_):
                if key not in cur:
                    out.append((key[0], open_.pop(key), key[1], y))
            for key in cur:
                open_.setdefault(key, y)
        return out

    # ---- changes (each returns a new Selection)
    def combine(self, other, mode):
        a, b = self.mask.astype(np.int16), other.mask.astype(np.int16)
        if mode == "add":
            m = np.maximum(a, b)
        elif mode == "sub":
            m = np.clip(a - b, 0, 255)
        elif mode == "and":
            m = np.minimum(a, b)
        else:
            return other
        return Selection(m.astype(np.uint8))

    def inverted(self):
        return Selection(255 - self.mask)

    def feathered(self, r):
        if r <= 0:
            return self
        return Selection(np.clip(blur(self.mask, r), 0, 255).astype(np.uint8))

    def grown(self, n):
        """n > 0 grows, n < 0 shrinks (square steps)"""
        m = self.mask
        for _ in range(abs(int(n))):
            p = np.pad(m, 1, mode="edge")
            stack = [p[y:y + m.shape[0], x:x + m.shape[1]] for y in range(3) for x in range(3)]
            m = np.maximum.reduce(stack) if n > 0 else np.minimum.reduce(stack)
        return Selection(m)

    def smoothed(self, r):
        m = (blur(self.mask, r) > 127).astype(np.uint8) * 255
        return Selection(m)

    def moved(self, dx, dy):
        h, w = self.mask.shape
        out = np.zeros_like(self.mask)
        x0, y0 = max(0, dx), max(0, dy)
        x1, y1 = min(w, w + dx), min(h, h + dy)
        if x1 > x0 and y1 > y0:
            out[y0:y1, x0:x1] = self.mask[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
        return Selection(out)

    def resized(self, w, h, ox=0, oy=0):
        """for canvas size / crop: new mask size, old content placed at (ox, oy)"""
        out = np.zeros((h, w), np.uint8)
        sh, sw = self.mask.shape
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(w, ox + sw), min(h, oy + sh)
        if x1 > x0 and y1 > y0:
            out[y0:y1, x0:x1] = self.mask[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
        return Selection(out)

    def copy(self):
        s = Selection(self.mask.copy(), QPainterPath(self._path) if self._path is not None else None)
        return s


def flood(img, x, y, tol, contiguous=True, sample=None):
    """magic wand: mask (h, w) uint8 of pixels close in color to the one at (x, y). tol 0-255.
    img is a QImage; sample is an optional QImage to sample from (e.g. the merged picture)."""
    a = arr.to_array(sample if sample is not None else img, True).astype(np.int16)
    h, w = a.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return np.zeros((h, w), np.uint8)
    ref = a[y, x]
    d = np.abs(a - ref).max(axis=2)
    close = d <= tol
    if not contiguous:
        return (close * 255).astype(np.uint8)
    # connected component by scanline fill on the boolean image
    out = np.zeros((h, w), bool)
    stack = [(x, y)]
    while stack:
        cx, cy = stack.pop()
        if out[cy, cx] or not close[cy, cx]:
            continue
        row = close[cy]
        nz = np.flatnonzero(~row[:cx + 1])
        l = int(nz[-1]) + 1 if len(nz) else 0
        nz = np.flatnonzero(~row[cx:])
        r = cx + int(nz[0]) - 1 if len(nz) else w - 1
        out[cy, l:r + 1] = True
        for ny in (cy - 1, cy + 1):
            if 0 <= ny < h:
                nrow = close[ny]
                seg = nrow[l:r + 1] & ~out[ny, l:r + 1]
                if seg.any():
                    # push one seed per run
                    idx = np.nonzero(seg)[0]
                    starts = idx[np.r_[True, np.diff(idx) > 1]]
                    for sx in starts:
                        stack.append((l + int(sx), ny))
    return (out * 255).astype(np.uint8)
