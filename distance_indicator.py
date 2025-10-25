#usr/bin/env python3
import glob
import pandas as pd
import numpy as np

# Tunables
BASE_N = 5      # how many initial samples are baseline (no fruit)
FRUIT_N = 5      # how many final samples are with fruit
MIN_DELTA = 0.20  # require >=30% CLEAR increase to say "fruit present"
MAX_JUMP = 4.0   # if CLEAR fruit/baseline > 4x, call it "too close/glare"
SAT_PCTL = 98.0  # glare if any channel in fruit window > this percentile of file

CHANNELS = ["F1","F2","F3","F4","F5","F6","F7","F8","CLEAR","NIR"]

def latest_index():
    files = sorted(glob.glob("out/index_*.csv"))
    if not files:
        raise SystemExit("No out/index_*.csv files. Run frad_app.py first.")
    return files[-1]

def judge(df):
    cols = [c for c in CHANNELS if c in df.columns]
    if "CLEAR" not in cols:
        raise SystemExit("CSV missing CLEAR column.")

    base = df.iloc[:BASE_N].copy()
    fruit = df.iloc[-FRUIT_N:].copy()

    clear_base = float(np.median(base["CLEAR"]))
    clear_fruit = float(np.median(fruit["CLEAR"]))
    ratio = clear_fruit / max(1e-9, clear_base)

    glare = False
    if cols:
        highs = df[cols].quantile(SAT_PCTL/100.0)
        fruit_highs = fruit[cols].max()
        glare = any(fruit_highs[c] >= highs[c] for c in cols)

    verdict = "good"
    reason = []

    if ratio < (1.0 + MIN_DELTA):
        verdict = "no fruit / too far"
        reason.append("CLEAR increase only %.2fx" % ratio)
    elif ratio > MAX_JUMP or glare:
        verdict = "too close / glare"
        if ratio > MAX_JUMP:
            reason.append("CLEAR jump %.1fx" % ratio)
        if glare:
            reason.append(">%gth percentile in fruit window" % SAT_PCTL)
    else:
        reason.append("CLEAR increase %.2fx" % ratio)

    return verdict, " ; ".join(reason), clear_base, clear_fruit

def main():
    path = latest_index()
    print("Using:", path)
    df = pd.read_csv(path)
    verdict, why, base_clear, fruit_clear = judge(df)
    print("Verdict:", verdict)
    print("Why:", why)
    print("Baseline CLEAR (median of first %d): %.1f" % (BASE_N, base_clear))
    print("Fruit     CLEAR (median of last  %d): %.1f" % (FRUIT_N, fruit_clear))

if __name__ == "__main__":
    main()


