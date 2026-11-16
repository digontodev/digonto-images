"""Color adjustments on RGBA uint8 arrays (straight alpha). Each returns a new array; alpha is kept."""
import numpy as np


def _lut(a, table):
    out = a.copy()
    out[..., :3] = table[a[..., :3]]
    return out


def lut_from_points(points):
    """curve through (x, y) points in 0-255 -> 256 table (smooth, monotone)"""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    if len(xs) < 2:
        return np.arange(256, dtype=np.uint8)
    # monotone cubic (Fritsch-Carlson)
    n = len(xs)
    dx, dy = np.diff(xs), np.diff(ys)
    m = dy / np.where(dx == 0, 1, dx)
    t = np.zeros(n)
    t[0], t[-1] = m[0], m[-1]
    for i in range(1, n - 1):
        t[i] = 0 if m[i - 1] * m[i] <= 0 else (m[i - 1] + m[i]) / 2
    for i in range(n - 1):
        if m[i] == 0:
            t[i] = t[i + 1] = 0
        else:
            a, b = t[i] / m[i], t[i + 1] / m[i]
            s = a * a + b * b
            if s > 9:
                k = 3 / np.sqrt(s)
                t[i], t[i + 1] = k * a * m[i], k * b * m[i]
    x = np.arange(256, dtype=np.float64)
    idx = np.clip(np.searchsorted(xs, x, side="right") - 1, 0, n - 2)
    h = np.where(dx[idx] == 0, 1, dx[idx])
    u = (x - xs[idx]) / h
    h00, h10, h01, h11 = 2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u, -2 * u**3 + 3 * u**2, u**3 - u**2
    y = h00 * ys[idx] + h10 * h * t[idx] + h01 * ys[idx + 1] + h11 * h * t[idx + 1]
    y = np.where(x <= xs[0], ys[0], np.where(x >= xs[-1], ys[-1], y))
    return np.clip(np.round(y), 0, 255).astype(np.uint8)


def brightness_contrast(a, brightness=0, contrast=0):
    """brightness, contrast: -100..100"""
    x = np.arange(256, dtype=np.float32)
    c = contrast / 100.0
    f = (1 + c) / (1 - c) if c < 1 else 255.0
    y = (x - 127.5) * (f if c > 0 else (1 + c)) + 127.5 + brightness * 1.5
    return _lut(a, np.clip(y, 0, 255).astype(np.uint8))


def levels(a, black=0, white=255, gamma=1.0, out_black=0, out_white=255, channels="rgb"):
    x = np.arange(256, dtype=np.float32)
    y = np.clip((x - black) / max(1, white - black), 0, 1) ** (1.0 / max(0.05, gamma))
    y = out_black + y * (out_white - out_black)
    t = np.clip(y, 0, 255).astype(np.uint8)
    out = a.copy()
    for i, ch in enumerate("rgb"):
        if ch in channels:
            out[..., i] = t[a[..., i]]
    return out


def curves(a, pts_rgb, pts_r=None, pts_g=None, pts_b=None):
    out = a.copy()
    main = lut_from_points(pts_rgb)
    for i, p in enumerate((pts_r, pts_g, pts_b)):
        t = main[lut_from_points(p)] if p else main
        out[..., i] = t[a[..., i]]
    return out


def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rc = np.where(nz & (mx == r), ((g - b) / np.where(nz, d, 1)) % 6, 0)
    gc = np.where(nz & (mx == g) & (mx != r), (b - r) / np.where(nz, d, 1) + 2, 0)
    bc = np.where(nz & (mx == b) & (mx != r) & (mx != g), (r - g) / np.where(nz, d, 1) + 4, 0)
    h = (rc + gc + bc) / 6.0
    s = np.where(mx > 1e-6, d / np.where(mx > 1e-6, mx, 1), 0)
    return np.stack([h % 1.0, s, mx], -1)


def hsv_to_rgb(hsv):
    h, s, v = hsv[..., 0] * 6.0, hsv[..., 1], hsv[..., 2]
    i = np.floor(h).astype(np.int32) % 6
    f = h - np.floor(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def _chunks(a, fn, rows=256):
    out = a.copy()
    for y in range(0, a.shape[0], rows):
        out[y:y + rows] = fn(a[y:y + rows])
    return out


def hue_saturation(a, hue=0, saturation=0, lightness=0):
    """hue -180..180 degrees, saturation / lightness -100..100"""
    def f(c):
        rgb = c[..., :3].astype(np.float32) / 255.0
        hsv = rgb_to_hsv(rgb)
        hsv[..., 0] = (hsv[..., 0] + hue / 360.0) % 1.0
        s = saturation / 100.0
        hsv[..., 1] = np.clip(hsv[..., 1] * (1 + s if s < 0 else 1 + s * 2), 0, 1)
        out = hsv_to_rgb(hsv)
        l = lightness / 100.0
        out = out * (1 + l) if l < 0 else out + (1 - out) * l
        o = c.copy()
        o[..., :3] = np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)
        return o
    return _chunks(a, f)


def vibrance(a, amount):
    def f(c):
        rgb = c[..., :3].astype(np.float32) / 255.0
        hsv = rgb_to_hsv(rgb)
        k = amount / 100.0
        hsv[..., 1] = np.clip(hsv[..., 1] + k * (1 - hsv[..., 1]) * (1 - hsv[..., 1] * 0.5), 0, 1)
        o = c.copy()
        o[..., :3] = np.clip(hsv_to_rgb(hsv) * 255 + 0.5, 0, 255).astype(np.uint8)
        return o
    return _chunks(a, f)


def temperature(a, temp=0, tint=0):
    """temp -100 (cooler) .. 100 (warmer), tint -100 (green) .. 100 (magenta)"""
    out = a.astype(np.float32)
    out[..., 0] *= 1 + temp / 300.0
    out[..., 2] *= 1 - temp / 300.0
    out[..., 1] *= 1 - tint / 300.0
    out[..., 0] *= 1 + tint / 600.0
    out[..., 2] *= 1 + tint / 600.0
    out[..., 3] = a[..., 3]
    return np.clip(out, 0, 255).astype(np.uint8)


def color_balance(a, shadows=(0, 0, 0), mids=(0, 0, 0), highs=(0, 0, 0)):
    """each (cyan-red, magenta-green, yellow-blue) -100..100"""
    x = np.arange(256, dtype=np.float32) / 255.0
    w_s = np.clip(1 - x * 2.0, 0, 1) ** 1.0
    w_h = np.clip(x * 2.0 - 1, 0, 1) ** 1.0
    w_m = 1 - w_s - w_h
    out = a.copy()
    for i in range(3):
        d = (shadows[i] * w_s + mids[i] * w_m + highs[i] * w_h) * 0.6
        t = np.clip(x * 255 + d, 0, 255).astype(np.uint8)
        out[..., i] = t[a[..., i]]
    return out


def invert(a):
    return _lut(a, (255 - np.arange(256)).astype(np.uint8))


def luma(a):
    return (a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114).astype(np.float32)


def desaturate(a):
    g = np.clip(luma(a) + 0.5, 0, 255).astype(np.uint8)
    out = a.copy()
    out[..., 0] = out[..., 1] = out[..., 2] = g
    return out


def threshold(a, level=128):
    g = np.where(luma(a) >= level, 255, 0).astype(np.uint8)
    out = a.copy()
    out[..., 0] = out[..., 1] = out[..., 2] = g
    return out


def posterize(a, levels_=4):
    n = max(2, int(levels_))
    x = np.arange(256)
    return _lut(a, (np.round(x / 255 * (n - 1)) / (n - 1) * 255).astype(np.uint8))


def sepia(a, amount=100):
    g = luma(a)
    tone = np.stack([g * 1.07, g * 0.74, g * 0.43], -1)
    k = amount / 100.0
    out = a.copy()
    out[..., :3] = np.clip(a[..., :3] * (1 - k) + tone * k, 0, 255).astype(np.uint8)
    return out


def gradient_map(a, c1, c2):
    g = (luma(a) / 255.0)[..., None]
    out = a.copy()
    out[..., :3] = np.clip(np.array(c1[:3], np.float32) * (1 - g) + np.array(c2[:3], np.float32) * g, 0, 255).astype(np.uint8)
    return out


def auto_levels(a, clip=0.5):
    out = a.copy()
    for i in range(3):
        ch = a[..., i]
        lo, hi = np.percentile(ch, [clip, 100 - clip])
        if hi > lo:
            t = np.clip((np.arange(256) - lo) / (hi - lo), 0, 1) * 255
            out[..., i] = t.astype(np.uint8)[ch]
    return out


def auto_contrast(a, clip=0.5):
    g = luma(a)
    lo, hi = np.percentile(g, [clip, 100 - clip])
    if hi <= lo:
        return a
    t = (np.clip((np.arange(256) - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
    return _lut(a, t)


def histogram(a):
    """-> (r, g, b, luma) arrays of 256 counts"""
    m = a[..., 3] > 0
    px = a[m] if m.any() else a.reshape(-1, 4)
    return [np.bincount(px[:, i], minlength=256) for i in range(3)] + [np.bincount(np.clip(luma(px[:, None, :]).ravel(), 0, 255).astype(np.uint8), minlength=256)]


def blend_masked(src, dst, mask):
    """result = src where mask is 255, dst where 0 (alpha channel taken from dst)"""
    if mask is None:
        return dst
    k = (mask.astype(np.float32) / 255.0)[..., None]
    out = src.astype(np.float32) * (1 - k) + dst.astype(np.float32) * k
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)
