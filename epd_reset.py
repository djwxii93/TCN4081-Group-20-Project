# epd_reset.py — full clear + reinit + sleep for Waveshare 2.13" V2
import time
from PIL import Image
try:
    from waveshare_epd import epd2in13_V2 as drv  # BW 250x122 (most 2.13" HATs)
except Exception:
    from lib.waveshare_epd import epd2in13_V2 as drv

epd = drv.EPD()

# Full init, clear to white, then draw a blank frame and sleep.
epd.init("full")                  # full init
epd.Clear(0xFF)             # full white clear (removes ghosting)
time.sleep(1)

img = Image.new('1', (250, 122), 255)  # white frame (landscape canvas)
epd.display(epd.getbuffer(img))
time.sleep(0.5)

# Put panel to sleep and release SPI
epd.sleep()
try:
    epd.Dev_exit()
except Exception:
    pass

print("E-paper cleared and put to sleep.")
