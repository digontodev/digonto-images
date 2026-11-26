"""Whole-picture and layer operations. Every one is a single undo step."""
import copy

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform

from . import arr
from .doc import Layer


def _smooth(flag=True):
    return Qt.SmoothTransformation if flag else Qt.FastTransformation


def crop(doc, rect):
    rect = QRect(rect).intersected(QRect(0, 0, doc.w, doc.h))
    if rect.width() < 1 or rect.height() < 1:
        return
    with doc.edit("Crop", whole=True):
        for l in doc.layers:
            inter = l.rect().intersected(rect)
            if inter.isEmpty():
                l._image, l._mask, l.x, l.y = arr.new_image(1, 1), None, 0, 0
                l.edit_mask = False
                continue
            l.map_images(lambda im, r=inter.translated(-l.x, -l.y): im.copy(r))
            l.x, l.y = inter.x() - rect.x(), inter.y() - rect.y()
        sel = doc.selection
        doc.w, doc.h = rect.width(), rect.height()
        doc.selection = sel.resized(doc.w, doc.h, -rect.x(), -rect.y()) if sel is not None else None
        if doc.selection is not None and doc.selection.empty():
            doc.selection = None


def resize(doc, w, h, smooth=True):
    w, h = max(1, int(w)), max(1, int(h))
    kx, ky = w / doc.w, h / doc.h
    with doc.edit("Image size", whole=True):
        for l in doc.layers:
            nw, nh = max(1, round(l._image.width() * kx)), max(1, round(l._image.height() * ky))
            l.map_images(lambda im, nw=nw, nh=nh: im.scaled(nw, nh, Qt.IgnoreAspectRatio, _smooth(smooth)).convertToFormat(arr.PM))
            l.x, l.y = round(l.x * kx), round(l.y * ky)
        doc.w, doc.h, doc.selection = w, h, None


def canvas_size(doc, w, h, ax=0.5, ay=0.5):
    w, h = max(1, int(w)), max(1, int(h))
    dx, dy = int(round((w - doc.w) * ax)), int(round((h - doc.h) * ay))
    with doc.edit("Canvas size", whole=True):
        for l in doc.layers:
            l.x += dx
            l.y += dy
        sel = doc.selection
        doc.w, doc.h = w, h
        doc.selection = sel.resized(w, h, dx, dy) if sel is not None else None


def rotate90(doc, clockwise=True):
    W, H = doc.w, doc.h
    t = QTransform().rotate(90 if clockwise else -90)
    with doc.edit("Rotate 90°", whole=True):
        for l in doc.layers:
            w, h = l._image.width(), l._image.height()
            l.map_images(lambda im: im.transformed(t).convertToFormat(arr.PM))
            if clockwise:
                l.x, l.y = H - (l.y + h), l.x
            else:
                l.x, l.y = l.y, W - (l.x + w)
        doc.w, doc.h, doc.selection = H, W, None


def flip(doc, horizontal=True):
    with doc.edit("Flip", whole=True):
        for l in doc.layers:
            w, h = l.image.width(), l.image.height()
            l.map_images(lambda im: im.mirrored(horizontal, not horizontal))
            if horizontal:
                l.x = doc.w - (l.x + w)
            else:
                l.y = doc.h - (l.y + h)
        doc.selection = None


def flip_layer(doc, horizontal=True):
    l = doc.layer()
    with doc.edit("Flip layer", [l]):
        l.map_images(lambda im: im.mirrored(horizontal, not horizontal))


def transform_layer(doc, scale=100.0, angle=0.0, sx=None, sy=None):
    l = doc.layer()
    if l is None:
        return
    kx = (sx if sx is not None else scale) / 100.0
    ky = (sy if sy is not None else scale) / 100.0
    cx, cy = l.x + l._image.width() / 2.0, l.y + l._image.height() / 2.0
    t = QTransform().rotate(angle).scale(kx, ky)
    with doc.edit("Transform layer", [l]):
        l.map_images(lambda im: im.transformed(t, Qt.SmoothTransformation).convertToFormat(arr.PM))
        l.x, l.y = int(round(cx - l._image.width() / 2.0)), int(round(cy - l._image.height() / 2.0))
        l.text = None


def duplicate_layer(doc):
    l = doc.layer()
    with doc.edit("Duplicate layer"):
        n = Layer(l._image.copy(), l.name + " copy", l.x, l.y)
        n.opacity, n.blend, n.visible = l.opacity, l.blend, l.visible
        n._mask = l._mask.copy() if l._mask is not None else None
        n.mask_on, n.style, n.adj, n.clip = l.mask_on, copy.deepcopy(l.style), copy.deepcopy(l.adj), l.clip
        n.text = dict(l.text) if l.text else None
        doc.layers.insert(doc.active + 1, n)
        doc.active += 1


def delete_layer(doc):
    if len(doc.layers) <= 1:
        return
    with doc.edit("Delete layer"):
        del doc.layers[doc.active]
        doc.active = max(0, min(doc.active, len(doc.layers) - 1))


def add_layer(doc, name=None):
    with doc.edit("New layer"):
        doc.add_layer(name=name)


def move_layer(doc, delta):
    i, j = doc.active, doc.active + delta
    if not (0 <= j < len(doc.layers)):
        return
    with doc.edit("Reorder layers"):
        doc.layers[i], doc.layers[j] = doc.layers[j], doc.layers[i]
        doc.active = j


def _proxy(l, dx, dy):
    n = Layer(l._image, l.name, l.x + dx, l.y + dy)
    n._mask, n.mask_on, n.style, n.adj = l._mask, l.mask_on, l.style, l.adj
    n.opacity, n.blend, n.visible = l.opacity, l.blend, l.visible
    return n


def merge_down(doc):
    from . import adjlayers, render
    from .doc import _MODES
    i = doc.active
    if i <= 0:
        return
    top, low = doc.layers[i], doc.layers[i - 1]
    if low.adj:
        return
    with doc.edit("Merge down", [low]):
        if top.adj:                                   # an adjustment layer is applied to the layer below it
            r = low.rect()
            out = arr.new_image(r.width(), r.height())
            p = QPainter(out)
            p.drawImage(0, 0, _bake(low, r))
            p.end()
            a = arr.to_array(out)
            res = adjlayers.apply(top.adj, a)
            k = np.full(a.shape[:2], top.opacity, np.float32)[..., None]
            if top._mask is not None and top.mask_on:
                k = k * render._region_array(top._mask, r, top.x, top.y)[..., :1]
            res = (a * (1 - k) + res * k).astype(np.uint8)
            res[..., 3] = a[..., 3]
            out = arr.from_array(res)
            low._image, low._mask, low.edit_mask, low.style, low.text = out, None, False, None, None
        else:
            r = low.rect().united(top.rect()) if top.visible else low.rect()
            mar = max(render.style_margin(low.style), render.style_margin(top.style)) if top.visible else render.style_margin(low.style)
            r = r.adjusted(-mar, -mar, mar, mar)
            out = arr.new_image(r.width(), r.height())
            whole = QRect(0, 0, r.width(), r.height())
            if low.visible:
                render.draw_layer(out, _proxy(low, -r.x(), -r.y()), whole, _MODES)
            if top.visible:
                alpha = render.base_alpha(_proxy(low, -r.x(), -r.y()), whole) if top.clip else None    # clipped: only inside the layer below
                render.draw_layer(out, _proxy(top, -r.x(), -r.y()), whole, _MODES, clip_alpha=alpha)
            low._image, low._mask, low.edit_mask, low.style, low.text = out, None, False, None, None
            low.x, low.y = r.x(), r.y()
        low.opacity, low.blend, low.mask_on = 1.0, "normal", True
        del doc.layers[i]
        doc.active = i - 1


def _bake(l, r):
    """the layer (mask and styles applied) as a picture covering the doc-space rectangle r"""
    from . import render
    from .doc import _MODES
    out = arr.new_image(r.width(), r.height())
    p = _proxy(l, -r.x(), -r.y())
    p.opacity, p.blend = 1.0, "normal"
    render.draw_layer(out, p, QRect(0, 0, r.width(), r.height()), _MODES)
    return out


def flatten(doc):
    if len(doc.layers) <= 1:
        return
    with doc.edit("Flatten", whole=True):
        img = doc.flat_image(None)
        base = Layer(img, "Background")
        doc.layers[:] = [base]
        doc.active = 0


def new_from_selection(doc, cut=False):
    """copy (or cut) the selected pixels of the active layer into a new layer"""
    l, sel = doc.layer(), doc.selection
    if l is None or sel is None:
        return False
    b = sel.bbox().intersected(l.rect())
    if b.isEmpty():
        return False
    m = sel.mask[b.y():b.y() + b.height(), b.x():b.x() + b.width()]
    a = arr.to_array(_bake(l, b))
    k = m.astype(np.float32) / 255.0
    a[..., 3] = (a[..., 3] * k).astype(np.uint8)
    with doc.edit("Layer via " + ("cut" if cut else "copy"), [l]):
        if cut:
            full = arr.to_array(l._image)
            lm = np.zeros((l._image.height(), l._image.width()), np.uint8)
            x0, y0 = max(0, l.x), max(0, l.y)
            x1, y1 = min(doc.w, l.x + lm.shape[1]), min(doc.h, l.y + lm.shape[0])
            lm[y0 - l.y:y1 - l.y, x0 - l.x:x1 - l.x] = sel.mask[y0:y1, x0:x1]
            full[..., 3] = (full[..., 3].astype(np.float32) * (1 - lm / 255.0)).astype(np.uint8)
            l._image = arr.from_array(full)
        n = Layer(arr.from_array(a), "Selection", b.x(), b.y())
        doc.layers.insert(doc.active + 1, n)
        doc.active += 1
    return True


def clear_selection_pixels(doc):
    l, sel = doc.layer(), doc.selection
    if l is None or sel is None or l.locked:
        return
    full = arr.to_array(l.image)
    lm = np.zeros(full.shape[:2], np.uint8)
    x0, y0 = max(0, l.x), max(0, l.y)
    x1, y1 = min(doc.w, l.x + lm.shape[1]), min(doc.h, l.y + lm.shape[0])
    if x1 <= x0 or y1 <= y0:
        return
    lm[y0 - l.y:y1 - l.y, x0 - l.x:x1 - l.x] = sel.mask[y0:y1, x0:x1]
    full[..., 3] = (full[..., 3].astype(np.float32) * (1 - lm / 255.0)).astype(np.uint8)
    with doc.edit("Clear", [l]):
        l.image = arr.from_array(full)


def masked(doc, l, a, res):
    """keep the change only inside the selection"""
    from . import adjust
    sel = doc.selection
    if sel is None:
        return res
    lm = np.zeros(a.shape[:2], np.uint8)
    x0, y0 = max(0, l.x), max(0, l.y)
    x1, y1 = min(doc.w, l.x + lm.shape[1]), min(doc.h, l.y + lm.shape[0])
    if x1 > x0 and y1 > y0:
        lm[y0 - l.y:y1 - l.y, x0 - l.x:x1 - l.x] = sel.mask[y0:y1, x0:x1]
    return adjust.blend_masked(a, res, lm)


def apply_array(doc, label, fn):
    """fn(rgba_uint8) -> rgba_uint8 on the active layer, through the selection"""
    l = doc.layer()
    if l is None or l.locked:
        return False
    a = arr.to_array(l.image)
    res = masked(doc, l, a, fn(a))
    with doc.edit(label, [l]):
        l.image = arr.from_array(res)
        l.text = None if l.text else l.text
    return True


def paste_image(doc, img, name="Pasted"):
    w, h = img.width(), img.height()
    with doc.edit("Paste"):
        n = Layer(img.convertToFormat(arr.PM), name, max(0, (doc.w - w) // 2), max(0, (doc.h - h) // 2))
        doc.layers.insert(doc.active + 1, n)
        doc.active += 1


def fill_layer(doc, color):
    l = doc.layer()
    if l is None or l.locked:
        return
    img = arr.new_image(l.image.width(), l.image.height(), color)
    with doc.edit("Fill layer", [l]):
        l.image = img


def resize_layer(doc, w, h):
    l = doc.layer()
    if l is None or l.locked:
        return
    with doc.edit("Resize layer", [l]):
        l.map_images(lambda im: im.scaled(max(1, int(w)), max(1, int(h)), Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(arr.PM))
        l.text = None


def move_layer_to(doc, x, y):
    l = doc.layer()
    if l is None or l.locked:
        return
    with doc.edit("Move layer", []):
        l.x, l.y = int(x), int(y)


def reorder_layers(doc, new_layers):
    active = doc.layers[doc.active]
    if [id(l) for l in new_layers] == [id(l) for l in doc.layers]:
        return
    with doc.edit("Reorder layers"):
        doc.layers[:] = new_layers
        doc.active = new_layers.index(active)


# ---------------------------------------------------------------- masks, styles, adjustment layers
def add_mask(doc, mode="reveal"):
    """mode: reveal (all visible), hide (all hidden), selection (selected part visible)"""
    l = doc.layer()
    if l is None or l.adj and False:
        return
    w, h = l._image.width(), l._image.height()
    if mode == "hide":
        m = np.zeros((h, w), np.uint8)
    elif mode == "selection" and doc.selection is not None:
        m = np.zeros((h, w), np.uint8)
        x0, y0 = max(0, l.x), max(0, l.y)
        x1, y1 = min(doc.w, l.x + w), min(doc.h, l.y + h)
        if x1 > x0 and y1 > y0:
            m[y0 - l.y:y1 - l.y, x0 - l.x:x1 - l.x] = doc.selection.mask[y0:y1, x0:x1]
    else:
        m = np.full((h, w), 255, np.uint8)
    img = _mask_image(m)
    with doc.edit("Add layer mask", [l]):
        l._mask, l.mask_on, l.edit_mask = img, True, True


def _mask_image(m):
    a = np.dstack([m, m, m, np.full_like(m, 255)])
    return arr.from_array(a, straight=False)


def mask_array(l):
    return arr.to_array(l._mask, straight=False)[..., 0]


def delete_mask(doc, apply=False):
    l = doc.layer()
    if l is None or l._mask is None:
        return
    with doc.edit("Apply layer mask" if apply else "Delete layer mask", [l]):
        if apply and not l.adj:
            a = arr.to_array(l._image)
            a[..., 3] = (a[..., 3].astype(np.float32) * mask_array(l) / 255.0).astype(np.uint8)
            l._image = arr.from_array(a)
        l._mask, l.edit_mask, l.mask_on = None, False, True


def invert_mask(doc):
    l = doc.layer()
    if l is None or l._mask is None:
        return
    with doc.edit("Invert mask", [l]):
        l._mask = _mask_image(255 - mask_array(l))


def toggle_mask(doc):
    l = doc.layer()
    if l is None or l._mask is None:
        return
    with doc.edit("Mask " + ("off" if l.mask_on else "on"), []):
        l.mask_on = not l.mask_on


def set_style(doc, style):
    l = doc.layer()
    if l is None:
        return
    with doc.edit("Layer style", []):
        l.style = copy.deepcopy(style)


def add_adjustment(doc, kind, params):
    from . import adjlayers
    name = adjlayers.KINDS[kind][0]
    with doc.edit("New adjustment layer"):
        n = Layer(arr.new_image(doc.w, doc.h), name, 0, 0)
        n.adj = {"kind": kind, "params": dict(params)}
        doc.layers.insert(doc.active + 1, n)
        doc.active += 1
        if doc.selection is not None:                       # like Photoshop: only the selected part is changed
            n._mask = _mask_image(doc.selection.mask.copy())
    return n


def set_adjustment(doc, layer, params, label="Adjustment"):
    with doc.edit(label, []):
        layer.adj = {"kind": layer.adj["kind"], "params": dict(params)}


def rotate_canvas(doc, angle, background=None):
    """straighten: rotate every layer by any angle around the picture centre (canvas keeps its size)"""
    cx, cy = doc.w / 2.0, doc.h / 2.0
    with doc.edit("Rotate " + f"{angle:g}°", whole=True):
        for l in doc.layers:
            w, h = l._image.width(), l._image.height()
            lcx, lcy = l.x + w / 2.0, l.y + h / 2.0
            t = QTransform().rotate(angle)
            nx = cx + (lcx - cx) * t.m11() + (lcy - cy) * t.m21()
            ny = cy + (lcx - cx) * t.m12() + (lcy - cy) * t.m22()
            l.map_images(lambda im: im.transformed(t, Qt.SmoothTransformation).convertToFormat(arr.PM))
            l.x, l.y = int(round(nx - l._image.width() / 2.0)), int(round(ny - l._image.height() / 2.0))
            if l._mask is not None:
                pass
        doc.selection = None


def stamp_visible(doc):
    """a new layer on top that holds a picture of everything you can see (the layers below stay as they are)"""
    img = doc.merged().copy()
    with doc.edit("Stamp visible"):
        n = Layer(img, "Stamp", 0, 0)
        doc.layers.append(n)
        doc.active = len(doc.layers) - 1


def merge_visible(doc):
    """merge all visible layers into one; hidden layers stay"""
    vis = [l for l in doc.layers if l.visible]
    if len(vis) < 2:
        return
    img = doc.merged().copy()
    first = doc.layers.index(vis[0])
    with doc.edit("Merge visible", whole=True):
        n = Layer(img, vis[0].name, 0, 0)
        keep = [l for l in doc.layers if not l.visible]
        pos = sum(1 for l in doc.layers[:first] if not l.visible)
        keep.insert(pos, n)
        doc.layers[:] = keep
        doc.active = keep.index(n)


def toggle_clip(doc):
    """clipping mask (Ctrl+Alt+G, as in Photoshop): the active layer only shows where the layer below has pixels"""
    i = doc.active
    l = doc.layer()
    if l is None or i <= 0:
        return False
    with doc.edit("Release clipping mask" if l.clip else "Create clipping mask", [l], pixels=False):
        l.clip = not l.clip
    return True


def duplicate_or_copy(doc):
    """Ctrl+J as in Photoshop: with a selection a new layer from it, without one a copy of the whole layer"""
    if doc.selection is not None and new_from_selection(doc, False):
        return
    duplicate_layer(doc)
