# frad_display.py — Waveshare 2.13" e-Paper helper (landscape + progress)
from PIL import Image, ImageDraw, ImageFont

def _load_driver():
    try:
        from waveshare_epd import epd2in13_V2 as drv
    except Exception:
        from lib.waveshare_epd import epd2in13_V2 as drv
    return drv

class EInkDisplay:
    """
    Landscape rendering for 2.13" V2 (driver native: 122x250).
    We draw on a 250x122 canvas (landscape), then rotate -90° to native.
    """
    def __init__(self, full_every: int = 15, orientation: str = "landscape"):
        drv = _load_driver()
        self.epd = drv.EPD()
        self.full_every = max(1, int(full_every))
        self._count = 0

        # Visual canvas (what you design in)
        self.W_vis, self.H_vis = (250, 122) if orientation == "landscape" else (122, 250)
        # Panel native (what the driver expects)
        self.W_nat, self.H_nat = 122, 250
        self.rotate_to_native = (orientation == "landscape")  # rotate -90 before send

        # Fonts
        try:
            self.font_big = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 28)
            self.font_med = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 20)
            self.font_small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)
        except Exception:
            self.font_big = self.font_med = self.font_small = ImageFont.load_default()

        # Init + first full clear to avoid ghosting
        self.epd.init()
        self.clear(full=True)

    # ---------- low level ----------

    def clear(self, full: bool = True):
        # Full clear recommended at start; driver does full by default on V2
        self.epd.Clear(0xFF)

    def _to_native(self, img_vis: Image.Image) -> Image.Image:
        if self.rotate_to_native:
            # Rotate canvas -90° to map 250x122 → 122x250 native
            img_nat = img_vis.rotate(90, expand=True)  # PIL rotates counter-clockwise; 90° makes landscape map to native
        else:
            img_nat = img_vis
        # Ensure exact native size & 1-bit mode
        img_nat = img_nat.convert("1").resize((self.W_nat, self.H_nat))
        return img_nat

    def _display(self, img_vis: Image.Image):
        img_nat = self._to_native(img_vis)
        self.epd.display(self.epd.getbuffer(img_nat))
        self._count += 1
        if self._count % self.full_every == 0:
            # Periodic full clear to prevent accumulated ghosting
            self.clear(full=True)

    # ---------- drawing helpers ----------

    def _canvas(self, bg_white=True) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        bg = 255 if bg_white else 0
        img = Image.new('1', (self.W_vis, self.H_vis), bg)
        return img, ImageDraw.Draw(img)

    def _center_text(self, d: ImageDraw.ImageDraw, text: str, y: int, font, invert=False):
        w, h = d.textsize(text, font=font)
        d.text(((self.W_vis - w)//2, y), text, font=font, fill=0 if not invert else 255)

    # ---------- public API ----------

    def show_scanning(self):
        img, d = self._canvas()
        self._center_text(d, "SCANNING...", 16, self.font_med)
        # simple “progress bar frame” (empty at start)
        d.rectangle([(20, self.H_vis - 26), (self.W_vis - 20, self.H_vis - 18)], outline=0, width=1)
        self._display(img)

    def show_step(self, step: int, total: int, label: str = ""):
        # Render a progress bar based on step/total
        img, d = self._canvas()
        pct = max(0.0, min(1.0, (step / float(max(1, total)))))
        pct_str = f"{int(pct*100)}%"
        top = f"STEP {step}/{total}"
        self._center_text(d, top, 10, self.font_small)
        if label:
            self._center_text(d, label, 34, self.font_med)

        # Draw progress bar
        x1, x2 = 20, self.W_vis - 20
        y1, y2 = self.H_vis - 30, self.H_vis - 18
        d.rectangle([(x1, y1), (x2, y2)], outline=0, width=1)
        fill_w = int(x1 + pct * (x2 - x1))
        if fill_w > x1:
            d.rectangle([(x1+1, y1+1), (fill_w-1, y2-1)], fill=0)
        self._center_text(d, pct_str, y1 - 18, self.font_small)

        self._display(img)

    def show_result(self, label: str, invert: bool = False):
        img, d = self._canvas(bg_white=not invert)
        self._center_text(d, "RESULT", 10, self.font_small, invert=invert)
        self._center_text(d, label.upper(), 52, self.font_big, invert=invert)
        self._display(img)

    def show_message(self, top: str, bottom: str = ""):
        img, d = self._canvas()
        self._center_text(d, top, 18, self.font_med)
        if bottom:
            self._center_text(d, bottom, 60, self.font_big)
        self._display(img)

    def sleep(self):
        try:
            self.epd.sleep()
        except Exception:
            pass
