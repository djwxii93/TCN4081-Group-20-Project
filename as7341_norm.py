import time, sys, board, busio
from collections import deque
from adafruit_as7341 import AS7341

i2c = busio.I2C(board.SCL, board.SDA)
s = AS7341(i2c)

BANDS = [
    ("415", lambda s: s.channel_415nm),
    ("445", lambda s: s.channel_445nm),
    ("480", lambda s: s.channel_480nm),
    ("515", lambda s: s.channel_515nm),
    ("555", lambda s: s.channel_555nm),
    ("590", lambda s: s.channel_590nm),
    ("630", lambda s: s.channel_630nm),
    ("680", lambda s: s.channel_680nm),
]
KEYS = [b for b,_ in BANDS]
WINDOW = 5
buf = {k: deque(maxlen=WINDOW) for k in KEYS}

def safe_div(a, b, eps=1e-9): return a / b if b > eps else 0.0

print("Normalized output (Ctrl+C to stop)")
while True:
    try:
        clr = float(s.channel_clear or 1)
        raw = {k: float(fn(s)) for k,fn in BANDS}
        norm = {k: safe_div(raw[k], clr) for k in KEYS}
        for k in KEYS: buf[k].append(norm[k])
        smooth = {k: sum(buf[k])/len(buf[k]) for k in KEYS}
        print(" ".join(f"{k}:{smooth[k]:.3f}" for k in KEYS))
        time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.")
        break
