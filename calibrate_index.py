#!/usr/bin/env python3
"""
calibrate_index.py

Applies calibration constants to normalized AS7341 data.
Each fruit type can have its own calibration file (JSON) with offsets and scales.

Usage:
  python3 calibrate_index.py --in norm.csv --out cal.csv --cal cal/banana_cal.json
"""

import argparse
import json
import pandas as pd
from pathlib import Path

def load_calibration(cal_path: Path) -> dict:
    """Load calibration constants from a JSON file."""
    with open(cal_path, "r", encoding="utf-8") as f:
        return json.load(f)

def apply_calibration(df: pd.DataFrame, cal: dict) -> pd.DataFrame:
    """
    Apply calibration constants (offset, scale) to each channel.
    Expected cal format:
    {
      "F1": {"offset": 0.0, "scale": 1.0},
      "F2": {"offset": 0.0, "scale": 1.0},
      ...
    }
    """
    out = df.copy()
    for band, params in cal.items():
        if band in out.columns:
            offset = params.get("offset", 0.0)
            scale = params.get("scale", 1.0)
            out[band] = (out[band] - offset) * scale
    return out

def main():
    parser = argparse.ArgumentParser(description="Apply calibration to normalized AS7341 data")
    parser.add_argument("--in", dest="inp", required=True, help="Input normalized CSV")
    parser.add_argument("--out", required=True, help="Output calibrated CSV")
    parser.add_argument("--cal", dest="cal", required=True, help="Calibration JSON file")
    args = parser.parse_args()

    df = pd.read_csv(args.inp)
    cal = load_calibration(Path(args.cal))

    df_cal = apply_calibration(df, cal)
    df_cal.to_csv(args.out, index=False)

    print(f" Calibrated data written to {args.out} using {args.cal}")

if __name__ == "__main__":
    main()
