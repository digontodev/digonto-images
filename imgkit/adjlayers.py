"""Adjustment layers: a setting that changes everything below it and can be edited again at any time."""
from . import adjust

# kind -> (name, [(key, label, lo, hi, default, scale?)], function(array, **params))
KINDS = {
    "brightness": ("Brightness / Contrast", [("brightness", "Brightness", -100, 100, 0), ("contrast", "Contrast", -100, 100, 0)],
                   lambda a, brightness=0, contrast=0: adjust.brightness_contrast(a, brightness, contrast)),
    "levels": ("Levels", [("black", "Shadows", 0, 250, 0), ("gamma", "Midtones", 10, 400, 100, 100), ("white", "Highlights", 5, 255, 255)],
               lambda a, black=0, gamma=1.0, white=255: adjust.levels(a, int(black), int(max(black + 1, white)), gamma)),
    "huesat": ("Hue / Saturation", [("hue", "Hue", -180, 180, 0), ("saturation", "Saturation", -100, 100, 0), ("lightness", "Lightness", -100, 100, 0)],
               lambda a, hue=0, saturation=0, lightness=0: adjust.hue_saturation(a, hue, saturation, lightness)),
    "vibrance": ("Vibrance", [("amount", "Amount", -100, 100, 30)], lambda a, amount=30: adjust.vibrance(a, amount)),
    "temperature": ("Temperature / Tint", [("temp", "Warm - cool", -100, 100, 0), ("tint", "Green - magenta", -100, 100, 0)],
                    lambda a, temp=0, tint=0: adjust.temperature(a, temp, tint)),
    "bw": ("Black and white", [], lambda a: adjust.desaturate(a)),
    "invert": ("Invert", [], lambda a: adjust.invert(a)),
    "threshold": ("Threshold", [("level", "Level", 0, 255, 128)], lambda a, level=128: adjust.threshold(a, level)),
    "posterize": ("Posterize", [("n", "Levels", 2, 16, 4)], lambda a, n=4: adjust.posterize(a, int(n))),
    "sepia": ("Sepia", [("amount", "Amount", 0, 100, 100)], lambda a, amount=100: adjust.sepia(a, amount)),
}


def defaults(kind):
    return {s[0]: (s[4] / s[5] if len(s) > 5 else s[4]) for s in KINDS[kind][1]}


def apply(adj, a):
    """adj = dict(kind, params); a = straight RGBA uint8 -> straight RGBA uint8"""
    fn = KINDS[adj["kind"]][2]
    return fn(a, **adj.get("params", {}))
