#!/usr/bin/env python3
"""
nice_view image tool
=====================

Load an image, crop it (with the crop box locked to the nice_view aspect
ratio so nothing gets squished), convert it to 1-bit monochrome, preview the
result magnified, and export it for use on a ZMK nice_view display.

Target display: Sharp memory LCD on the nice_view = 160 x 68 px, 1-bit.

Exports
-------
* PNG  - the final 160x68 black/white image. Feed this to the LVGL online
         image converter, or to a community nice_view art module.
* XBM  - X BitMap: a standard 1-bit C array you can include directly.

Requires: Python 3.8+ and Pillow  ->  pip install pillow
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk, ImageOps
except ImportError:
    raise SystemExit("Pillow is required.  Install it with:  pip install pillow")


# ---- nice_view display geometry -------------------------------------------
TARGET_W = 160
TARGET_H = 68
ASPECT = TARGET_W / TARGET_H          # crop box is locked to this ratio

# ---- UI sizing ------------------------------------------------------------
SRC_MAX_W = 640                       # max width the source preview is shown at
SRC_MAX_H = 480
PREVIEW_SCALE = 4                     # magnification of the 160x68 result
MIN_CROP_W = 16                       # smallest crop width, in source pixels


class CropTool:
    def __init__(self, root):
        self.root = root
        root.title("nice_view image tool  -  160 x 68, 1-bit")

        self.original = None          # loaded PIL image (RGB), un-rotated
        self.source = None            # working image after rotation (RGB)
        self.coarse_rot = 0           # 0/90/180/270 from the rotate buttons
        self.disp_scale = 1.0         # source-image px -> canvas px
        self.disp_img = None          # PhotoImage kept alive
        self.prev_img = None          # PhotoImage kept alive

        # crop rectangle, in SOURCE image coordinates (aspect-locked)
        self.cx = self.cy = 0.0
        self.cw = self.ch = 0.0

        # drag state
        self._mode = None             # "new" | "move"
        self._anchor = (0, 0)
        self._box_start = (0, 0)

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        bar = ttk.Frame(self.root, padding=6)
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(bar, text="Load image...", command=self.load).pack(side=tk.LEFT)

        ttk.Label(bar, text="  Threshold").pack(side=tk.LEFT)
        self.threshold = tk.IntVar(value=128)
        ttk.Scale(bar, from_=1, to=254, variable=self.threshold,
                  command=lambda _=None: self.render_preview(),
                  length=160).pack(side=tk.LEFT)

        self.invert = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Invert", variable=self.invert,
                        command=self.render_preview).pack(side=tk.LEFT, padx=6)

        self.dither = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Dither", variable=self.dither,
                        command=self.render_preview).pack(side=tk.LEFT)

        ttk.Button(bar, text="Export PNG...", command=self.export_png).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Export XBM...", command=self.export_xbm).pack(side=tk.RIGHT, padx=6)

        bar2 = ttk.Frame(self.root, padding=(6, 0, 6, 6))
        bar2.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(bar2, text="Rotate -90", command=lambda: self.rotate(-90)).pack(side=tk.LEFT)
        ttk.Button(bar2, text="Rotate +90", command=lambda: self.rotate(90)).pack(side=tk.LEFT, padx=6)

        ttk.Label(bar2, text="  Fine angle").pack(side=tk.LEFT)
        self.fine_rot = tk.DoubleVar(value=0.0)
        ttk.Scale(bar2, from_=-45, to=45, variable=self.fine_rot,
                  command=lambda _=None: self.apply_rotation(),
                  length=200).pack(side=tk.LEFT)
        ttk.Button(bar2, text="Reset rotation", command=self.reset_rotation).pack(side=tk.LEFT, padx=6)

        body = ttk.Frame(self.root, padding=6)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(body, text="Source  (drag to draw crop, drag inside to move, scroll to resize)")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.src_canvas = tk.Canvas(left, width=SRC_MAX_W, height=SRC_MAX_H,
                                    bg="#202020", highlightthickness=0)
        self.src_canvas.pack(fill=tk.BOTH, expand=True)
        self.src_canvas.bind("<ButtonPress-1>", self.on_press)
        self.src_canvas.bind("<B1-Motion>", self.on_drag)
        self.src_canvas.bind("<MouseWheel>", self.on_wheel)        # Windows / macOS
        self.src_canvas.bind("<Button-4>", self.on_wheel)          # Linux up
        self.src_canvas.bind("<Button-5>", self.on_wheel)          # Linux down

        right = ttk.LabelFrame(body, text=f"Preview  ({TARGET_W} x {TARGET_H}, magnified {PREVIEW_SCALE}x)")
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 0))
        self.prev_canvas = tk.Canvas(right, width=TARGET_W * PREVIEW_SCALE,
                                     height=TARGET_H * PREVIEW_SCALE,
                                     bg="#808080", highlightthickness=0)
        self.prev_canvas.pack()
        self.status = ttk.Label(right, text="Load an image to begin.")
        self.status.pack(pady=6)

    # --------------------------------------------------------------- loading
    def load(self):
        path = filedialog.askopenfilename(
            title="Choose an image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tiff"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            img = Image.open(path)
            img = ImageOps.exif_transpose(img).convert("RGB")
        except Exception as exc:
            messagebox.showerror("Could not open image", str(exc))
            return
        self.original = img
        self.coarse_rot = 0
        self.fine_rot.set(0.0)
        self.apply_rotation()

    # --------------------------------------------------------------- rotation
    def rotate(self, delta):
        if self.original is None:
            return
        self.coarse_rot = (self.coarse_rot + delta) % 360
        self.apply_rotation()

    def reset_rotation(self):
        if self.original is None:
            return
        self.coarse_rot = 0
        self.fine_rot.set(0.0)
        self.apply_rotation()

    def apply_rotation(self, *_):
        if self.original is None:
            return
        angle = self.coarse_rot + self.fine_rot.get()
        if angle % 360 == 0:
            self.source = self.original
        else:
            # PIL rotates counter-clockwise for positive angle; negate so the
            # buttons read as a normal clockwise/counter-clockwise turn.
            self.source = self.original.rotate(
                -angle, expand=True, resample=Image.BICUBIC, fillcolor=(0, 0, 0))
        self._fit_source_to_canvas()
        self._reset_crop()
        self.render_source()
        self.render_preview()

    def _fit_source_to_canvas(self):
        w, h = self.source.size
        self.disp_scale = min(SRC_MAX_W / w, SRC_MAX_H / h)
        dw, dh = int(w * self.disp_scale), int(h * self.disp_scale)
        self.disp_img = ImageTk.PhotoImage(self.source.resize((dw, dh), Image.LANCZOS))
        self.src_canvas.config(width=dw, height=dh)

    def _reset_crop(self):
        """Default crop: largest aspect-correct box centered on the image."""
        w, h = self.source.size
        cw = w
        ch = cw / ASPECT
        if ch > h:
            ch = h
            cw = ch * ASPECT
        self.cw, self.ch = cw, ch
        self.cx = (w - cw) / 2
        self.cy = (h - ch) / 2

    # ----------------------------------------------------------- rendering
    def render_source(self):
        c = self.src_canvas
        c.delete("all")
        if self.disp_img is None:
            return
        c.create_image(0, 0, anchor=tk.NW, image=self.disp_img)
        s = self.disp_scale
        x0, y0 = self.cx * s, self.cy * s
        x1, y1 = (self.cx + self.cw) * s, (self.cy + self.ch) * s
        c.create_rectangle(x0, y0, x1, y1, outline="#00e5ff", width=2)

    def render_preview(self, *_):
        if self.source is None:
            return
        x, y = int(round(self.cx)), int(round(self.cy))
        w, h = int(round(self.cw)), int(round(self.ch))
        w, h = max(1, w), max(1, h)
        crop = self.source.crop((x, y, x + w, y + h))

        small = crop.resize((TARGET_W, TARGET_H), Image.LANCZOS).convert("L")
        if self.invert.get():
            small = ImageOps.invert(small)

        if self.dither.get():
            bw = small.convert("1")                       # Floyd-Steinberg
        else:
            t = self.threshold.get()
            bw = small.point(lambda p: 255 if p > t else 0).convert("1")

        self._last_bw = bw
        big = bw.convert("L").resize(
            (TARGET_W * PREVIEW_SCALE, TARGET_H * PREVIEW_SCALE), Image.NEAREST)
        self.prev_img = ImageTk.PhotoImage(big)
        self.prev_canvas.delete("all")
        self.prev_canvas.create_image(0, 0, anchor=tk.NW, image=self.prev_img)

        note = "  (upscaled - may look soft)" if w < TARGET_W or h < TARGET_H else ""
        self.status.config(text=f"Crop: {w} x {h} px in source{note}")
        self.render_source()

    # -------------------------------------------------------- interaction
    def _to_img(self, ev):
        return ev.x / self.disp_scale, ev.y / self.disp_scale

    def _inside_crop(self, ix, iy):
        return (self.cx <= ix <= self.cx + self.cw and
                self.cy <= iy <= self.cy + self.ch)

    def on_press(self, ev):
        if self.source is None:
            return
        ix, iy = self._to_img(ev)
        if self._inside_crop(ix, iy):
            self._mode = "move"
            self._anchor = (ix, iy)
            self._box_start = (self.cx, self.cy)
        else:
            self._mode = "new"
            self._anchor = (ix, iy)

    def on_drag(self, ev):
        if self.source is None or self._mode is None:
            return
        ix, iy = self._to_img(ev)
        w, h = self.source.size
        if self._mode == "new":
            ax, ay = self._anchor
            cw = max(MIN_CROP_W, abs(ix - ax))
            ch = cw / ASPECT
            cx = min(ax, ix)
            cy = min(ay, iy)
            self.cw, self.ch = cw, ch
            self.cx, self.cy = cx, cy
            self._clamp()
        elif self._mode == "move":
            ax, ay = self._anchor
            sx, sy = self._box_start
            self.cx = sx + (ix - ax)
            self.cy = sy + (iy - ay)
            self._clamp()
        self.render_preview()

    def on_wheel(self, ev):
        if self.source is None:
            return
        up = getattr(ev, "delta", 0) > 0 or getattr(ev, "num", 0) == 4
        factor = 0.9 if up else 1.1          # scroll up = zoom in (smaller crop)
        ccx = self.cx + self.cw / 2
        ccy = self.cy + self.ch / 2
        self.cw = max(MIN_CROP_W, self.cw * factor)
        self.ch = self.cw / ASPECT
        self.cx = ccx - self.cw / 2
        self.cy = ccy - self.ch / 2
        self._clamp()
        self.render_preview()

    def _clamp(self):
        """Keep the aspect-locked box fully inside the image."""
        w, h = self.source.size
        if self.cw > w:
            self.cw = w
            self.ch = self.cw / ASPECT
        if self.ch > h:
            self.ch = h
            self.cw = self.ch * ASPECT
        self.cx = min(max(0, self.cx), w - self.cw)
        self.cy = min(max(0, self.cy), h - self.ch)

    # ------------------------------------------------------------ exporting
    def export_png(self):
        if not self._ensure_image():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG", "*.png")],
            initialfile="niceview.png")
        if path:
            self._last_bw.save(path)
            messagebox.showinfo("Saved", f"Wrote {path}")

    def export_xbm(self):
        if not self._ensure_image():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xbm", filetypes=[("XBM", "*.xbm")],
            initialfile="niceview.xbm")
        if path:
            self._last_bw.save(path)
            messagebox.showinfo("Saved", f"Wrote {path}\n(standard 1-bit C array)")

    def _ensure_image(self):
        if self.source is None or getattr(self, "_last_bw", None) is None:
            messagebox.showwarning("No image", "Load and crop an image first.")
            return False
        return True


def main():
    root = tk.Tk()
    CropTool(root)
    root.mainloop()


if __name__ == "__main__":
    main()
