import time, board, busio
from adafruit_as7341 import AS7341

i2c = busio.I2C(board.SCL, board.SDA)
s = AS7341(i2c)

print("Press Ctrl+C to stop.")
while True:
    try:
        print({
            "415nm": s.channel_415nm,
            "445nm": s.channel_445nm,
            "480nm": s.channel_480nm,
            "515nm": s.channel_515nm,
            "555nm": s.channel_555nm,
            "590nm": s.channel_590nm,
            "630nm": s.channel_630nm,
            "680nm": s.channel_680nm,
            "Clear": s.channel_clear,
            "NIR":   s.channel_nir,
        })
        time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")
        break
