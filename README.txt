DIGONTO IMAGES 1.0
Photo editing with layers, selections, brushes, adjustments and filters.
Open it from Digonto Studio (tile "Digonto Images").

TOOLS (left side)
  Move (V)      drag the active layer; arrow keys nudge, Shift = 10 px
  Select (M)    rectangle, ellipse or freehand. Shift adds, Alt subtracts, click = deselect
  Wand (W)      select by colour. Tolerance, touching-only, "this layer only"
  Brush (B)     size, hardness, opacity.   [ and ] change the size
  Eraser (E)    same settings, rubs out to transparency
  Fill (K)      fills a colour area. Gradient (G): linear or radial, front to back colour
  Picker (I)    click = front colour, Alt-click = back colour
  Text (T)      click, type; font, size, bold, italic, alignment, colour. Layer > Edit text changes it later
  Shape (U)     rectangle, rounded, ellipse, line - fill and/or outline
  Crop (C)      drag, Enter = crop.   Hand (H) / Space = move around.   Zoom (Z)
Everything paints inside the selection when there is one.

PANELS (View menu shows or hides them)
  Navigator     small picture with a red frame - drag it to move around, slider zooms
  Colour        front/back colour, sliders, hex, swatches (X swaps, D = black/white)
  Layers        show/hide, opacity, 13 blend modes, lock, add, duplicate, reorder, merge, delete (double-click = rename)
  History       click any step to go back to it (40 steps)

MENUS
  Image         size, canvas size, crop to selection, rotate, flip
  Adjust        brightness/contrast, levels, curves, hue/saturation, vibrance, temperature, colour balance, auto levels,
                invert, black and white, threshold, posterize, sepia, gradient map  (live preview, Cancel puts it back)
  Filter        gaussian and motion blur, sharpen, noise, median, pixelate, emboss, edges, vignette, drop shadow, outline
  Select        all, none, inverse, soft edge, grow, shrink, smooth

FILES
  Save project  .pimg keeps all layers, text and blend modes (a zip with one PNG per layer)
  Export        PNG (optimised automatically), JPG, WebP, PDF, PSD (layers kept), BMP, ICO.
  Open          PNG JPG WebP BMP GIF ICO TGA SVG, .psd and .pimg. Drag a file onto the window to open it.
  Photoshop files are written without compression, so a .psd can be large.
  Photoshop text layers open as editable text (words, font, size, colour). Text layers are saved back as real
  Photoshop text layers, so they stay editable in Photoshop. A missing font is replaced by the closest installed one.
  Layer masks are saved as real masks (Photoshop and GIMP can keep editing them), also when a mask is switched off.
  Layer styles are merged into the layer pixels in a saved .psd (a mask on a layer with styles is merged too);
  adjustment layers are not written.

RETOUCHING AND NON-DESTRUCTIVE WORK
  Clone stamp, Healing brush, Spot healing   Alt + click = choose the part to copy, then paint (Spot healing: just paint over the spot)
  Smudge, Blur brush, Sharpen brush, Dodge, Burn   in the Retouch tool menu
  Layer masks      Layers panel > Mask: show all / hide all / from selection. Paint black to hide, white to show
  Adjustment layers  Layers panel > Adjustment: brightness, levels, hue/saturation... edit again any time (double-click)
  Layer styles     fx button: drop shadow, outer glow, outline, colour overlay
  Free transform (Ctrl+T)   drag handles to scale, inside to move, outside to rotate; Shift = proportions, Alt = from centre; Enter applies
  Quick selection (A)   paint over an object, the selection grows over similar colours; Select > Colour range picks one colour everywhere
  Layer > Stamp visible, Merge visible
  Image > Rotate by any angle (straighten)
  Saving .psd bakes masks and styles into each layer; adjustment layers are not written to .psd (the .pimg project keeps everything)

PHOTOSHOP PRESETS
  Brush tool       Load .abr brushes (options bar). Gradient tool: Load .grd gradients. Colour panel: Load .aco / .act swatches.
  Tested with files built from the format descriptions; some very new or unusual preset files may not load.

SIDES
  Tools (left)     one small button per tool; Select and Shape open a menu of variants (rectangle, round, rounded, lasso, polygon / rectangle, rounded, ellipse, line)
  Properties       (right, under Navigator) picture size, layer position and size, text font and size, selection bounds
  Layers           drag a layer up or down to reorder it

Needs PySide6, NumPy and Pillow (installed by the Digonto installer). The AI background remover is in Digonto Tools.
