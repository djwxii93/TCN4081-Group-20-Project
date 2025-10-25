#!/usr/bin/env python3
"""
OLD VERSION – ripeness_score.py

Classifies ripeness using hardcoded thresholds.
"""

import argparse
import json
import pandas as pd

def main():
    parser = argparse.ArgumentParser(description="Ripeness scoring")
    parser.add_argument("--in", dest="inp", required=True, help="Input index CSV")
    parser.add_argument("--out", dest="out", required=True, help="Output JSON file")
    args = parser.parse_args()

    # Read the last row of index data
    df = pd.read_csv(args.inp)
    latest = df.iloc[-1].to_dict()

    # Hardcoded rules (example: bananas)
    RI1 = latest.get("RI1", 0)
    RI2 = latest.get("RI2", 0)

    if RI1 > 1.2 and RI2 < 0.35:
        label = "ripe"
        confidence = 0.85
    else:
        label = "unripe"
        confidence = 0.6

    result = {"label": label, "confidence": confidence}

    # Save to JSON
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Ripeness score written to {args.out}")
    print(result)

if __name__ == "__main__":
    main()
