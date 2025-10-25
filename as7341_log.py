#!/usr/bin/env python3
"""
as7341_log.py

Logs N samples from the AS7341 spectral sensor into a CSV file.
Now supports --it (integration time, ms) and --gain (multiplier).
"""

import argparse
import csv
import time
import board
import busio
from adafruit_as7341 import AS7341

def main():
    parser = argparse.ArgumentParser(description="Log AS7341 sensor readings")
    parser.add_argument("--out", required=True, help="Output CSV file")
    parser.add_argument("--count", type=int, default=50, help="Number of samples to log")
    parser.add_argument("--it", type=int, default=100, help="Integration time in ms (default=100)")
    parser.add_argument("--gain", type=int, default=4, help="Gain multiplier (default=4)")
    args = parser.parse_args()

    # Set up I2C and sensor
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor = AS7341(i2c)

    # Configure integration time and gain
    sensor.integration_time = args.it
    sensor.gain = args.gain

    print(f"Logging {args.count} samples → {args.out}")
    print(f"(IT={args.it} ms, gain={args.gain})")

    # Prepare CSV
    fieldnames = [
        "ts", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8",
        "CLEAR", "NIR"
    ]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i in range(args.count):
            ts = time.time()
            row = {
                "ts": ts,
                "F1": sensor.channel_415nm,
                "F2": sensor.channel_445nm,
                "F3": sensor.channel_480nm,
                "F4": sensor.channel_515nm,
                "F5": sensor.channel_555nm,
                "F6": sensor.channel_590nm,
                "F7": sensor.channel_630nm,
                "F8": sensor.channel_680nm,
                "CLEAR": sensor.channel_clear,
                "NIR": sensor.channel_nir,
            }
            writer.writerow(row)
            print(f"[{i+1}/{args.count}] {row}")
            time.sleep(0.1)

    print("Done.")

if __name__ == "__main__":
    main()
