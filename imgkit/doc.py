"""The document: layers, selection, undo history and the merged picture."""
import copy

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from . import arr
from .select import Selection

BLEND = [("normal", "Normal"), ("multiply", "Multiply"), ("screen", "Screen"), ("overlay", "Overlay"), ("darken", "Darken"),
         ("lighten", "Lighten"), ("dodge", "Color dodge"), ("burn", "Color burn"), ("hard", "Hard light"), ("soft", "Soft light"),
         ("difference", "Difference"), ("exclusion", "Exclusion"), ("plus", "Add")]
_MODES = {
    "normal": QPainter.CompositionMode_SourceOver, "multiply": QPainter.CompositionMode_Multiply, "screen": QPainter.CompositionMode_Screen,
    "overlay": QPainter.CompositionMode_Overlay, "darken": QPainter.CompositionMode_Darken, "lighten": QPainter.CompositionMode_Lighten,
    "dodge": QPainter.CompositionMode_ColorDodge, "burn": QPainter.CompositionMode_ColorBurn, "hard": QPainter.CompositionMode_HardLight,
    "soft": QPainter.CompositionMode_SoftLight, "difference": QPainter.CompositionMode_Difference,
    "exclusion": QPainter.CompositionMode_Exclusion, "plus": QPainter.CompositionMode_Plus,
}
META = ("name", "x", "y", "opacity", "blend", "visible", "locked", "text", "style", "adj", "mask_on", "clip",
        "is_group", "gid", "parent", "collapsed", "smart")


class Layer:
    def __init__(self, image, name="Layer", x=0, y=0):
        self._image = image
        self._mask = None                    # layer mask: a grey picture, white shows the layer, black hides it (same size as the layer)
        self.edit_mask = False               # True: brush, eraser, fill... paint on the mask instead of the picture
        self.mask_on = True
        self.style = None                    # layer styles (drop shadow, stroke, glow, colour overlay) - see render.py
        self.adj = None                      # adjustment layer: dict(kind, params); it changes everything below it
        self.name, self.x, self.y = name, x, y
        self.opacity, self.blend, self.visible, self.locked = 1.0, "normal", True, False
        self.clip = False                    # clipping mask: only show where the layer below has pixels (Ctrl+Alt+G)
        self.text = None                     # dict for a text layer (see tools.render_text), else None
        # layer groups (as in Photoshop): a group is a header layer just above its members (no pixels of its own)
        self.is_group, self.gid, self.parent, self.collapsed = False, None, None, False
        # smart object (as in Photoshop): the original pixels are kept (_smart_src) and every resize / rotate is made
        # from them, so nothing is lost. smart = dict(sx, sy, ang) or None
        self.smart, self._smart_src = None, None

    # while the mask is being edited every tool sees the mask as "the layer picture", so all tools work on masks
    @property
    def image(self):
        return self._mask if (self.edit_mask and self._mask is not None) else self._image

    @image.setter
    def image(self, v):
        if self.edit_mask and self._mask is not None:
            self._mask = v
        else:
            self._image = v

    @property
    def mask(self):
        return self._mask

    def map_images(self, fn):
        """apply a geometry change (crop, scale, rotate...) to the picture and to its mask together"""
        self.smart = None                    # the picture changed: it is a normal layer from now on
        self._image = fn(self._image)
        if self._mask is not None:
            self._mask = fn(self._mask)

    def rect(self):
        return QRect(self.x, self.y, self._image.width(), self._image.height())

    def meta(self):
        return {k: copy.deepcopy(getattr(self, k)) for k in META}

    def set_meta(self, m):
        for k, v in m.items():
            setattr(self, k, copy.deepcopy(v))

    @staticmethod
    def _small(img, size):
        """fast thumbnail: a quick coarse reduction first, then a smooth one (smooth scaling of a 12 MP picture is slow)"""
        if max(img.width(), img.height()) > size * 6:
            img = img.scaled(size * 4, size * 4, Qt.KeepAspectRatio, Qt.FastTransformation)
        return img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def thumb(self, size=40):
        return self._small(self._image, size)

    def mask_thumb(self, size=40):
        return self._small(self._mask, size) if self._mask is not None else None


def _shifted(l, dx, dy):
    """the same layer, moved (for drawing a group into a part-picture)"""
    c = copy.copy(l)
    c.x, c.y = l.x + dx, l.y + dy
    return c


class _Edit:
    def __init__(self, doc, label, layers, whole, pixels=True):
        self.doc, self.label, self.layers, self.whole, self.pixels = doc, label, layers, whole, pixels

    def __enter__(self):
        self.doc._push(self.label, self.layers, self.whole)
        return self

    def __exit__(self, *a):
        self.doc.tidy_groups()
        self.doc.changed(None if self.pixels else QRect())
        return False


class Document:
    LIMIT = 40

    def __init__(self, w, h, background=None):
        self.w, self.h = int(w), int(h)
        self.layers = []
        self.active = 0
        self.selection = None
        self.path = ""
        self.dirty = False
        self.history, self.pos = [], 0         # entries: dict(label, before, after)
        self.listeners = []
        self._merged = None
        self._dirty_rect = None
        if background is not None:
            self.layers.append(Layer(arr.new_image(w, h, background), "Background"))
        else:
            self.layers.append(Layer(arr.new_image(w, h), "Layer 1"))

    # ---- listeners
    def on_change(self, fn):
        self.listeners.append(fn)

    def changed(self, rect=None):
        """call after any change; rect = changed part of the picture (None = everything)"""
        self.dirty = True
        self.last_rect = QRect(rect) if rect is not None else None      # lets the view repaint only what changed
        self.invalidate(rect)
        for fn in list(self.listeners):
            fn()

    def invalidate(self, rect=None):
        if rect is None:
            self._dirty_rect = QRect(0, 0, self.w, self.h)
        else:
            r = QRect(rect).intersected(QRect(0, 0, self.w, self.h))
            self._dirty_rect = r if self._dirty_rect is None else self._dirty_rect.united(r)
        if self._merged is None or self._merged.size() != self.size():
            self._merged = None
            self._dirty_rect = QRect(0, 0, self.w, self.h)

    def size(self):
        from PySide6.QtCore import QSize
        return QSize(self.w, self.h)

    # ---- layers
    def layer(self):
        return self.layers[self.active] if self.layers else None

    def set_active(self, i):
        self.active = max(0, min(len(self.layers) - 1, i))

    def add_layer(self, image=None, name=None, index=None, x=0, y=0):
        img = image if image is not None else arr.new_image(self.w, self.h)
        L = Layer(img, name or f"Layer {len(self.layers) + 1}", x, y)
        i = self.active + 1 if index is None else index
        cur = self.layers[self.active] if index is None and 0 <= self.active < len(self.layers) else None
        if cur is not None and cur.is_group:             # a group is selected: the new layer goes in on top of it
            L.parent, i = cur.gid, self.active
        elif cur is not None and cur.parent:             # a layer in a group: the new layer joins that group
            L.parent = cur.parent
        self.layers.insert(i, L)
        self.active = i
        return L

    def tidy_groups(self):
        """members of a group always sit right below it, in their order (after any change to the layer list)"""
        heads = {l.gid for l in self.layers if l.is_group}
        if not heads and not any(l.parent for l in self.layers):
            return
        act = self.layers[self.active] if 0 <= self.active < len(self.layers) else None
        for l in self.layers:
            if l.parent and l.parent not in heads:
                l.parent = None
        out = []
        for l in self.layers:
            if l.parent and not l.is_group:
                continue
            if l.is_group:
                out.extend(m for m in self.layers if m.parent == l.gid and not m.is_group)
            out.append(l)
        if [id(x) for x in out] != [id(x) for x in self.layers]:
            self.layers[:] = out
            if act in out:
                self.active = out.index(act)

    # ---- history
    def _snapshot(self):
        """layer images are shared, never copied: a layer that is about to change gets a fresh live image in _push,
        so a snapshot's image is never modified afterwards"""
        return {"w": self.w, "h": self.h, "active": self.active,
                "sel": self.selection.copy() if self.selection is not None else None,
                "layers": [(l, l.meta(), l._image, l._mask) for l in self.layers]}

    def _restore(self, st):
        self.w, self.h, self.active = st["w"], st["h"], st["active"]
        self.selection = st["sel"].copy() if st["sel"] is not None else None
        self.layers = []
        for l, m, im, mk in st["layers"]:
            l.set_meta(m)
            l._image, l._mask = im, mk
            if mk is None:
                l.edit_mask = False
            self.layers.append(l)
        self._merged = None

    def edit(self, label, layers=None, whole=False, pixels=True):
        """with doc.edit('Brush', [layer]): ...   - remembers the layers before the change (for undo)"""
        return _Edit(self, label, layers if layers is not None else [], whole, pixels)

    def _push(self, label, layers, whole):
        del self.history[self.pos:]
        before = self._snapshot()
        if not whole and label != "Free transform":
            for l in layers or []:
                l.smart = None               # painting or a filter on a smart object turns it into a normal layer (rasterize)
        for l in (self.layers if whole else layers):
            l._image = l._image.copy()
            if l._mask is not None:
                l._mask = l._mask.copy()
        size = sum(l._image.sizeInBytes() + (l._mask.sizeInBytes() if l._mask is not None else 0) for l in (self.layers if whole else layers))
        self.history.append({"label": label, "before": before, "after": None, "bytes": size})
        self.pos = len(self.history)
        # keep at most 40 steps and about 700 MB of copies, so big pictures do not make the computer swap
        while len(self.history) > 1 and (len(self.history) > self.LIMIT or sum(e.get("bytes", 0) for e in self.history) > 700_000_000):
            self.history.pop(0)
            self.pos -= 1

    def can_undo(self):
        return self.pos > 0

    def can_redo(self):
        return self.pos < len(self.history)

    def undo(self):
        if not self.can_undo():
            return
        e = self.history[self.pos - 1]
        e["after"] = self._snapshot()
        self.pos -= 1
        self._restore(e["before"])
        self.changed()

    def redo(self):
        if not self.can_redo():
            return
        e = self.history[self.pos]
        self.pos += 1
        self._restore(e["after"])
        self.changed()

    def goto(self, index):
        """jump in the history (0 = start)"""
        while self.pos > index and self.can_undo():
            self.undo()
        while self.pos < index and self.can_redo():
            self.redo()

    # ---- merged picture
    def merged(self, rect=None):
        """the whole picture with transparency (premultiplied RGBA). Only the changed part is redrawn."""
        if self._merged is None or self._merged.size() != self.size():
            self._merged = arr.new_image(self.w, self.h)
            self._dirty_rect = QRect(0, 0, self.w, self.h)
        if self._dirty_rect is not None and not self._dirty_rect.isEmpty():
            self._draw(self._merged, self._dirty_rect)
            self._dirty_rect = None
        return self._merged

    def _draw(self, target, rect):
        p = QPainter(target)
        p.setClipRect(rect)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(rect, Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.end()
        self.composite(target, self.layers, rect)

    def composite(self, target, layers, rect, gid=None):
        """draw layers (bottom first) into target inside rect. Groups: members are drawn together and the group's
        opacity and blend mode are applied to them as one (normal + 100 % lets them mix with what is below)."""
        from . import render
        base, alpha = None, None
        i, n = 0, len(layers)
        while i < n:
            l = layers[i]
            if l.parent and l.parent != gid:
                j = i
                while j < n and layers[j].parent == l.parent:
                    j += 1
                head = layers[j] if j < n and layers[j].is_group and layers[j].gid == l.parent else None
                members = layers[i:j]
                if head is None:                         # members without their group: draw them normally
                    self.composite(target, members, rect, l.parent)
                elif head.visible and not getattr(head, "_hide", False):
                    if head.blend == "normal" and head.opacity >= 0.999:
                        self.composite(target, members, rect, l.parent)
                    else:
                        tmp = arr.new_image(rect.width(), rect.height())
                        shifted = [_shifted(m, -rect.x(), -rect.y()) for m in members]
                        self.composite(tmp, shifted, QRect(0, 0, rect.width(), rect.height()), l.parent)
                        q = QPainter(target)
                        q.setClipRect(rect)
                        q.setOpacity(head.opacity)
                        q.setCompositionMode(_MODES.get(head.blend, QPainter.CompositionMode_SourceOver))
                        q.drawImage(rect.x(), rect.y(), tmp)
                        q.end()
                base, alpha = None, None
                i = j + 1 if head is not None else j
                continue
            if l.is_group:                               # an empty group
                i += 1
                continue
            i += 1
            shown = l.visible and not getattr(l, "_hide", False)
            if not l.clip:
                base, alpha = (l if shown else None), None
                if shown:
                    render.draw_layer(target, l, rect, _MODES)
                continue
            # clipping mask: shown only where the base layer (the first normal layer below) has pixels
            if l is layers[0]:                          # nothing below: drawn normally
                if shown:
                    render.draw_layer(target, l, rect, _MODES)
                continue
            if not shown or base is None or base.adj:
                continue
            if alpha is None:
                alpha = render.base_alpha(base, rect)
            render.draw_layer(target, l, rect, _MODES, clip_alpha=alpha)

    def flat_image(self, background=None):
        """for saving: merged, optionally on a solid background"""
        out = arr.new_image(self.w, self.h, background)
        p = QPainter(out)
        p.drawImage(0, 0, self.merged())
        p.end()
        return out

    def sample(self, x, y, merged=True):
        im = self.merged() if merged else self.layer().image
        if merged:
            ox, oy = 0, 0
        else:
            ox, oy = self.layer().x, self.layer().y
        px, py = int(x) - ox, int(y) - oy
        if 0 <= px < im.width() and 0 <= py < im.height():
            return im.pixelColor(px, py)
        return QColor(0, 0, 0, 0)

    # ---- selection
    def set_selection(self, sel):
        self.selection = sel if (sel is not None and not sel.empty()) else None

    def sel_mask(self):
        return self.selection.mask if self.selection is not None else None
