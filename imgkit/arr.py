"""QImage <-> NumPy. Layers are stored as RGBA8888 with premultiplied alpha (what Qt paints fastest)."""
import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage

PM = QImage.Format_RGBA8888_Premultiplied
ST = QImage.Format_RGBA8888


def new_image(w, h, color=None):
    im = QImage(max(1, int(w)), max(1, int(h)), PM)
    im.fill(QColor(color) if color is not None else Qt.transparent)
    return im


def to_array(img, straight=True):
    """-> uint8 array (h, w, 4) RGBA (a copy you may change)"""
    im = img.convertToFormat(ST if straight else PM)
    h, w = im.height(), im.width()
    return np.frombuffer(im.constBits(), np.uint8).reshape(h, im.bytesPerLine() // 4, 4)[:, :w, :].copy()


def from_array(a, straight=True):
    """uint8 (h, w, 4) RGBA -> premultiplied layer image"""
    a = np.ascontiguousarray(a, dtype=np.uint8)
    h, w = a.shape[:2]
    im = QImage(a.data, w, h, w * 4, ST if straight else PM).copy()
    return im if not straight else im.convertToFormat(PM)


def to_mask(img):
    """Alpha8 / grayscale image -> uint8 (h, w)"""
    im = img.convertToFormat(QImage.Format_Grayscale8)
    h, w = im.height(), im.width()
    return np.frombuffer(im.constBits(), np.uint8).reshape(h, im.bytesPerLine())[:, :w].copy()


def from_mask(m):
    m = np.ascontiguousarray(m, dtype=np.uint8)
    h, w = m.shape
    return QImage(m.data, w, h, w, QImage.Format_Grayscale8).copy()


def qcolor_rgba(c):
    c = QColor(c)
    return c.red(), c.green(), c.blue(), c.alpha()
