#!/usr/bin/env python3
"""
calibrate_runner.py

Interactive calibration wizard for AS7341.
Captures:
  1. Dark reference (cover sensor)
  2. White reference (white card, full illumination)

Generates calibration JSON with offset/scale per channel.
"""

import argparse
import json
import time
import board
import busio
from adafruit_as7341 import AS7341
from pathlib import Path

CHANNELS = {
    "F1": "415nm",
    "F2": "445nm",
    "F3": "480nm",
    "F4": "515nm",
    "F5": "555nm",
    "F6": "590nm",
    "F7": "630nm",
    "F8": "680nm",
    "CLEAR": "Clear",
    "NIR": "NearIR"
}

def read_average(sensor, n=10, delay=0.1):
    """Read n samples and return average dict."""
    vals = {ch: 0 for ch in CHANNELS}
    for i in range(n):
        vals["F1"] += sensor.channel_415nm
        vals["F2"] += sensor.channel_445nm
        vals["F3"] += sensor.channel_480nm
        vals["F4"] += sensor.channel_515nm
        vals["F5"] += sensor.channel_555nm
        vals["F6"] += sensor.channel_590nm
        vals["F7"] += sensor.channel_630nm
        vals["F8"] += sensor.channel_680nm
        vals["CLEAR"] += sensor.channel_clear
        vals["NIR"] += sensor.channel_nir
        time.sleep(delay)
    for k in vals:
        vals[k] /= n
    return vals

def main():
    parser = argparse.ArgumentParser(description="FRAD AS7341 calibration wizard")
    parser.add_argument("--out", required=True, help="Output calibration JSON file")
    parser.add_argument("--it", type=int, default=100, help="Integration time ms (default=100)")
    parser.add_argument("--gain", type=int, default=4, help="Gain multiplier (default=4)")
    parser.add_argument("--samples", type=int, default=10, help="Samples to average (default=10)")
    args = parser.parse_args()

    # Init sensor
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor = AS7341(i2c)
    sensor.integration_time = args.it
    sensor.gain = args.gain

    print("FRAD Calibration Wizard")
    print(f"Settings: IT={args.it} ms, gain={args.gain}, avg {args.samples} samples\n")

    # Step 1: Dark reference
    input("Cover the sensor completely (dark). Press Enter to capture...")
    dark_vals = read_average(sensor, n=args.samples)
    print("Dark reference captured:", dark_vals, "\n")

    # Step 2: White reference
    input("Place sensor against white card under full light. Press Enter to capture...")
    white_vals = read_average(sensor, n=args.samples)
    print("White reference captured:", white_vals, "\n")

    # Compute calibration
    cal = {}
    for ch in CHANNELS:
        offset = dark_vals[ch]
        span = max(white_vals[ch] - offset, 1e-6)  # avoid div/0
        scale = 1.0 / span
        cal[ch] = {"offset": offset, "scale": scale}

    # Save
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cal, f, indent=2)

    print(f" Calibration complete! Written → {out_path}")
    print(json.dumps(cal, indent=2))

if __name__ == "__main__":
    main()
