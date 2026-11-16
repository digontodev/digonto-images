"""Reads the text inside Photoshop text layers (the 'TySh' block): the words,
font name, size, colour, alignment. Best effort: anything unreadable is skipped."""
import re
import struct


class _R:
    def __init__(self, data, pos=0):
        self.d = data
        self.p = pos

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

    def u16(self):
        v = struct.unpack_from(">H", self.d, self.p)[0]
        self.p += 2
        return v

    def take(self, n):
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def unicode(self):
        n = self.u32()
        s = self.take(2 * n).decode("utf-16-be", "replace")
        return s.rstrip("\x00")

    def key(self):
        n = self.u32()
        return self.take(n or 4).decode("latin-1")


def _value(r, t):
    if t == "TEXT":
        return r.unicode()
    if t == "long":
        return r.i32()
    if t == "doub":
        return r.f64()
    if t == "bool":
        return bool(r.take(1)[0])
    if t == "UntF":
        r.take(4)
        return r.f64()
    if t == "enum":
        r.key()
        return r.key()
    if t == "Objc" or t == "GlbO":
        return _descriptor(r)
    if t == "VlLs":
        n = r.u32()
        out = []
        for _ in range(n):
            tt = r.take(4).decode("latin-1")
            out.append(_value(r, tt))
        return out
    if t == "tdta":
        n = r.u32()
        return r.take(n)
    if t == "type" or t == "GlbC":
        r.unicode()
        r.key()
        return None
    raise ValueError("unsupported descriptor type " + t)


def _descriptor(r):
    r.unicode()          # name
    r.key()              # class id
    n = r.u32()
    out = {}
    for _ in range(n):
        k = r.key()
        t = r.take(4).decode("latin-1")
        out[k] = _value(r, t)
    return out


# ----------------------------------------------------------------------
# EngineData (PostScript-like dictionary text)
# ----------------------------------------------------------------------

_TOK = re.compile(rb"\s*(<<|>>|\[|\]|/[^\s<>\[\]/()]*|\((?:\\.|[^\\()])*\)|[^\s<>\[\]/()]+)", re.S)


def _decode_ps_string(raw):
    body = raw[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        if c == 0x5C and i + 1 < len(body):
            n = body[i + 1]
            out.append({0x6E: 10, 0x72: 13, 0x74: 9}.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    b = bytes(out)
    if b[:2] == b"\xfe\xff":
        return b[2:].decode("utf-16-be", "replace")
    return b.decode("latin-1")


def parse_engine_data(data):
    toks = [m.group(1) for m in _TOK.finditer(data)]
    pos = 0

    def val():
        nonlocal pos
        t = toks[pos]
        pos += 1
        if t == b"<<":
            d = {}
            while toks[pos] != b">>":
                k = toks[pos][1:].decode("latin-1")
                pos += 1
                d[k] = val()
            pos += 1
            return d
        if t == b"[":
            a = []
            while toks[pos] != b"]":
                a.append(val())
            pos += 1
            return a
        if t.startswith(b"("):
            return _decode_ps_string(t)
        if t.startswith(b"/"):
            return t[1:].decode("latin-1")
        if t == b"true":
            return True
        if t == b"false":
            return False
        try:
            return float(t) if (b"." in t or b"e" in t.lower()) else int(t)
        except ValueError:
            return t.decode("latin-1")

    try:
        return val()
    except Exception:
        return {}


def _get(d, *path, default=None):
    cur = d
    for p in path:
        try:
            cur = cur[p]
        except (KeyError, IndexError, TypeError):
            return default
    return cur


def parse_tysh(block):
    """Returns dict(text, font_ps, size, color(r,g,b), align, tracking, leading, matrix, box, runs, mixed)
    or None."""
    try:
        r = _R(block)
        r.u16()                                  # version
        matrix = [r.f64() for _ in range(6)]
        r.u16()                                  # text version
        r.u32()                                  # descriptor version
        desc = _descriptor(r)
    except Exception:
        return None
    text = desc.get("Txt ")
    eng = parse_engine_data(desc["EngineData"]) if isinstance(desc.get("EngineData"), (bytes, bytearray)) else {}
    if not text:
        text = _get(eng, "EngineDict", "Editor", "Text", default="")
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x03", "\n")
    runs = _get(eng, "EngineDict", "StyleRun", "RunArray", default=[]) or []
    fonts = _get(eng, "ResourceDict", "FontSet", default=[]) or []
    style = _get(runs, 0, "StyleSheet", "StyleSheetData", default={}) or {}
    size = style.get("FontSize")
    font_ps = None
    fi = style.get("Font")
    if isinstance(fi, int) and 0 <= fi < len(fonts):
        font_ps = _get(fonts, fi, "Name")
    col = _get(style, "FillColor", "Values", default=None)
    color = (0, 0, 0)
    if isinstance(col, list) and len(col) >= 4:
        color = tuple(max(0, min(255, int(round(float(v) * 255)))) for v in col[1:4])
    elif isinstance(col, list) and len(col) == 2:     # grey
        g = max(0, min(255, int(round(float(col[1]) * 255))))
        color = (g, g, g)
    just = _get(eng, "EngineDict", "ParagraphRun", "RunArray", 0, "ParagraphSheet", "Properties", "Justification", default=0)
    align = {0: "left", 1: "right", 2: "center"}.get(just if isinstance(just, int) else 0, "left")
    lead = style.get("Leading") if not style.get("AutoLeading", True) else None
    distinct = set()
    for ru in runs:
        sd = _get(ru, "StyleSheet", "StyleSheetData", default={}) or {}
        distinct.add((sd.get("Font"), sd.get("FontSize"), str(_get(sd, "FillColor", "Values"))))
    yy = abs(matrix[3]) if matrix[3] else 1.0
    return {"text": text, "font_ps": font_ps, "size": (size * yy) if size else None, "color": color,
            "align": align, "tracking": style.get("Tracking", 0), "leading": (lead * yy) if lead else None,
            "matrix": matrix, "mixed": len(distinct) > 1}
