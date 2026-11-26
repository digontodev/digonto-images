"""Open and save: pictures (PNG JPG WebP BMP GIF ICO TGA SVG) and the layered .dimg project (.pimg from older versions still opens) (a zip with one PNG per layer)."""
import json
import os
import zipfile

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QImageWriter, QPainter

from . import arr
from .doc import Document, Layer

OPEN_FILTER = ("Pictures and projects (*.dimg *.pimg *.psd *.png *.jpg *.jpeg *.webp *.bmp *.gif *.ico *.tga *.svg);;"
               "Digonto Images project (*.dimg *.pimg);;Photoshop (*.psd);;All files (*)")
EXPORT_TYPES = [("PNG (lossless, optimised)", "png"), ("JPEG (smallest photos)", "jpg"), ("WebP (small, with transparency)", "webp"),
                ("PDF (one page)", "pdf"), ("Photoshop PSD (keeps layers)", "psd"), ("BMP", "bmp"), ("ICO (icon)", "ico")]
BLEND_TO_PSD = {"normal": "norm", "multiply": "mul ", "screen": "scrn", "overlay": "over", "darken": "dark", "lighten": "lite",
                "dodge": "div ", "burn": "idiv", "hard": "hLit", "soft": "sLit", "difference": "diff", "exclusion": "smud", "plus": "lddg"}
PSD_TO_BLEND = {v: k for k, v in BLEND_TO_PSD.items()}


def _png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def open_picture(path, svg_size=1600):
    ext = os.path.splitext(path)[1].lower()
    rd = QImageReader(path)
    rd.setAutoTransform(True)
    if ext == ".svg":
        sz = rd.size()
        if sz.isValid() and max(sz.width(), sz.height()) > 0:
            k = svg_size / max(sz.width(), sz.height())
            rd.setScaledSize(QSize(max(1, int(sz.width() * k)), max(1, int(sz.height() * k))))
    img = rd.read()
    if img.isNull():
        raise ValueError(rd.errorString() or "cannot read this picture")
    img = img.convertToFormat(arr.PM)
    d = Document(img.width(), img.height(), None)
    d.layers[0].image = img
    d.layers[0].name = "Background"
    d.path = path
    d.dirty = False
    return d


def open_any(path):
    low = path.lower()
    if low.endswith((".dimg", ".pimg")):
        return open_pimg(path)
    if low.endswith(".psd"):
        return open_psd(path)
    return open_picture(path)


def open_psd(path):
    import numpy as np
    from .psdio import read_psd
    pd = read_psd(path)
    d = Document(pd.width, pd.height, None)
    d.layers = []
    mixed = 0
    for l in pd.layers:
        a = np.asarray(l.image.convert("RGBA"))
        if a.size == 0:
            continue
        L = Layer(arr.from_array(a), l.name or "Layer", int(l.x), int(l.y))
        L.opacity = max(0.0, min(1.0, l.opacity / 255.0))
        L.visible = bool(l.visible)
        L.blend = PSD_TO_BLEND.get(l.blend, "normal")
        L.clip = bool(getattr(l, "clip", False))           # clipping mask from Photoshop
        if getattr(l, "mask", None) is not None:          # a real layer mask, editable like one made here
            L._mask = arr.from_mask(l.mask)
            L.mask_on = bool(l.mask_on)
        if getattr(l, "text", None) and (l.text.get("text") or "").strip():
            L.text = psd_text_spec(l.text, L.image)       # editable like a Digonto text layer; the pixels stay as Photoshop made them
            mx = l.text.get("matrix") or []
            if len(mx) == 6:
                L.text["psd_anchor"] = [mx[4] - L.x, mx[5] - L.y]
            if l.text.get("font_ps"):
                L.text["font_ps"] = l.text["font_ps"]
            if l.text.get("mixed"):
                mixed += 1
        d.layers.append(L)
    if not d.layers:
        a = np.asarray(pd.composite.convert("RGBA")) if pd.composite is not None else np.zeros((pd.height, pd.width, 4), np.uint8)
        d.layers.append(Layer(arr.from_array(a), "Background"))
    d.active = len(d.layers) - 1
    d.path = path
    d.dirty = False
    d.notes = list(getattr(pd, "warnings", []))
    if mixed:
        d.notes.append(f"{mixed} text layer(s) use more than one font, size or colour: after editing they get one style.")
    return d


def _font_family(ps_name):
    """Photoshop's font name (PostScript, e.g. 'Montserrat-BoldItalic', 'ArialMT') -> installed family, bold, italic"""
    import re
    from PySide6.QtGui import QFontDatabase
    ps = (ps_name or "").strip()
    fam, _, style = ps.partition("-")
    st = style.lower()
    bold = any(k in st for k in ("bold", "black", "heavy", "semibold", "extrabold"))
    italic = any(k in st for k in ("italic", "oblique"))
    fam = re.sub(r"(MT|PS|Std|Pro)$", "", fam) or fam
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", fam)
    fams = QFontDatabase.families()
    key = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    want = key(fam)
    for f in fams:
        if key(f) == want:
            return f, bold, italic
    for f in fams:
        if want and key(f).startswith(want):
            return f, bold, italic
    return spaced or "Sans Serif", bold, italic                  # not installed: the name as Photoshop wrote it


def psd_text_spec(t, image):
    """Photoshop text info -> Digonto text-layer spec (font, size, colour, alignment)"""
    from PySide6.QtGui import QColor
    fam, bold, italic = _font_family(t.get("font_ps"))
    size = t.get("size") or 24
    spec = dict(text=t["text"].rstrip("\n"), font=fam, size=max(4, int(round(size))), bold=bold, italic=italic,
                align=t.get("align", "left"), color=QColor(*t.get("color", (0, 0, 0))).name())
    # check the size against the real pixels: if they disagree a lot, trust the pixels (rare files store it differently)
    try:
        from .tools import render_text, ink_rect
        ir = ink_rect(image)
        nr = ink_rect(render_text(spec))
        if ir is not None and nr is not None and nr.height() > 0:
            ratio = ir.height() / nr.height()
            if ratio < 0.75 or ratio > 1.33:
                spec["size"] = max(4, int(round(spec["size"] * ratio)))
    except Exception:  # noqa: BLE001
        pass
    return spec


def save_psd(doc, path):
    import numpy as np
    from PIL import Image
    from .psdio import PsdDoc, PsdLayer, write_psd
    layers = []
    from PySide6.QtCore import QRect
    from . import ops, render
    for l in doc.layers:
        if l.adj:
            continue                      # adjustment layers are not written (they are inside the flattened preview)
        if l._mask is not None and not l.style:
            # a real layer mask: Photoshop and GIMP can keep editing it
            r = l.rect()
            img = Image.fromarray(arr.to_array(l._image), "RGBA")
            pl = PsdLayer(l.name, int(r.x()), int(r.y()), img, int(round(l.opacity * 255)), l.visible, BLEND_TO_PSD.get(l.blend, "norm"))
            pl.mask, pl.mask_on = arr.to_mask(l._mask), bool(l.mask_on)
        else:
            mar = render.style_margin(l.style)
            r = l.rect().adjusted(-mar, -mar, mar, mar)
            img = Image.fromarray(arr.to_array(ops._bake(l, r)), "RGBA")     # layer styles (and a mask with them) are baked in
            pl = PsdLayer(l.name, int(r.x()), int(r.y()), img, int(round(l.opacity * 255)), l.visible, BLEND_TO_PSD.get(l.blend, "norm"))
        pl.clip = bool(getattr(l, "clip", False))         # clipping mask stays a clipping mask in Photoshop
        if l.text and (l.text.get("text") or "").strip():
            try:                                           # Photoshop keeps the text editable
                from .psd_textw import anchor_for, build_tysh
                t = l.text
                if t.get("psd_anchor"):
                    anc = (l.x + t["psd_anchor"][0], l.y + t["psd_anchor"][1])
                else:
                    anc = anchor_for(t, l.x, l.y, l.image.width())
                pl.tysh = build_tysh(t, anc, (t.get("font_ps"), t.get("font")))
            except Exception:  # noqa: BLE001 - a text that cannot be described is still saved as pixels
                pass
        layers.append(pl)
    comp = Image.fromarray(arr.to_array(doc.flat_image(None)), "RGBA")
    write_psd(PsdDoc(doc.w, doc.h, layers, comp), path)


def save_pdf(doc, path, dpi=300, background="#FFFFFF"):
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter
    w = QPdfWriter(path)
    w.setResolution(dpi)
    w.setPageSize(QPageSize(QSizeF(doc.w * 25.4 / dpi, doc.h * 25.4 / dpi), QPageSize.Millimeter))
    w.setPageMargins(QMarginsF(0, 0, 0, 0))
    w.setTitle(os.path.splitext(os.path.basename(path))[0])
    p = QPainter(w)
    img = doc.flat_image(background)
    p.drawImage(p.viewport(), img)
    p.end()


def save_pimg(doc, path):
    meta = {"format": "digonto-images", "version": 1, "w": doc.w, "h": doc.h, "active": doc.active, "layers": []}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i, l in enumerate(doc.layers):
            name = f"layers/{i}.png"
            z.writestr(name, _png_bytes(l._image))
            entry = {"file": name, **l.meta()}
            if l._mask is not None:
                z.writestr(f"layers/{i}_mask.png", _png_bytes(l._mask))
                entry["mask_file"] = f"layers/{i}_mask.png"
            meta["layers"].append(entry)
        z.writestr("project.json", json.dumps(meta))
        z.writestr("preview.png", _png_bytes(doc.flat_image().scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)))      # 1 = keep aspect
    doc.path = path
    doc.dirty = False


def open_pimg(path):
    with zipfile.ZipFile(path) as z:
        meta = json.loads(z.read("project.json"))
        d = Document(meta["w"], meta["h"], None)
        d.layers = []
        for m in meta["layers"]:
            img = QImage.fromData(z.read(m["file"]), "PNG").convertToFormat(arr.PM)
            L = Layer(img)
            L.set_meta({k: v for k, v in m.items() if k not in ("file", "mask_file")})
            if m.get("mask_file"):
                L._mask = QImage.fromData(z.read(m["mask_file"]), "PNG").convertToFormat(arr.PM)
            d.layers.append(L)
    d.active = max(0, min(len(d.layers) - 1, meta.get("active", 0)))
    d.path = path
    d.dirty = False
    return d


def _opaque(img):
    import numpy as np
    return bool((arr.to_array(img)[..., 3] == 255).all())


def export_picture(doc, path, quality=92, background="#FFFFFF"):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext == "psd":
        return save_psd(doc, path)
    if ext == "pdf":
        return save_pdf(doc, path, background=background)
    flat = doc.flat_image(background if ext in ("jpg", "jpeg", "bmp") else None)
    if ext == "ico":
        flat = flat.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation) if max(flat.width(), flat.height()) > 256 else flat
    w = QImageWriter(path)
    if ext in ("jpg", "jpeg", "webp"):
        w.setQuality(int(quality))
        w.setOptimizedWrite(True)
        if ext in ("jpg", "jpeg"):
            w.setProgressiveScanWrite(True)
    if ext == "png":
        w.setQuality(0)                          # 0 = smallest file (best compression), still lossless
        w.setOptimizedWrite(True)
        out = flat.convertToFormat(QImage.Format_RGB888 if _opaque(flat) else QImage.Format_ARGB32)   # no alpha channel when nothing is transparent
    elif ext in ("jpg", "jpeg", "bmp"):
        out = flat.convertToFormat(QImage.Format_RGB32)
    else:
        out = flat.convertToFormat(QImage.Format_ARGB32)
    if not w.write(out):
        raise ValueError(w.errorString())
