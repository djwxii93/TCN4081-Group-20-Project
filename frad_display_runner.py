#!/usr/bin/env python3
# frad_display_runner.py
# Live Waveshare 2.13" display of FRAD scanning + ripeness results

import time
import math
from datetime import datetime

# ---- DISPLAY DRIVER (pick the one you have) ----
# For 2.13" V4:
from waveshare_epd import epd2in13_V4 as epd_driver
# If you have V2 instead, comment the line above and uncomment:
# from waveshare_epd import epd2in13_V2 as epd_driver

from PIL import Image, ImageDraw, ImageFont

# ---- FRAD modules (adjust if your function names differ) ----
# TODO(1): Spectrum reader
try:
    import as7341_norm as spec_reader  # your normalized reader (preferred)
except ImportError:
    import as7341_read as spec_reader   # fallback to raw if needed

# TODO(2): Ripeness index
import ripeness_index_run as ripeness

# ---------- Helpers ----------
def safe_font(size=16):
    try:
        # If you have a TTF like DejaVuSans:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

def draw_bar(draw, x, y, w, h, pct):
    pct = max(0.0, min(1.0, pct))
    fill_w = int(w * pct)
    # outline
    draw.rectangle([x, y, x+w, y+h], outline=0, width=1)
    # fill
    if fill_w > 0:
        draw.rectangle([x, y, x+fill_w, y+h], fill=0)

def format_pct(p):
    return f"{int(round(100*p))}%"

# ---------- Main ----------
def main():
    # Init display
    epd = epd_driver.EPD()
    epd.init()  # default = full update
    width, height = epd.height, epd.width  # (Yes, rotated)
    # Rotate 90° to use landscape: create img with (width,height) swapped
    img = Image.new('1', (epd.width, epd.height), 255)
    draw = ImageDraw.Draw(img)

    font_h1 = safe_font(16)
    font_h2 = safe_font(14)
    font_sm = safe_font(12)

    # Clear once
    epd.Clear(0xFF)

    # Switch to PARTIAL update for fast UI refresh
    try:
        epd.init(epd_driver.PART_UPDATE)
        partial_supported = True
    except Exception:
        partial_supported = False  # some drivers don’t expose PART_UPDATE

    cycle = 0
    full_refresh_every = 15  # do a full refresh periodically to reduce ghosting
    sleep_s = 1.0            # update cadence

    # If your sensor module needs setup, do it here
    # e.g., spec_reader.init()  (uncomment if applicable)

    try:
        while True:
            cycle += 1
            # ---- 1) Read spectrum from sensor ----
            # Expected: dict of normalized channels or a list/tuple
            # TODO(1): Replace with your exact call
            # Example stubs:
            #   spec = spec_reader.read_normalized()  -> returns dict
            #   spec = spec_reader.read_raw()         -> returns dict
            spec = None
            if hasattr(spec_reader, "read_normalized"):
                spec = spec_reader.read_normalized()
            elif hasattr(spec_reader, "read_once"):
                spec = spec_reader.read_once()
            else:
                # Last-resort stub to avoid crash while you wire in the real call
                spec = {"415": 0.12, "445": 0.20, "480": 0.31, "515": 0.44, "555": 0.52,
                        "590": 0.47, "630": 0.38, "680": 0.29, "CLEAR": 1.00, "NIR": 0.40}

            # ---- 2) Compute ripeness score ----
            # TODO(2): Replace with your actual ripeness function
            # Expect a float 0..1 and an optional class label
            score = 0.0
            label = "Scanning"
            if hasattr(ripeness, "compute_index"):
                score = float(ripeness.compute_index(spec))
            elif hasattr(ripeness, "predict"):
                out = ripeness.predict(spec)  # e.g., returns dict {"score":0.73,"label":"Ripe"}
                score = float(out.get("score", 0.0))
                label = out.get("label", "Unknown")
            else:
                # simple placeholder: higher NIR means riper (example only!)
                score = float(spec.get("NIR", 0.4))
                label = "Est."

            score = max(0.0, min(1.0, score))
            pct_text = format_pct(score)

            # ---- 3) Render UI ----
            draw.rectangle([0, 0, epd.width, epd.height], fill=255)  # clear buffer (white)

            margin = 6
            y = margin

            # Header
            draw.text((margin, y), "FRAD • Live Scan", font=font_h1, fill=0)
            ts = datetime.now().strftime("%H:%M:%S")
            draw.text((epd.width - 80, y), ts, font=font_sm, fill=0)
            y += 20

            # Fruit / status line (set fruit name if you have it)
            draw.text((margin, y), f"Status: {label}", font=font_h2, fill=0)
            y += 18

            # Ripeness
            draw.text((margin, y), f"Ripeness: {pct_text}", font=font_h2, fill=0)
            y += 18

            # Bar
            bar_w = epd.width - 2*margin
            bar_h = 16
            draw_bar(draw, margin, y, bar_w, bar_h, score)
            y += bar_h + 10

            # Optional quick spectral readout (two or three bands)
            keys = [k for k in spec.keys() if k.isdigit()]
            keys = sorted(keys, key=int)
            if keys:
                sample_keys = [keys[0], keys[len(keys)//2], keys[-1]]
                line = " | ".join(f"{k}:{spec.get(k, 0):.2f}" for k in sample_keys)
                draw.text((margin, y), line, font=font_sm, fill=0)
                y += 14

            # Footer
            draw.text((margin, epd.height-16), "Partial updates; full every ~15s", font=font_sm, fill=0)

            # ---- 4) Push to panel ----
            if partial_supported and (cycle % full_refresh_every):
                epd.displayPartial(epd.getbuffer(img))
            else:
                # full refresh (init full mode briefly if needed)
                try:
                    epd.init()
                except Exception:
                    pass
                epd.display(epd.getbuffer(img))
                # return to partial if available
                if partial_supported:
                    try:
                        epd.init(epd_driver.PART_UPDATE)
                    except Exception:
                        pass

            time.sleep(sleep_s)

    except KeyboardInterrupt:
        pass
    finally:
        # Tidy shutdown
        try:
            epd.sleep()
        except Exception:
            pass

if __name__ == "__main__":
    main()
