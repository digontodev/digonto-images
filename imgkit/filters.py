"""Filters on RGBA uint8 arrays (straight alpha). Blurs work on premultiplied colors so edges stay clean."""
import numpy as np

from .select import _box, blur as _blur


def premul(a):
    f = a.astype(np.float32)
    f[..., :3] *= f[..., 3:4] / 255.0
    return f


def unpremul(f):
    out = f.copy()
    al = out[..., 3:4]
    out[..., :3] = np.where(al > 0, out[..., :3] * 255.0 / np.maximum(al, 1e-3), 0)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def gaussian_blur(a, radius):
    if radius <= 0:
        return a
    return unpremul(_blur(premul(a), radius))


def box_blur(a, radius):
    r = int(radius)
    if r <= 0:
        return a
    f = premul(a)
    return unpremul(_box(_box(f, r, 0), r, 1).astype(np.float32))


def motion_blur(a, length, angle=0):
    n = max(1, int(length))
    f = premul(a)
    h, w = f.shape[:2]
    th = np.deg2rad(angle)
    dx, dy = np.cos(th), -np.sin(th)
    acc = np.zeros_like(f)
    ys, xs = np.mgrid[0:h, 0:w]
    steps = max(2, min(n, 60))
    for i in range(steps):
        t = (i / (steps - 1) - 0.5) * n
        sx = np.clip(np.round(xs + dx * t).astype(np.int32), 0, w - 1)
        sy = np.clip(np.round(ys + dy * t).astype(np.int32), 0, h - 1)
        acc += f[sy, sx]
    return unpremul(acc / steps)


def _conv3(f, k):
    p = np.pad(f, ((1, 1), (1, 1), (0, 0)), mode="edge")
    h, w = f.shape[:2]
    out = np.zeros_like(f)
    for j in range(3):
        for i in range(3):
            if k[j][i]:
                out += k[j][i] * p[j:j + h, i:i + w]
    return out


def sharpen(a, amount=100, radius=1.5):
    """unsharp mask: amount 0-300 %"""
    f = premul(a)
    bl = _blur(f, radius)
    out = f + (f - bl) * (amount / 100.0)
    out[..., 3] = f[..., 3]
    out[..., :3] = np.minimum(out[..., :3], out[..., 3:4])
    return unpremul(np.clip(out, 0, 255))


def add_noise(a, amount=20, mono=True, seed=1):
    rng = np.random.default_rng(seed)
    h, w = a.shape[:2]
    n = rng.normal(0, amount * 2.55 * 0.5, (h, w, 1 if mono else 3)).astype(np.float32)
    out = a.copy()
    out[..., :3] = np.clip(a[..., :3].astype(np.float32) + n, 0, 255).astype(np.uint8)
    return out


def pixelate(a, size):
    s = max(1, int(size))
    if s == 1:
        return a
    h, w = a.shape[:2]
    f = premul(a)
    hh, ww = -(-h // s), -(-w // s)
    pad = np.pad(f, ((0, hh * s - h), (0, ww * s - w), (0, 0)), mode="edge")
    small = pad.reshape(hh, s, ww, s, 4).mean(axis=(1, 3))
    big = np.repeat(np.repeat(small, s, 0), s, 1)[:h, :w]
    return unpremul(big)


def emboss(a):
    g = a[..., :3].astype(np.float32).mean(-1, keepdims=True)
    e = _conv3(g, [[-2, -1, 0], [-1, 1, 1], [0, 1, 2]]) + 128
    out = a.copy()
    out[..., :3] = np.clip(e, 0, 255).astype(np.uint8)
    return out


def find_edges(a):
    g = a[..., :3].astype(np.float32).mean(-1, keepdims=True)
    gx = _conv3(g, [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]])
    gy = _conv3(g, [[-1, -2, -1], [0, 0, 0], [1, 2, 1]])
    m = np.clip(255 - np.hypot(gx, gy), 0, 255).astype(np.uint8)
    out = a.copy()
    out[..., :3] = m
    return out


def vignette(a, amount=50, size=70):
    h, w = a.shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = (x - w / 2) / (w / 2), (y - h / 2) / (h / 2)
    d = np.sqrt(nx * nx + ny * ny) / 1.4142
    edge = size / 100.0
    k = np.clip((d - edge * 0.6) / max(0.05, 1 - edge * 0.6), 0, 1) ** 1.5
    f = 1 - k * (amount / 100.0)
    out = a.copy()
    out[..., :3] = np.clip(a[..., :3] * f[..., None], 0, 255).astype(np.uint8)
    return out


def median3(a):
    p = np.pad(a, ((1, 1), (1, 1), (0, 0)), mode="edge")
    h, w = a.shape[:2]
    stack = np.stack([p[j:j + h, i:i + w] for j in range(3) for i in range(3)], 0)
    out = np.median(stack, axis=0).astype(np.uint8)
    out[..., 3] = a[..., 3]
    return out


def drop_shadow(a, dx=8, dy=8, radius=8, color=(0, 0, 0), opacity=60):
    """shadow behind the shape of the layer (the layer needs transparent room around the shape)"""
    h, w = a.shape[:2]
    al = a[..., 3].astype(np.float32)
    sh = np.zeros_like(al)
    x0, y0 = max(0, dx), max(0, dy)
    x1, y1 = min(w, w + dx), min(h, h + dy)
    if x1 > x0 and y1 > y0:
        sh[y0:y1, x0:x1] = al[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    sh = _blur(sh[..., None], radius)[..., 0] * (opacity / 100.0)
    f = premul(a)
    sc = np.zeros_like(f)
    sc[..., 0], sc[..., 1], sc[..., 2] = [c * sh / 255.0 for c in color[:3]]
    sc[..., 3] = sh
    out = f + sc * (1 - f[..., 3:4] / 255.0)
    return unpremul(np.clip(out, 0, 255))


def outline(a, width=4, color=(255, 255, 255)):
    from .select import Selection
    m = Selection((a[..., 3] > 127).astype(np.uint8) * 255).grown(width).mask
    f = premul(a)
    ring = np.zeros_like(f)
    k = m.astype(np.float32)
    for i in range(3):
        ring[..., i] = color[i] * k / 255.0
    ring[..., 3] = k
    out = f + ring * (1 - f[..., 3:4] / 255.0)
    return unpremul(np.clip(out, 0, 255))
