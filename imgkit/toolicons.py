"""Drawn tool icons (no image files needed)."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

INK = QColor("#1E2B25")
GREEN = QColor("#C2395C")
LIGHT = QColor("#DBC6EB")


def icon(key, size=32):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 32.0, size / 32.0)
    pen = QPen(INK, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    dash = QPen(INK, 1.6, Qt.DashLine)
    if key == "move":
        for a in (0, 90, 180, 270):
            p.save(); p.translate(16, 16); p.rotate(a)
            p.drawLine(0, 0, 0, -11); p.drawPolyline(QPolygonF([QPointF(-3, -8), QPointF(0, -12), QPointF(3, -8)]))
            p.restore()
    elif key in ("select_rect", "select"):
        p.setPen(dash); p.drawRect(QRectF(6, 8, 20, 16))
    elif key == "select_ellipse":
        p.setPen(dash); p.drawEllipse(QRectF(5, 7, 22, 18))
    elif key == "select_rounded":
        p.setPen(dash); p.drawRoundedRect(QRectF(6, 8, 20, 16), 6, 6)
    elif key == "lasso":
        path = QPainterPath(QPointF(8, 14)); path.cubicTo(8, 4, 26, 4, 26, 13); path.cubicTo(26, 22, 12, 24, 10, 19)
        p.setPen(dash); p.drawPath(path); p.setPen(pen); p.drawLine(10, 19, 8, 27)
    elif key == "poly":
        p.setPen(dash); p.drawPolyline(QPolygonF([QPointF(6, 22), QPointF(10, 7), QPointF(24, 6), QPointF(27, 20), QPointF(16, 26), QPointF(6, 22)]))
    elif key == "wand":
        p.drawLine(6, 26, 20, 12)
        p.setPen(QPen(GREEN, 2.4, Qt.SolidLine, Qt.RoundCap)); p.drawLine(6, 26, 14, 18)
        p.setPen(QPen(QColor("#E5A800"), 1.6, Qt.SolidLine, Qt.RoundCap))
        for a in range(0, 360, 60):
            p.save(); p.translate(23, 9); p.rotate(a); p.drawLine(3, 0, 6, 0); p.restore()
    elif key == "brush":
        path = QPainterPath(QPointF(8, 26)); path.cubicTo(5, 20, 10, 19, 13, 20)
        p.setBrush(GREEN); p.setPen(Qt.NoPen); p.drawPath(path); p.drawEllipse(QPointF(10, 24), 4, 3.5)
        p.setPen(QPen(INK, 3.2, Qt.SolidLine, Qt.RoundCap)); p.drawLine(15, 19, 26, 6)
    elif key == "eraser":
        p.save(); p.translate(16, 17); p.rotate(-40)
        p.setBrush(QColor("#F4B8B8")); p.drawRoundedRect(QRectF(-11, -6, 22, 12), 2, 2)
        p.setBrush(Qt.white); p.drawRect(QRectF(-11, -6, 9, 12))
        p.restore()
    elif key in ("clone", "heal", "spot"):
        if key == "clone":
            p.setBrush(LIGHT); p.drawRoundedRect(QRectF(11, 5, 10, 8), 2, 2); p.drawRect(QRectF(14, 13, 4, 6)); p.drawRoundedRect(QRectF(8, 19, 16, 7), 2, 2)
        else:
            p.setBrush(QColor("#F6E0C8")); p.drawRoundedRect(QRectF(5, 12, 22, 9), 4.5, 4.5)
            p.setBrush(Qt.white); p.drawRect(QRectF(13, 12, 6, 9))
            if key == "spot":
                p.setBrush(GREEN); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(16, 16.5), 1.5, 1.5)
    elif key == "smudge":
        path = QPainterPath(QPointF(6, 22)); path.cubicTo(10, 8, 18, 26, 26, 10)
        p.setPen(QPen(GREEN, 3.5, Qt.SolidLine, Qt.RoundCap)); p.drawPath(path)
        p.setPen(QPen(INK, 1.8)); p.drawLine(24, 12, 28, 6)
    elif key == "blurbrush":
        for i, r in enumerate((10, 7, 4)):
            c = QColor(GREEN); c.setAlpha(60 + i * 70); p.setPen(Qt.NoPen); p.setBrush(c); p.drawEllipse(QPointF(16, 16), r, r)
    elif key == "sharpenbrush":
        p.setBrush(LIGHT); p.drawPolygon(QPolygonF([QPointF(16, 4), QPointF(27, 26), QPointF(5, 26)]))
    elif key == "dodge":
        p.setBrush(Qt.white); p.drawEllipse(QPointF(16, 17), 6, 6)
        for a in range(0, 360, 45):
            p.save(); p.translate(16, 17); p.rotate(a); p.drawLine(9, 0, 12, 0); p.restore()
    elif key == "burn":
        p.setBrush(INK); p.drawEllipse(QPointF(16, 16), 9, 9)
        p.setBrush(Qt.white); p.setPen(Qt.NoPen); p.drawEllipse(QPointF(19, 14), 5, 6)
    elif key == "fill":
        p.save(); p.translate(15, 15); p.rotate(-20)
        p.setBrush(LIGHT); p.drawRect(QRectF(-8, -8, 16, 16)); p.restore()
        p.setBrush(GREEN); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(26, 17), QPointF(23, 23), QPointF(29, 23)]))
        p.drawEllipse(QPointF(26, 24), 2.2, 2.2)
    elif key == "gradient":
        g = QLinearGradient(5, 0, 27, 0); g.setColorAt(0, Qt.white); g.setColorAt(1, GREEN)
        p.setBrush(g); p.drawRoundedRect(QRectF(5, 8, 22, 16), 2, 2)
    elif key == "eyedropper":
        p.drawLine(8, 24, 18, 14)
        p.setBrush(Qt.white); p.drawPolygon(QPolygonF([QPointF(5, 27), QPointF(8, 20), QPointF(12, 24)]))
        p.save(); p.translate(21, 11); p.rotate(45); p.setBrush(GREEN); p.drawRoundedRect(QRectF(-3, -8, 6, 16), 2, 2); p.restore()
    elif key == "text":
        f = QFont("Sans Serif"); f.setBold(True); f.setPixelSize(26)
        p.setFont(f); p.drawText(QRectF(0, 0, 32, 32), Qt.AlignCenter, "T")
    elif key == "shape_rect":
        p.setBrush(LIGHT); p.drawRect(QRectF(5, 8, 22, 16))
    elif key == "shape_rounded":
        p.setBrush(LIGHT); p.drawRoundedRect(QRectF(5, 8, 22, 16), 5, 5)
    elif key == "shape_ellipse":
        p.setBrush(LIGHT); p.drawEllipse(QRectF(4, 7, 24, 18))
    elif key == "shape_line":
        p.drawLine(6, 26, 26, 6)
    elif key == "crop":
        p.drawPolyline(QPolygonF([QPointF(9, 3), QPointF(9, 23), QPointF(29, 23)]))
        p.drawPolyline(QPolygonF([QPointF(3, 9), QPointF(23, 9), QPointF(23, 29)]))
    elif key == "transform":
        p.setPen(dash); p.drawRect(QRectF(8, 8, 16, 16))
        p.setPen(pen); p.setBrush(Qt.white)
        for x, y in ((8, 8), (24, 8), (8, 24), (24, 24), (16, 8), (16, 24), (8, 16), (24, 16)):
            p.drawRect(QRectF(x - 2, y - 2, 4, 4))
    elif key == "hand":
        p.setBrush(Qt.white)
        p.drawRoundedRect(QRectF(9, 13, 14, 12), 4, 4)
        for x, top in ((10.5, 7), (14, 5), (17.5, 5), (21, 8)):
            p.drawRoundedRect(QRectF(x, top, 3, 14), 1.5, 1.5)
    elif key == "zoom":
        p.setBrush(Qt.white); p.drawEllipse(QPointF(13, 13), 8, 8)
        p.setPen(QPen(INK, 3, Qt.SolidLine, Qt.RoundCap)); p.drawLine(19, 19, 27, 27)
    p.end()
    return QIcon(pm)
