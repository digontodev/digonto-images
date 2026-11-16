"""Settings shared by the tools and the panels."""
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor


class State(QObject):
    changed = Signal(str)          # name of the setting that changed

    DEFAULTS = dict(size=24, hardness=70, opacity=100, tolerance=32, contiguous=True, sample_all=True, feather=0,
                    shape="rect", fill=True, stroke=False, stroke_w=4, radius=24, grad="linear", grad_mode="fg-bg",
                    sel_kind="rect", font="Sans Serif", font_size=64, bold=False, italic=False, align="left", text_color="#000000",
                    sample_layer=False)

    def __init__(self):
        super().__init__()
        self.fg, self.bg = QColor("#000000"), QColor("#FFFFFF")
        self.tool = "brush"
        from .presets import builtin_gradients
        self.tip = None                      # brush tip from an .abr file (None = round brush)
        self.brush_presets = []              # loaded tips
        self.gradient = None                 # None = front to back colour
        self.gradients = builtin_gradients() # built in + loaded
        self.swatches = None                 # loaded colour swatches (None = built in)
        for k, v in self.DEFAULTS.items():
            setattr(self, k, v)

    def set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
            self.changed.emit(k)

    def swap(self):
        self.fg, self.bg = self.bg, self.fg
        self.changed.emit("fg")

    def reset_colors(self):
        self.fg, self.bg = QColor("#000000"), QColor("#FFFFFF")
        self.changed.emit("fg")
