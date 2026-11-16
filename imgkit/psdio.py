"""Photoshop .psd reader and writer (own code, no libraries).

Reads:  8-bit and 16-bit RGB / grayscale / CMYK / indexed files, with layers
        (raw, RLE and ZIP compression), layer names, opacity, visibility, blend
        mode keys, simple layer masks. Folders are flattened. Photoshop text /
        shape / smart-object layers are loaded as their pixels.
Writes: 8-bit RGB with transparent layers, names, opacity, visibility.
        Layers are stored uncompressed (biggest files but readable everywhere).
        Digonto's own data (editable text properties) is stored in a private
        resource that Photoshop keeps/ignores, so text stays editable here.
"""
import json
import struct

from . import psd_text
import zlib

import numpy as np
from PIL import Image


class PsdError(Exception):
    pass


class PsdLayer:
    def __init__(self, name, x, y, image, opacity=255, visible=True, blend="norm", path=None, clip=False, text=None):
        self.path = list(path or [])   # names of the folders it sits in, outermost first
        self.clip = clip               # clipped to the layer below
        self.text = text               # dict from psd_text.parse_tysh() for Photoshop text layers
        self.mask = None               # layer mask: numpy uint8 (h, w) the size of the layer, 255 shows, 0 hides
        self.mask_on = True
        self.name = name
        self.x = x
        self.y = y
        self.image = image          # PIL RGBA, size = layer rectangle
        self.opacity = opacity      # 0..255
        self.visible = visible
        self.blend = blend          # 4-char key, e.g. 'norm', 'mul ', 'scrn'


class PsdDoc:
    def __init__(self, width, height, layers=None, composite=None, meta=None):
        self.width = width
        self.height = height
        self.layers = layers or []  # bottom -> top
        self.composite = composite  # PIL RGBA or None
        self.meta = meta or {}
        self.warnings = []          # things that could not be reproduced (effects, adjustment layers ...)


PRIVATE_RESOURCE_ID = 4000


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _unpackbits_row(buf, width_bytes):
    out = bytearray()
    i, n = 0, len(buf)
    while i < n and len(out) < width_bytes:
        c = buf[i]
        i += 1
        if c < 128:
            out += buf[i:i + c + 1]
            i += c + 1
        elif c > 128:
            out += buf[i:i + 1] * (257 - c)
            i += 1
    if len(out) < width_bytes:
        out += b"\x00" * (width_bytes - len(out))
    return bytes(out[:width_bytes])


def _decode_plane(comp, data, w, h, depth, offset=0, end=None):
    """Returns (uint8 array h x w, bytes consumed for RLE/raw)."""
    bpp = 2 if depth == 16 else 1
    if w <= 0 or h <= 0:
        return np.zeros((max(h, 0), max(w, 0)), np.uint8), 0
    if depth not in (8, 16):
        raise PsdError(f"{depth}-bit PSD files are not supported (use 8 or 16-bit).")
    if comp == 0:
        n = w * h * bpp
        arr = np.frombuffer(data, np.uint8, n, offset)
        used = n
    elif comp == 1:
        counts = struct.unpack_from(f">{h}H", data, offset)
        p = offset + 2 * h
        rows = []
        for c in counts:
            rows.append(_unpackbits_row(data[p:p + c], w * bpp))
            p += c
        arr = np.frombuffer(b"".join(rows), np.uint8)
        used = p - offset
    elif comp in (2, 3):
        raw = zlib.decompress(data[offset:end])
        arr = np.frombuffer(raw, np.uint8, w * h * bpp)
        if comp == 3:
            if bpp == 1:
                arr = np.cumsum(arr.reshape(h, w), axis=1, dtype=np.uint8).reshape(-1)
            else:
                a16 = arr.reshape(h, w, 2)
                v = (a16[:, :, 0].astype(np.uint16) << 8) | a16[:, :, 1]
                v = np.cumsum(v, axis=1, dtype=np.uint16)
                arr = np.stack([(v >> 8).astype(np.uint8), (v & 255).astype(np.uint8)], axis=2).reshape(-1)
        used = (end or len(data)) - offset
    else:
        raise PsdError(f"unknown PSD compression {comp}")
    plane = arr.reshape(h, w * bpp)
    if bpp == 2:
        plane = plane[:, 0::2]       # keep the high byte of each 16-bit sample
    return np.ascontiguousarray(plane), used


def _pascal(data, pos, pad):
    n = data[pos]
    s = data[pos + 1:pos + 1 + n]
    total = 1 + n
    if pad > 1 and total % pad:
        total += pad - total % pad
    try:
        return s.decode("mac_roman"), total
    except Exception:
        return s.decode("latin-1"), total


def _to_rgba(mode, planes, ctable):
    """planes: dict channel id -> uint8 array (all same shape). Returns uint8 (h, w, 4)."""
    any_plane = next(iter(planes.values()))
    h, w = any_plane.shape
    alpha = planes.get(-1)
    if mode == 3:
        rgb = [planes.get(i, np.zeros((h, w), np.uint8)) for i in range(3)]
    elif mode == 1:
        g = planes.get(0, np.zeros((h, w), np.uint8))
        rgb = [g, g, g]
    elif mode == 2:
        idx = planes.get(0, np.zeros((h, w), np.uint8))
        pal = np.frombuffer(ctable, np.uint8).reshape(3, 256) if ctable and len(ctable) >= 768 else np.zeros((3, 256), np.uint8)
        rgb = [pal[i][idx] for i in range(3)]
    elif mode == 4:
        c, m, y, k = (planes.get(i, np.full((h, w), 255, np.uint8)).astype(np.uint16) for i in range(4))
        # PSD stores CMYK inverted (255 = no ink)
        rgb = [((c * k) // 255).astype(np.uint8), ((m * k) // 255).astype(np.uint8), ((y * k) // 255).astype(np.uint8)]
    else:
        raise PsdError("This colour mode (Bitmap / Lab / Duotone / Multichannel) is not supported. "
                       "In Photoshop use Image > Mode > RGB Color and save again.")
    a = alpha if alpha is not None else np.full((h, w), 255, np.uint8)
    return np.dstack([rgb[0], rgb[1], rgb[2], a])


_ADJ_KEYS = {b'brit', b'levl', b'curv', b'expA', b'vibA', b'hue ', b'hue2', b'blnc', b'blwh', b'phfl',
             b'mixr', b'clrL', b'nvrt', b'post', b'thrs', b'grdm', b'selc', b'CgEd', b'CBrt'}
_BLENDS_OK = {"norm", "mul ", "scrn", "over", "dark", "lite", "diff"}


# ----------------------------------------------------------------------
# reader
# ----------------------------------------------------------------------

def read_psd(source):
    data = source if isinstance(source, (bytes, bytearray)) else open(source, "rb").read()
    if data[:4] != b"8BPS":
        raise PsdError("This is not a Photoshop (.psd) file.")
    ver = struct.unpack_from(">H", data, 4)[0]
    if ver == 2:
        raise PsdError("Large PSB files are not supported.")
    channels, height, width, depth, mode = struct.unpack_from(">HIIHH", data, 12)
    pos = 26
    cm_len = struct.unpack_from(">I", data, pos)[0]
    ctable = data[pos + 4:pos + 4 + cm_len]
    pos += 4 + cm_len
    # --- image resources
    res_len = struct.unpack_from(">I", data, pos)[0]
    rpos, rend = pos + 4, pos + 4 + res_len
    meta = {}
    while rpos + 12 <= rend:
        if data[rpos:rpos + 4] != b"8BIM":
            break
        rid = struct.unpack_from(">H", data, rpos + 4)[0]
        nlen = data[rpos + 6]
        npad = 1 + nlen
        if npad % 2:
            npad += 1
        sz = struct.unpack_from(">I", data, rpos + 6 + npad)[0]
        d0 = rpos + 6 + npad + 4
        if rid == PRIVATE_RESOURCE_ID:
            try:
                meta = json.loads(data[d0:d0 + sz].decode("utf-8"))
            except Exception:
                meta = {}
        rpos = d0 + sz + (sz % 2)
    pos = rend
    # --- layers
    lm_len = struct.unpack_from(">I", data, pos)[0]
    lm_start, lm_end = pos + 4, pos + 4 + lm_len
    layers = []
    warnings, effects, vmasks = [], [], []
    if lm_len:
        li_len = struct.unpack_from(">I", data, lm_start)[0]
        p = lm_start + 4
        if li_len:
            count = struct.unpack_from(">h", data, p)[0]
            p += 2
            n = abs(count)
            recs = []
            for _ in range(n):
                top, left, bottom, right, nch = struct.unpack_from(">iiiiH", data, p)
                p += 18
                chans = []
                for _c in range(nch):
                    cid, clen = struct.unpack_from(">hI", data, p)
                    p += 6
                    chans.append((cid, clen))
                blend = data[p + 4:p + 8].decode("latin-1")
                opacity, clip, flags = data[p + 8], data[p + 9], data[p + 10]
                extra_len = struct.unpack_from(">I", data, p + 12)[0]
                e0, e1 = p + 16, p + 16 + extra_len
                q = e0
                mlen = struct.unpack_from(">I", data, q)[0]
                mask = None
                if mlen >= 20:
                    mt, ml, mb, mr = struct.unpack_from(">iiii", data, q + 4)
                    mdef, mflags = data[q + 20], data[q + 21]
                    density = 255
                    if mflags & 16:                               # mask parameters: Photoshop's Density slider
                        pp = q + 22
                        if mlen >= 36 and any(c == -3 for c, _l in chans):
                            pp += 18                              # a "real user mask" header comes first
                        if pp + 1 < q + 4 + mlen:
                            pflags = data[pp]
                            if pflags & 1:
                                density = data[pp + 1]
                    mask = (mt, ml, mb, mr, mdef, mflags, density)
                q += 4 + mlen
                brl = struct.unpack_from(">I", data, q)[0]
                q += 4 + brl
                name, used = _pascal(data, q, 4)
                q += used
                section = 0
                tysh, extras = None, set()
                while q + 12 <= e1:
                    sig = data[q:q + 4]
                    if sig not in (b"8BIM", b"8B64"):
                        q += 1
                        continue
                    key = data[q + 4:q + 8]
                    blen = struct.unpack_from(">I", data, q + 8)[0]
                    d0 = q + 12
                    if key == b"luni" and blen >= 4:
                        cn = struct.unpack_from(">I", data, d0)[0]
                        try:
                            name = data[d0 + 4:d0 + 4 + 2 * cn].decode("utf-16-be").rstrip("\x00")
                        except Exception:
                            pass
                    elif key == b"lsct" and blen >= 4:
                        section = struct.unpack_from(">I", data, d0)[0]
                    elif key == b"TySh":
                        tysh = data[d0:d0 + blen]
                    else:
                        extras.add(bytes(key))
                    q = d0 + blen
                recs.append(dict(top=top, left=left, bottom=bottom, right=right, chans=chans, blend=blend,
                                 opacity=opacity, flags=flags, name=name, mask=mask, section=section,
                                 clip=bool(clip), tysh=tysh, extras=extras))
                p = e1
            # channel image data
            group_stack = []
            for rec in recs:
                planes, mask_plane = {}, None
                w, h = rec["right"] - rec["left"], rec["bottom"] - rec["top"]
                for cid, clen in rec["chans"]:
                    seg_start = p
                    p += clen
                    if clen < 2:
                        continue
                    comp = struct.unpack_from(">H", data, seg_start)[0]
                    if cid in (-2, -3):
                        if rec["mask"] and cid == -2:
                            mt, ml, mb, mr = rec["mask"][:4]
                            if mr > ml and mb > mt:
                                try:
                                    mask_plane, _ = _decode_plane(comp, data, mr - ml, mb - mt, depth, seg_start + 2, p)
                                except Exception:
                                    mask_plane = None
                        continue
                    if w > 0 and h > 0:
                        planes[cid], _ = _decode_plane(comp, data, w, h, depth, seg_start + 2, p)
                if rec["section"] == 3:
                    group_stack.append([])      # start (bottom) marker of a folder
                    continue
                if rec["section"] in (1, 2):    # the folder itself (top marker)
                    if group_stack:
                        members = group_stack.pop()
                        for m in members:
                            m.path.insert(0, rec["name"])
                            if rec["flags"] & 2:
                                m.visible = False
                            if rec["opacity"] < 255:
                                m.opacity = m.opacity * rec["opacity"] // 255
                        if group_stack:
                            group_stack[-1].extend(members)
                    continue
                if w <= 0 or h <= 0 or not planes:
                    if rec["extras"] & _ADJ_KEYS:
                        warnings.append(f"Adjustment layer '{rec['name']}' is not applied (colour/brightness adjustment).")
                    continue            # adjustment layers etc.
                try:
                    arr = _to_rgba(mode, planes, ctable)
                except PsdError:
                    raise
                lmask, lmask_on = None, True
                if mask_plane is not None and rec["mask"]:
                    mt, ml, mb, mr, mdef = rec["mask"][:5]
                    full = np.full((h, w), mdef, np.uint8)
                    y0, x0 = mt - rec["top"], ml - rec["left"]
                    ys0, xs0 = max(0, y0), max(0, x0)
                    ys1, xs1 = min(h, y0 + mask_plane.shape[0]), min(w, x0 + mask_plane.shape[1])
                    if ys1 > ys0 and xs1 > xs0:
                        full[ys0:ys1, xs0:xs1] = mask_plane[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0]
                    if rec["mask"][5] & 4:
                        full = 255 - full
                    dens = rec["mask"][6]
                    if dens < 255:                              # lower density: black hides less
                        full = (255 - (255 - full.astype(np.uint16)) * dens // 255).astype(np.uint8)
                    lmask, lmask_on = full, not (rec["mask"][5] & 2)     # a real layer mask (white shows, black hides)
                blend = rec["blend"] if rec["blend"] in _BLENDS_OK else "norm"
                tdat = None
                if rec["tysh"]:
                    tdat = psd_text.parse_tysh(rec["tysh"])
                lay = PsdLayer(rec["name"], rec["left"], rec["top"], Image.fromarray(arr, "RGBA"),
                               rec["opacity"], not (rec["flags"] & 2), blend, clip=rec["clip"], text=tdat)
                lay.mask, lay.mask_on = lmask, lmask_on
                if {b"lfx2", b"lrFX", b"lmfx"} & rec["extras"]:
                    effects.append(rec["name"])
                if {b"vmsk", b"vsms"} & rec["extras"]:
                    vmasks.append(rec["name"])
                layers.append(lay)
                if group_stack:
                    group_stack[-1].append(lay)
    # --- merged image
    comp_img = None
    pos = lm_end
    try:
        comp = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        h, w = height, width
        planes = {}
        if comp == 1:
            counts = struct.unpack_from(f">{h * channels}H", data, pos)
            q = pos + 2 * h * channels
            ci = 0
            for ch in range(channels):
                rows = []
                for _ in range(h):
                    c = counts[ci]
                    ci += 1
                    rows.append(_unpackbits_row(data[q:q + c], w * (2 if depth == 16 else 1)))
                    q += c
                arr = np.frombuffer(b"".join(rows), np.uint8).reshape(h, -1)
                planes[ch] = np.ascontiguousarray(arr[:, 0::2] if depth == 16 else arr)
        elif comp == 0:
            step = w * h * (2 if depth == 16 else 1)
            for ch in range(channels):
                arr = np.frombuffer(data, np.uint8, step, pos + ch * step).reshape(h, -1)
                planes[ch] = np.ascontiguousarray(arr[:, 0::2] if depth == 16 else arr)
        else:
            raw = zlib.decompress(data[pos:])
            step = w * h * (2 if depth == 16 else 1)
            for ch in range(channels):
                arr = np.frombuffer(raw, np.uint8, step, ch * step).reshape(h, -1)
                planes[ch] = np.ascontiguousarray(arr[:, 0::2] if depth == 16 else arr)
        want = {3: 3, 1: 1, 2: 1, 4: 4}.get(mode, 3)
        mapped = {i: planes[i] for i in range(min(want, channels))}
        if channels > want:
            mapped[-1] = planes[want]
        comp_img = Image.fromarray(_to_rgba(mode, mapped, ctable), "RGBA")
    except PsdError:
        raise
    except Exception:
        comp_img = None
    if effects:
        warnings.append(f"Layer effects (shadow, stroke, glow ...) are not drawn: {', '.join(effects[:6])}"
                        + (" ..." if len(effects) > 6 else ""))
    if vmasks:
        warnings.append(f"Vector masks are not applied on: {', '.join(vmasks[:6])}" + (" ..." if len(vmasks) > 6 else ""))
    doc = PsdDoc(width, height, layers, comp_img, meta)
    doc.warnings = warnings
    return doc


# ----------------------------------------------------------------------
# writer
# ----------------------------------------------------------------------

def _pascal_bytes(name, pad):
    b = name.encode("latin-1", "replace")[:255]
    out = bytes([len(b)]) + b
    while len(out) % pad:
        out += b"\x00"
    return out


def _resource(rid, payload):
    out = b"8BIM" + struct.pack(">H", rid) + b"\x00\x00" + struct.pack(">I", len(payload)) + payload
    if len(payload) % 2:
        out += b"\x00"
    return out


def write_psd(doc, path=None):
    """Writes a PSD. `doc.composite` (RGBA) is the flattened picture; layers bottom -> top."""
    w, h = doc.width, doc.height
    comp = doc.composite
    if comp is None:
        comp = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    comp = comp.convert("RGBA")
    ca = np.asarray(comp)
    has_alpha = bool((ca[:, :, 3] < 255).any())
    nch = 4 if has_alpha else 3
    out = bytearray()
    out += b"8BPS" + struct.pack(">H", 1) + b"\x00" * 6 + struct.pack(">HIIHH", nch, h, w, 8, 3)
    out += struct.pack(">I", 0)                                   # colour mode data
    res = _resource(1005, struct.pack(">IHHIHH", 72 << 16, 1, 1, 72 << 16, 1, 1))
    meta = dict(doc.meta or {})
    res += _resource(PRIVATE_RESOURCE_ID, json.dumps(meta, separators=(",", ":")).encode("utf-8"))
    out += struct.pack(">I", len(res)) + res

    recs, chan_blobs = bytearray(), bytearray()
    seq, cur = [], []
    for lay in doc.layers:
        lp = list(lay.path)
        k = 0
        while k < len(cur) and k < len(lp) and cur[k] == lp[k]:
            k += 1
        for name in reversed(cur[k:]):
            seq.append(("close", name))
        for name in lp[k:]:
            seq.append(("open", name))
        cur = lp
        seq.append(("layer", lay))
    for name in reversed(cur):
        seq.append(("close", name))

    def record(name, rect, planes, opacity, visible, blend, section, clip=False, tysh=None, mask=None, mask_on=True):
        nonlocal recs, chan_blobs
        top, left, bottom, right = rect
        cids = [-1, 0, 1, 2]
        if mask is not None:
            cids.append(-2)
            planes = list(planes) + [struct.pack(">H", 0) + np.ascontiguousarray(mask, np.uint8).tobytes()]
        recs += struct.pack(">iiiiH", top, left, bottom, right, len(cids))
        for cid, data in zip(cids, planes):
            recs += struct.pack(">hI", cid, len(data))
            chan_blobs += data
        recs += b"8BIM" + blend.encode("latin-1") + bytes([max(0, min(255, int(opacity))), 1 if clip else 0,
                                                            0 if visible else 2, 0])
        name_b = _pascal_bytes(name, 4)
        uni = name.encode("utf-16-be")
        luni = struct.pack(">I", len(name)) + uni
        if len(luni) % 2:
            luni += b"\x00"
        blocks = b"8BIM" + b"luni" + struct.pack(">I", len(luni)) + luni
        if section is not None:
            blocks += b"8BIM" + b"lsct" + struct.pack(">I", 4) + struct.pack(">I", section)
        if tysh:
            blocks += b"8BIM" + b"TySh" + struct.pack(">I", len(tysh)) + tysh
        if mask is not None:                                       # layer mask data: its rectangle = the layer, default white
            mdata = struct.pack(">iiii", top, left, bottom, right) + bytes([255, 0 if mask_on else 2]) + b"\x00\x00"
        else:
            mdata = b""
        extra = struct.pack(">I", len(mdata)) + mdata + struct.pack(">I", 0) + name_b + blocks
        recs += struct.pack(">I", len(extra)) + extra

    empty = [struct.pack(">H", 0)] * 4
    for kind, obj in seq:
        if kind == "open":
            record("</Layer group>", (0, 0, 0, 0), empty, 255, True, "norm", 3)
        elif kind == "close":
            record(obj, (0, 0, 0, 0), empty, 255, True, "norm", 1)
        else:
            lay = obj
            img = lay.image.convert("RGBA")
            lw, lh = img.size
            arr = np.asarray(img)
            planes = [struct.pack(">H", 0) + arr[:, :, c].tobytes() for c in (3, 0, 1, 2)]
            record(lay.name, (lay.y, lay.x, lay.y + lh, lay.x + lw), planes, lay.opacity, lay.visible,
                   lay.blend if lay.blend in _BLENDS_OK else "norm", None, lay.clip, getattr(lay, "tysh", None),
                   getattr(lay, "mask", None), getattr(lay, "mask_on", True))
    count = sum(1 for k, _o in seq)
    if has_alpha and count:
        count = -count
    li = struct.pack(">h", count) + bytes(recs) + bytes(chan_blobs)
    if len(li) % 2:
        li += b"\x00"
    if seq:
        lm = struct.pack(">I", len(li)) + li + struct.pack(">I", 0)
        out += struct.pack(">I", len(lm)) + lm
    else:
        out += struct.pack(">I", 0)
    out += struct.pack(">H", 0)                                   # merged image: raw
    chs = [ca[:, :, 0], ca[:, :, 1], ca[:, :, 2]] + ([ca[:, :, 3]] if has_alpha else [])
    for c in chs:
        out += np.ascontiguousarray(c).tobytes()
    data = bytes(out)
    if path:
        with open(path, "wb") as f:
            f.write(data)
    return data
