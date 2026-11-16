"""Photoshop preset files: brushes (.abr), gradients (.grd), swatches (.aco, .act).
Written from the file formats; every reader is best effort and reports what it could not read."""
import struct

import numpy as np
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap

from . import arr


class PresetError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ swatches
def read_aco(data):
    """Photoshop colour swatches. Returns [(name, QColor)]"""
    pos = 0
    sections = []
    while pos + 4 <= len(data):
        ver, count = struct.unpack_from(">HH", data, pos)
        if ver not in (1, 2):
            break
        pos += 4
        start = pos
        items = []
        for _ in range(count):
            if pos + 10 > len(data):
                break
            space, a, b, c, d = struct.unpack_from(">HHHHH", data, pos)
            pos += 10
            name = ""
            if ver == 2:
                pos += 2                                  # 0 separator
                (ln,) = struct.unpack_from(">H", data, pos)
                pos += 2
                name = data[pos:pos + max(0, ln - 1) * 2].decode("utf-16-be", "ignore")
                pos += ln * 2
            col = _aco_color(space, a, b, c, d)
            if col is not None:
                items.append((name or col.name().upper(), col))
        sections.append((ver, items))
    if not sections:
        raise PresetError("no colours found")
    best = [s for s in sections if s[0] == 2] or sections       # version 2 has the names
    return best[0][1]


def _aco_color(space, a, b, c, d):
    if space == 0:
        return QColor(a >> 8, b >> 8, c >> 8)
    if space == 1:
        return QColor.fromHsvF(min(1.0, a / 65535.0), b / 65535.0, c / 65535.0) if a < 65536 else None
    if space == 2:                                        # CMYK: stored inverted (65535 = no ink)
        return QColor.fromCmykF((65535 - a) / 65535.0, (65535 - b) / 65535.0, (65535 - c) / 65535.0, (65535 - d) / 65535.0)
    if space == 8:
        v = int(round(a / 10000.0 * 255))
        return QColor(v, v, v)
    return None


def read_act(data):
    if len(data) < 768:
        raise PresetError("not a colour table")
    n = 256
    if len(data) >= 772:
        n = struct.unpack_from(">H", data, 768)[0] or 256
    n = min(n, 256)
    out = []
    for i in range(n):
        r, g, b = data[i * 3:i * 3 + 3]
        c = QColor(r, g, b)
        out.append((c.name().upper(), c))
    return out


def read_swatches(path):
    data = open(path, "rb").read()
    return read_act(data) if path.lower().endswith(".act") else read_aco(data)


# ------------------------------------------------------------------------------------------------ brushes
def _unpackbits(src, n):
    out = bytearray()
    i = 0
    while i < len(src) and len(out) < n:
        c = src[i] if src[i] < 128 else src[i] - 256
        i += 1
        if c >= 0:
            out += src[i:i + c + 1]
            i += c + 1
        elif c != -128:
            out += src[i:i + 1] * (1 - c)
            i += 1
    return bytes(out[:n])


def _read_rect_and_pixels(d, pos, end):
    """top,left,bottom,right (int32 x4), depth int16, compression int8, then the pixels. -> (array, newpos) or None"""
    if pos + 19 > len(d):
        return None
    top, left, bottom, right, depth, comp = struct.unpack_from(">iiiihb", d, pos)
    w, h = right - left, bottom - top
    if not (0 < w <= 4000 and 0 < h <= 4000 and depth in (8, 16) and comp in (0, 1) and top >= 0 and left >= 0):
        return None
    pos += 19
    bpp = depth // 8
    if comp == 0:
        need = w * h * bpp
        if pos + need > len(d):
            return None
        buf = d[pos:pos + need]
        pos += need
    else:
        counts = struct.unpack_from(">%dH" % h, d, pos)
        pos += 2 * h
        rows = bytearray()
        for cnt in counts:
            rows += _unpackbits(d[pos:pos + cnt], w * bpp)
            pos += cnt
        buf = bytes(rows)
        if len(buf) != w * h * bpp:
            return None
    a = np.frombuffer(buf, np.uint8 if bpp == 1 else ">u2").reshape(h, w)
    if bpp == 2:
        a = (a >> 8).astype(np.uint8)
    return a.copy(), pos


def _ink(a):
    """make 255 = paint. Tips come with either polarity: the corners are background."""
    edge = np.concatenate([a[0, :], a[-1, :], a[:, 0], a[:, -1]]).mean()
    return (255 - a) if edge > 127 else a


def read_abr(path):
    """-> [dict(name, alpha=uint8 (h, w) with 255 = paint, spacing=percent)]"""
    d = open(path, "rb").read()
    if len(d) < 4:
        raise PresetError("empty file")
    ver = struct.unpack_from(">H", d, 0)[0]
    out = []
    if ver in (1, 2):
        count = struct.unpack_from(">H", d, 2)[0]
        pos = 4
        for i in range(count):
            if pos + 6 > len(d):
                break
            typ, size = struct.unpack_from(">Hi", d, pos)
            pos += 6
            end = pos + size
            if typ == 2:
                p = pos + 4
                spacing = struct.unpack_from(">H", d, p)[0]
                p += 2
                name = ""
                if ver == 2:
                    (ln,) = struct.unpack_from(">I", d, p)
                    p += 4
                    name = d[p:p + max(0, ln - 1) * 2].decode("utf-16-be", "ignore")
                    p += ln * 2
                p += 1 + 8                                     # antialiasing + 4 shorts of bounds
                got = _read_rect_and_pixels(d, p, end)
                if got:
                    out.append(dict(name=name or f"Brush {len(out) + 1}", alpha=_ink(got[0]), spacing=max(1, spacing)))
            pos = end
    else:
        i = d.find(b"8BIMsamp")
        if i < 0:
            raise PresetError("this brush file version is not supported")
        (ln,) = struct.unpack_from(">I", d, i + 8)
        pos, end = i + 12, i + 12 + ln
        while pos + 4 < end:
            (bl,) = struct.unpack_from(">I", d, pos)
            pos += 4
            bend = pos + bl
            if bl <= 0 or bend > len(d):
                break
            plen = d[pos] if pos < len(d) else 0
            name = f"Brush {len(out) + 1}"
            got = None
            for off in range(pos + 1 + plen, min(bend, pos + 1 + plen + 80)):     # the rectangle follows some unknown bytes
                got = _read_rect_and_pixels(d, off, bend)
                if got:
                    break
            if got:
                out.append(dict(name=name, alpha=_ink(got[0]), spacing=25))
            pos = (bend + 3) & ~3
    if not out:
        raise PresetError("no sampled brushes found (round computed brushes are not read)")
    return out


def tip_qimage(alpha):
    """alpha mask (255 = paint) -> QImage Alpha8-like grayscale"""
    return arr.from_mask(alpha)


# ------------------------------------------------------------------------------------------------ gradients
class _R:
    def __init__(self, d, p=0):
        self.d, self.p = d, p

    def u32(self):
        v = struct.unpack_from(">I", self.d, self.p)[0]
        self.p += 4
        return v

    def i32(self):
        v = struct.unpack_from(">i", self.d, self.p)[0]
        self.p += 4
        return v

    def f64(self):
        v = struct.unpack_from(">d", self.d, self.p)[0]
        self.p += 8
        return v

    def key(self):
        n = self.u32()
        n = n or 4
        s = self.d[self.p:self.p + n].decode("latin-1")
        self.p += n
        return s

    def ustr(self):
        n = self.u32()
        s = self.d[self.p:self.p + n * 2].decode("utf-16-be", "ignore").rstrip("\x00")
        self.p += n * 2
        return s


def _value(r, typ):
    if typ == "Objc":
        return _descriptor(r)
    if typ == "VlLs":
        n = r.u32()
        lst = []
        for _ in range(n):
            t = r.d[r.p:r.p + 4].decode("latin-1")
            r.p += 4
            lst.append(_value(r, t))
        return lst
    if typ == "doub":
        return r.f64()
    if typ == "long":
        return r.i32()
    if typ == "bool":
        v = r.d[r.p]
        r.p += 1
        return bool(v)
    if typ == "TEXT":
        return r.ustr()
    if typ == "enum":
        r.key()
        return r.key()
    if typ == "UntF":
        r.p += 4
        return r.f64()
    if typ == "type" or typ == "GlbC":
        r.ustr()
        return r.key()
    raise PresetError("unknown value type " + typ)


def _descriptor(r):
    r.ustr()                       # name
    cls = r.key()
    n = r.u32()
    out = {"_class": cls}
    for _ in range(n):
        k = r.key()
        t = r.d[r.p:r.p + 4].decode("latin-1")
        r.p += 4
        out[k] = _value(r, t)
    return out


def _stop_color(c, fg, bg):
    cls = c.get("_class")
    if cls == "RGBC":
        return (c.get("Rd  ", 0), c.get("Grn ", 0), c.get("Bl  ", 0))
    if cls == "Grsc":
        v = c.get("Gry ", 0) * 255 / 100.0 if c.get("Gry ", 0) <= 100 else c.get("Gry ", 0)
        return (v, v, v)
    if cls == "HSBC":
        q = QColor.fromHsvF(((c.get("H   ", 0) % 360) / 360.0), c.get("Strt", 0) / 100.0, c.get("Brgh", 0) / 100.0)
        return (q.red(), q.green(), q.blue())
    if cls == "CMYC":
        q = QColor.fromCmykF(c.get("Cyn ", 0) / 100.0, c.get("Mgnt", 0) / 100.0, c.get("Ylw ", 0) / 100.0, c.get("Blck", 0) / 100.0)
        return (q.red(), q.green(), q.blue())
    return (128, 128, 128)


def read_grd(path):
    """-> [dict(name, stops=[(pos 0-1, (r,g,b))], alpha=[(pos 0-1, 0-1)], uses_fg_bg=[...])]"""
    d = open(path, "rb").read()
    if d[:4] != b"8BGR":
        raise PresetError("this is not a Photoshop gradient file")
    ver = struct.unpack_from(">H", d, 4)[0]
    if ver < 5:
        raise PresetError(f"gradient files of version {ver} (Photoshop 5 and older) are not supported")
    i = d.find(b"GrdL")
    if i < 0:
        raise PresetError("no gradients found")
    obj = None
    for back in range(10, 48):
        try:
            r = _R(d, i - back)
            obj = _descriptor(r)
            if obj.get("GrdL"):
                break
        except Exception:
            obj = None
    if not obj or not obj.get("GrdL"):
        raise PresetError("could not read the gradient list")
    out = []
    for g in obj["GrdL"]:
        try:
            gr = g.get("Grad", g)
            name = gr.get("Nm  ", g.get("Nm  ", f"Gradient {len(out) + 1}"))
            clrs = gr.get("Clrs", [])
            if not clrs:
                continue
            stops = []
            for c in clrs:
                loc = c.get("Lctn", 0) / 4096.0
                t = c.get("Type", "UsrS")
                col = _stop_color(c.get("Clr ", {}), None, None) if t == "UsrS" else ("fg" if t == "FrgC" else "bg")
                stops.append((loc, col))
            alpha = [(t.get("Lctn", 0) / 4096.0, t.get("Opct", 100.0) / 100.0) for t in gr.get("Trns", [])] or [(0.0, 1.0), (1.0, 1.0)]
            out.append(dict(name=name, stops=sorted(stops, key=lambda s: s[0]), alpha=sorted(alpha)))
        except Exception:
            continue
    if not out:
        raise PresetError("no readable gradients in this file")
    return out


def _interp(points, t):
    """points sorted [(pos, value)]; value a number or tuple"""
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for (p0, v0), (p1, v1) in zip(points, points[1:]):
        if p0 <= t <= p1:
            k = 0 if p1 == p0 else (t - p0) / (p1 - p0)
            if isinstance(v0, tuple):
                return tuple(a + (b - a) * k for a, b in zip(v0, v1))
            return v0 + (v1 - v0) * k
    return points[-1][1]


def gradient_stops(g, fg, bg):
    """-> [(pos, QColor)] for a Qt gradient, resolving foreground / background stops"""
    def rgb(c):
        if c == "fg":
            return (fg.red(), fg.green(), fg.blue())
        if c == "bg":
            return (bg.red(), bg.green(), bg.blue())
        return c
    cpts = [(p, rgb(c)) for p, c in g["stops"]]
    apts = g["alpha"]
    pos = sorted({p for p, _c in cpts} | {p for p, _a in apts})
    out = []
    for p in pos:
        r, gg, b = _interp(cpts, p)
        a = _interp(apts, p)
        out.append((p, QColor(int(round(r)), int(round(gg)), int(round(b)), int(round(max(0, min(1, a)) * 255)))))
    return out


def builtin_gradients():
    S = lambda *cs: [(i / (len(cs) - 1), c) for i, c in enumerate(cs)]
    A = [(0.0, 1.0), (1.0, 1.0)]
    return [
        dict(name="Front to back colour", stops=[(0.0, "fg"), (1.0, "bg")], alpha=A),
        dict(name="Front to transparent", stops=[(0.0, "fg"), (1.0, "fg")], alpha=[(0.0, 1.0), (1.0, 0.0)]),
        dict(name="Black, white", stops=S((0, 0, 0), (255, 255, 255)), alpha=A),
        dict(name="Sunrise", stops=S((255, 201, 74), (255, 122, 61), (232, 48, 79), (142, 17, 80)), alpha=A),
        dict(name="Digonto green", stops=S((34, 181, 115), (0, 128, 90), (0, 77, 55)), alpha=A),
        dict(name="Rainbow", stops=S((232, 48, 79), (255, 201, 74), (123, 211, 137), (31, 181, 196), (47, 91, 234), (107, 63, 208)), alpha=A),
        dict(name="Ocean", stops=S((198, 240, 255), (47, 140, 234), (10, 40, 110)), alpha=A),
        dict(name="Metal", stops=S((250, 250, 250), (150, 155, 160), (240, 240, 240), (110, 115, 120), (230, 230, 230)), alpha=A),
        dict(name="Sunset sky", stops=S((255, 236, 170), (255, 150, 90), (200, 70, 120), (60, 40, 110)), alpha=A),
    ]


def gradient_icon(g, fg, bg, w=96, h=16):
    pm = QPixmap(w, h)
    pm.fill(QColor("#FFFFFF"))
    p = QPainter(pm)
    lg = QLinearGradient(0, 0, w, 0)
    for pos, c in gradient_stops(g, fg, bg):
        lg.setColorAt(max(0.0, min(1.0, pos)), c)
    p.fillRect(0, 0, w, h, lg)
    p.setPen(QColor("#888"))
    p.drawRect(0, 0, w - 1, h - 1)
    p.end()
    return pm
