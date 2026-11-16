"""Writes Photoshop text layers (the 'TySh' block) so a saved .psd keeps its text editable in Photoshop.

The text engine data is built from psd_text_template.bin (Photoshop's own default text resources) with the
words, font, size, colour and alignment of the Digonto text layer put in. The layer pixels are written too,
so every program shows the text at once, and Photoshop can edit it.
"""
import copy
import os
import re
import struct

from .psd_text import parse_engine_data

_TEMPLATE = None


def _template():
    global _TEMPLATE
    if _TEMPLATE is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "psd_text_template.bin"), "rb") as f:
            _TEMPLATE = parse_engine_data(f.read())
    return copy.deepcopy(_TEMPLATE)


# ---------------------------------------------------------------- engine data text
def _num(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = f"{float(v):.5f}".rstrip("0")
    if s.endswith("."):
        s += "0"
    if s.startswith("0.") and s != "0.0":
        s = s[1:]
    elif s.startswith("-0."):
        s = "-" + s[2:]
    return s


def _str(s):
    raw = b"\xfe\xff" + s.encode("utf-16-be")
    out = bytearray(b"(")
    for c in raw:
        if c in (0x28, 0x29, 0x5C):
            out.append(0x5C)
        out.append(c)
    out.append(0x29)
    return bytes(out)


def _scalar(v):
    if isinstance(v, str):
        return _str(v)
    return _num(v).encode("ascii")


def _emit(v, ind):
    t = b"\t" * ind
    if isinstance(v, dict):
        out = t + b"<<\n"
        for k, x in v.items():
            key = t + b"\t/" + k.encode("latin-1")
            if isinstance(x, dict):
                out += key + b"\n" + _emit(x, ind + 1)
            elif isinstance(x, list) and any(isinstance(e, (dict, list)) for e in x):
                out += key + b" [\n"
                for e in x:
                    out += _emit(e, ind + 1)
                out += t + b"\t]\n"
            elif isinstance(x, list):
                out += key + b" [ " + b" ".join(_scalar(e) for e in x) + b" ]\n"
            else:
                out += key + b" " + _scalar(x) + b"\n"
        return out + t + b">>\n"
    if isinstance(v, list):
        return t + b"[ " + b" ".join(_scalar(e) for e in v) + b" ]\n"
    return t + _scalar(v) + b"\n"


def engine_bytes(d):
    return b"\n\n" + _emit(d, 0)


# ---------------------------------------------------------------- font name
def postscript_name(family, bold, italic, keep=None):
    """the PostScript name Photoshop looks for. keep = (name, family) from the opened .psd when the font is unchanged"""
    if keep and keep[0] and keep[1] == family:
        return keep[0], False
    try:                                              # the real name, when the system can tell it
        from PySide6.QtGui import QFont, QRawFont
        f = QFont(family)
        f.setBold(bold)
        f.setItalic(italic)
        raw = QRawFont.fromFont(f)
        tbl = raw.fontTable("name")
        name = _ps_from_name_table(bytes(tbl)) if tbl else None
        if name:
            styled = ("bold" in name.lower()) == bool(bold) and (("italic" in name.lower() or "oblique" in name.lower()) == bool(italic))
            return name, not styled                   # faux style only when the font file has no such style
    except Exception:  # noqa: BLE001
        pass
    base = re.sub(r"\s+", "", family) or "ArialMT"
    style = ("Bold" if bold else "") + ("Italic" if italic else "")
    return base + "-" + (style or "Regular"), False


def _ps_from_name_table(t):
    """name ID 6 (PostScript name) from a TrueType/OpenType 'name' table"""
    if len(t) < 6:
        return None
    count, off = struct.unpack(">HH", t[2:6])
    for i in range(count):
        p = 6 + i * 12
        if p + 12 > len(t):
            break
        pid, eid, lid, nid, ln, o = struct.unpack(">HHHHHH", t[p:p + 12])
        if nid != 6:
            continue
        s = t[off + o:off + o + ln]
        try:
            return s.decode("utf-16-be") if pid in (0, 3) else s.decode("latin-1")
        except UnicodeDecodeError:
            continue
    return None


# ---------------------------------------------------------------- descriptor
def _uni(s):
    return struct.pack(">I", len(s) + 1) + (s + "\x00").encode("utf-16-be") if s else struct.pack(">I", 1) + b"\x00\x00"


def _key(k):
    b = k.encode("latin-1")
    return struct.pack(">I", 0) + b if len(b) == 4 else struct.pack(">I", len(b)) + b


def _desc(cls, items):
    out = _uni("") + _key(cls) + struct.pack(">I", len(items))
    for k, typ, val in items:
        out += _key(k) + typ.encode("latin-1")
        if typ == "TEXT":
            out += struct.pack(">I", len(val)) + val.encode("utf-16-be")
        elif typ == "enum":
            out += _key(val[0]) + _key(val[1])
        elif typ == "long":
            out += struct.pack(">i", val)
        elif typ == "doub":
            out += struct.pack(">d", val)
        elif typ == "tdta":
            out += struct.pack(">I", len(val)) + val
    return out


# ---------------------------------------------------------------- the block
def build_tysh(spec, anchor, keep_font=None):
    """spec: Digonto text spec (text, font, size, bold, italic, align, color). anchor: (x, y) of the first baseline
    in document pixels (left / centre / right point by alignment). -> bytes of the TySh block"""
    from PySide6.QtGui import QColor
    text = (spec.get("text") or " ").replace("\r\n", "\n").replace("\r", "\n")
    paras = text.split("\n")
    body = "\r".join(paras)
    size = float(spec.get("size", 24))
    col = QColor(spec.get("color", "#000000"))
    just = {"left": 0, "right": 1, "center": 2}.get(spec.get("align", "left"), 0)
    ps, faux = postscript_name(spec.get("font", "Arial"), bool(spec.get("bold")), bool(spec.get("italic")), keep_font)

    d = _template()
    ed = d["EngineDict"]
    ed["Editor"]["Text"] = body + "\r"
    para_tpl = ed["ParagraphRun"]["RunArray"][0]
    runs, lens = [], []
    for k, p in enumerate(paras):
        r = copy.deepcopy(para_tpl)
        r["ParagraphSheet"]["Properties"]["Justification"] = just
        runs.append(r)
        lens.append(len(p) + 1)
    ed["ParagraphRun"]["RunArray"] = runs
    ed["ParagraphRun"]["RunLengthArray"] = lens
    st = ed["StyleRun"]["RunArray"][0]["StyleSheet"]["StyleSheetData"]
    st.update({"Font": 0, "FontSize": size, "FauxBold": bool(spec.get("bold")) and faux,
               "FauxItalic": bool(spec.get("italic")) and faux, "AutoLeading": True,
               "FillColor": {"Type": 1, "Values": [1.0, col.redF(), col.greenF(), col.blueF()]}})
    ed["StyleRun"]["RunArray"] = [ed["StyleRun"]["RunArray"][0]]
    ed["StyleRun"]["RunLengthArray"] = [len(body) + 1]
    fonts = [{"Name": ps, "Script": 0, "FontType": 1, "Synthetic": 0},
             {"Name": "AdobeInvisFont", "Script": 0, "FontType": 0, "Synthetic": 0}]
    for res in ("ResourceDict", "DocumentResources"):
        if res in d:
            d[res]["FontSet"] = copy.deepcopy(fonts)
            for ss in d[res].get("StyleSheetSet", []):
                ss.get("StyleSheetData", {})["Font"] = 0
    eng = engine_bytes(d)

    out = struct.pack(">H", 1) + struct.pack(">6d", 1.0, 0.0, 0.0, 1.0, float(anchor[0]), float(anchor[1]))
    out += struct.pack(">HI", 50, 16)
    out += _desc("TxLr", [("Txt ", "TEXT", body + "\x00"),
                          ("textGridding", "enum", ("textGridding", "None")),
                          ("Ornt", "enum", ("Ornt", "Hrzn")),
                          ("AntA", "enum", ("Annt", "AnSm")),
                          ("TextIndex", "long", 0),
                          ("EngineData", "tdta", eng)])
    out += struct.pack(">HI", 1, 16)
    out += _desc("warp", [("warpStyle", "enum", ("warpStyle", "warpNone")),
                          ("warpValue", "doub", 0.0),
                          ("warpPerspective", "doub", 0.0),
                          ("warpPerspectiveOther", "doub", 0.0),
                          ("warpRotate", "enum", ("Ornt", "Hrzn"))])
    out += struct.pack(">4i", 0, 0, 0, 0)
    if len(out) % 2:
        out += b"\x00"
    return out


def anchor_for(spec, layer_x, layer_y, image_w):
    """where Photoshop's text point is, for a picture made by tools.render_text (pad 6, first baseline at pad + ascent)"""
    from PySide6.QtGui import QFont, QFontMetricsF
    f = QFont(spec.get("font", "Sans Serif"))
    f.setPixelSize(max(4, int(spec.get("size", 48))))
    f.setBold(bool(spec.get("bold")))
    f.setItalic(bool(spec.get("italic")))
    pad = 6
    al = spec.get("align", "left")
    x = pad if al == "left" else (image_w / 2.0 if al == "center" else image_w - pad)
    return layer_x + x, layer_y + pad + QFontMetricsF(f).ascent()
