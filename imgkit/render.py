"""Drawing one layer into the picture: layer mask, layer styles (shadow, glow, stroke, colour overlay) and adjustment layers."""
import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter

from . import adjlayers, arr
from .select import blur

DEFAULT_STYLE = {
    "shadow": {"on": False, "dx": 6, "dy": 6, "blur": 8, "color": "#000000", "opacity": 60},
    "glow": {"on": False, "size": 10, "color": "#FFE066", "opacity": 70},
    "stroke": {"on": False, "size": 3, "color": "#000000", "opacity": 100},
    "overlay": {"on": False, "color": "#C2395C", "opacity": 100},
}


def new_style():
    return {k: dict(v) for k, v in DEFAULT_STYLE.items()}


def style_active(st):
    return bool(st) and any(v.get("on") for v in st.values())


def style_margin(st):
    if not style_active(st):
        return 0
    m = 0
    s = st.get("shadow", {})
    if s.get("on"):
        m = max(m, int(max(abs(s["dx"]), abs(s["dy"])) + s["blur"] * 1.8 + 2))
    if st.get("glow", {}).get("on"):
        m = max(m, int(st["glow"]["size"] * 2 + 2))
    if st.get("stroke", {}).get("on"):
        m = max(m, int(st["stroke"]["size"] + 2))
    return m


def _rgb(c):
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def _dilate(a, n):
    """grow a 0..1 alpha by n pixels (round-ish)"""
    a = a.copy()
    for i in range(int(n)):
        b = a.copy()
        b[1:] = np.maximum(b[1:], a[:-1])
        b[:-1] = np.maximum(b[:-1], a[1:])
        b[:, 1:] = np.maximum(b[:, 1:], a[:, :-1])
        b[:, :-1] = np.maximum(b[:, :-1], a[:, 1:])
        if i % 2:
            c = b.copy()
            c[1:, 1:] = np.maximum(c[1:, 1:], a[:-1, :-1])
            c[:-1, :-1] = np.maximum(c[:-1, :-1], a[1:, 1:])
            c[1:, :-1] = np.maximum(c[1:, :-1], a[:-1, 1:])
            c[:-1, 1:] = np.maximum(c[:-1, 1:], a[1:, :-1])
            b = c
        a = b
    return a


def _over(dst, src):
    """premultiplied float arrays, src over dst"""
    return src + dst * (1 - src[..., 3:4])


def _region_array(img, reg, lx, ly):
    """premultiplied float RGBA (0..1) of the part of a layer picture inside reg (doc coordinates); outside the picture = empty"""
    sub = img.copy(QRect(reg.x() - lx, reg.y() - ly, reg.width(), reg.height()))
    return arr.to_array(sub, straight=False).astype(np.float32) / 255.0


def layer_pixels(l, reg):
    """the layer inside reg with its mask applied - premultiplied float (h, w, 4)"""
    a = _region_array(l._image, reg, l.x, l.y)
    if l._mask is not None and l.mask_on:
        m = _region_array(l._mask, reg, l.x, l.y)[..., 0]
        a = a * m[..., None]
    return a


def _styled(a, st):
    """a = layer pixels (premultiplied float); returns the finished premultiplied picture with the styles drawn around/over it"""
    al = a[..., 3]
    out = np.zeros_like(a)
    s = st.get("shadow", {})
    if s.get("on"):
        sh = np.roll(np.roll(al, int(s["dy"]), 0), int(s["dx"]), 1)
        if s["blur"] > 0:
            sh = blur(sh, s["blur"])
        k = np.clip(sh, 0, 1) * s["opacity"] / 100.0
        c = _rgb(s["color"]) / 255.0
        out = _over(out, np.dstack([c[0] * k, c[1] * k, c[2] * k, k]))
    g = st.get("glow", {})
    if g.get("on"):
        sh = blur(_dilate(al, max(1, int(g["size"] / 2))), max(1.0, g["size"]))
        k = np.clip(sh * 1.4, 0, 1) * g["opacity"] / 100.0
        c = _rgb(g["color"]) / 255.0
        out = _over(out, np.dstack([c[0] * k, c[1] * k, c[2] * k, k]))
    t = st.get("stroke", {})
    if t.get("on"):
        d = _dilate(al, t["size"])
        k = np.clip(d - al * 0, 0, 1) * t["opacity"] / 100.0
        c = _rgb(t["color"]) / 255.0
        out = _over(out, np.dstack([c[0] * k, c[1] * k, c[2] * k, k]))
    out = _over(out, a)
    o = st.get("overlay", {})
    if o.get("on"):
        c = _rgb(o["color"]) / 255.0
        k = o["opacity"] / 100.0
        al2 = a[..., 3:4]
        cc = np.concatenate([c[None, None, :] * al2, al2], -1)
        out[..., :3] = out[..., :3] * (1 - al2 * k) + cc[..., :3] * k
    return out


def draw_layer(target, l, rect, modes):
    """draw layer l into the merged picture, only inside rect (doc coordinates)"""
    if l.adj:
        return _adjustment(target, l, rect)
    st = l.style if style_active(l.style) else None
    mar = style_margin(st) if st else 0
    lr = l.rect().adjusted(-mar, -mar, mar, mar)
    if not lr.intersects(rect):
        return
    p = QPainter(target)
    p.setClipRect(rect)
    p.setOpacity(l.opacity)
    p.setCompositionMode(modes.get(l.blend, QPainter.CompositionMode_SourceOver))
    if st is None and (l._mask is None or not l.mask_on):
        p.drawImage(l.x, l.y, l._image)
        p.end()
        return
    reg = rect.adjusted(-mar, -mar, mar, mar).intersected(lr)
    a = layer_pixels(l, reg)
    if st:
        a = _styled(a, st)
    img = arr.from_array(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8), straight=False)
    p.drawImage(reg.x(), reg.y(), img)
    p.end()


def _adjustment(target, l, rect):
    reg = rect.intersected(QRect(0, 0, target.width(), target.height()))
    if reg.isEmpty() or l.adj.get("kind") not in adjlayers.KINDS:
        return
    sub = target.copy(reg)
    a = arr.to_array(sub)                              # straight RGBA
    res = adjlayers.apply(l.adj, a)
    k = np.full(a.shape[:2], l.opacity, np.float32)
    if l._mask is not None and l.mask_on:
        k = k * _region_array(l._mask, reg, l.x, l.y)[..., 0]
    k = k[..., None]
    out = a.astype(np.float32) * (1 - k) + res.astype(np.float32) * k
    out[..., 3] = a[..., 3]
    img = arr.from_array(np.clip(out + 0.5, 0, 255).astype(np.uint8))
    p = QPainter(target)
    p.setClipRect(reg)
    p.setCompositionMode(QPainter.CompositionMode_Source)
    p.drawImage(reg.x(), reg.y(), img)
    p.end()
