#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Auto-tune FRAD thresholds from existing CSVs.

- Loads CSVs:
    fresh: out/green_fresh/d*/*.csv
    bad:   out/green_bad/d*/*.csv
- Grid-searches cutoffs for y_over_g (>=), r_over_g (>=), and optionally nir_over_red (<=).
- Objective: maximize overall accuracy; tie-breaker: minimize FP on bad apples.
- Prints best thresholds + confusion matrix + per-distance breakdown.
- Optionally writes the best thresholds into cal/apple_cal.json.

Usage:
  python3 evaluator_autotune.py
  python3 evaluator_autotune.py --use-nir
  python3 evaluator_autotune.py --write-cal
  python3 evaluator_autotune.py --fresh-glob "out/green_fresh/d20mm/*.csv" --bad-glob "out/green_bad/d20mm/*.csv"
"""

import argparse, csv, glob, json, math
from collections import defaultdict, Counter
from pathlib import Path

IDX_KEYS = ("y_over_g","r_over_g","nir_over_red")

# ------------------------ IO ------------------------

def read_rows(globpat):
    rows = []
    for p in glob.glob(globpat):
        with open(p, newline="") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                row["_file"] = p
                rows.append(row)
    return rows

def dist_from_path(p: str) -> str:
    parts = Path(p).parts
    for part in parts:
        if part.startswith("d") and part.endswith("mm"):
            return part
    return "unknown"

# ------------------------ Scoring ------------------------

def classify(row, thr, use_nir=False, fallback="unripe"):
    votes=[]
    y = float(row.get("y_over_g","nan"))
    r = float(row.get("r_over_g","nan"))
    if math.isfinite(y) and y >= thr["y_over_g"]: votes.append("ripe")
    if math.isfinite(r) and r >= thr["r_over_g"]: votes.append("ripe")
    if use_nir:
        n = float(row.get("nir_over_red","nan"))
        if math.isfinite(n) and n <= thr["nir_over_red"]: votes.append("ripe")
    return (Counter(votes).most_common(1)[0][0] if votes else fallback)

def evaluate(fresh_rows, bad_rows, thr, use_nir=False):
    # fresh should be "ripe"; bad should be "unripe"
    tp=tn=fp=fn=0
    per_dist = defaultdict(lambda: {"tp":0,"tn":0,"fp":0,"fn":0,"n":0})
    misfiles=set()

    def upd(row, truth):
        nonlocal tp,tn,fp,fn
        pred = classify(row, thr, use_nir)
        dkey = dist_from_path(row["_file"])
        per_dist[dkey]["n"] += 1

        ok_file=True
        if truth == "fresh":
            if pred == "ripe":
                tp+=1; per_dist[dkey]["tp"]+=1
            else:
                fn+=1; per_dist[dkey]["fn"]+=1; ok_file=False
        else:
            if pred == "ripe":
                fp+=1; per_dist[dkey]["fp"]+=1; ok_file=False
            else:
                tn+=1; per_dist[dkey]["tn"]+=1
        if not ok_file: misfiles.add(row["_file"])

    for r in fresh_rows: upd(r,"fresh")
    for r in bad_rows:   upd(r,"bad")

    n = tp+tn+fp+fn
    acc = (tp+tn)/n if n else 0.0
    return {"tp":tp,"tn":tn,"fp":fp,"fn":fn,"n":n,"acc":acc,
            "per_distance": per_dist, "misfiles": sorted(misfiles)}

# ------------------------ Search space ------------------------

def quantiles(vals, qlist):
    if not vals: return [float("nan")]*len(qlist)
    xs=sorted(vals); n=len(xs)
    out=[]
    for q in qlist:
        i=(n-1)*q; lo=int(i); hi=min(lo+1,n-1); t=i-lo
        out.append(xs[lo]*(1-t)+xs[hi]*t)
    return out

def build_candidates(fresh_rows, bad_rows, use_nir):
    def pull(idx, rows):
        out=[]
        for r in rows:
            try: out.append(float(r[idx]))
            except: pass
        return out

    Fy = pull("y_over_g", fresh_rows); By = pull("y_over_g", bad_rows)
    Fr = pull("r_over_g", fresh_rows); Br = pull("r_over_g", bad_rows)
    Fn = pull("nir_over_red", fresh_rows); Bn = pull("nir_over_red", bad_rows)

    # y_over_g & r_over_g: fresh > bad, so threshold is >=
    # candidates near between-class region + a bit of margin
    q = [0.05,0.10,0.20,0.30,0.40,0.50,0.60,0.70,0.80,0.90,0.95]
    Fyq, Byq = quantiles(Fy,q), quantiles(By,q)
    Frq, Brq = quantiles(Fr,q), quantiles(Br,q)

    y_cands = sorted(set([
        (Fyq[1]+Byq[9])/2, (Fyq[2]+Byq[8])/2, (Fyq[3]+Byq[7])/2,
        (sum(Fy)/len(Fy)+sum(By)/len(By))/2 if Fy and By else float("nan")
    ] + [v for v in Fyq[1:4]+Byq[7:10] if math.isfinite(v)]))
    r_cands = sorted(set([
        (Frq[1]+Brq[9])/2, (Frq[2]+Brq[8])/2, (Frq[3]+Brq[7])/2,
        (sum(Fr)/len(Fr)+sum(Br)/len(Br))/2 if Fr and Br else float("nan")
    ] + [v for v in Frq[1:4]+Brq[7:10] if math.isfinite(v)]))

    # nir_over_red: fresh < bad, so threshold is <=
    if use_nir:
        Fnq, Bnq = quantiles(Fn,q), quantiles(Bn,q)
        n_cands = sorted(set([
            (Fnq[9]+Bnq[1])/2, (Fnq[8]+Bnq[2])/2, (Fnq[7]+Bnq[3])/2,
            (sum(Fn)/len(Fn)+sum(Bn)/len(Bn))/2 if Fn and Bn else float("nan")
        ] + [v for v in Fnq[7:10]+Bnq[1:4] if math.isfinite(v)]))
    else:
        n_cands = []

    # prune NaNs
    y_cands=[x for x in y_cands if math.isfinite(x)]
    r_cands=[x for x in r_cands if math.isfinite(x)]
    n_cands=[x for x in n_cands if math.isfinite(x)]
    return y_cands, r_cands, n_cands

# ------------------------ Main ------------------------

def parse_args():
    ap = argparse.ArgumentParser(description="Auto-tune FRAD thresholds from CSVs.")
    ap.add_argument("--fresh-glob", default="out/green_fresh/d*/*.csv")
    ap.add_argument("--bad-glob",   default="out/green_bad/d*/*.csv")
    ap.add_argument("--use-nir", action="store_true", help="Include nir_over_red in the search (requires fixed standoff)")
    ap.add_argument("--write-cal", action="store_true", help="Write best thresholds into cal/apple_cal.json")
    ap.add_argument("--cal", default="cal/apple_cal.json")
    return ap.parse_args()

def main():
    args = parse_args()

    fresh_rows = read_rows(args.fresh_glob)
    bad_rows   = read_rows(args.bad_glob)

    if not fresh_rows or not bad_rows:
        print("[ERR] No data found. Check your globs.")
        print(" fresh:", args.fresh_glob, " ->", len(fresh_rows))
        print(" bad:  ", args.bad_glob,   " ->", len(bad_rows))
        return 2

    y_cands, r_cands, n_cands = build_candidates(fresh_rows, bad_rows, args.use_nir)
    if not y_cands or not r_cands:
        print("[ERR] Not enough variability to propose thresholds.")
        return 2

    best=None
    combos=0
    for y in y_cands:
        for r in r_cands:
            if args.use_nir and n_cands:
                for n in n_cands:
                    thr={"y_over_g":y, "r_over_g":r, "nir_over_red":n}
                    S=evaluate(fresh_rows,bad_rows,thr,use_nir=True)
                    combos+=1
                    score=(S["acc"], -(S["fp"]))  # maximize acc, then minimize FP
                    if best is None or score > best[0]:
                        best=(score, thr, S)
            else:
                thr={"y_over_g":y, "r_over_g":r}
                S=evaluate(fresh_rows,bad_rows,thr,use_nir=False)
                combos+=1
                score=(S["acc"], -(S["fp"]))
                if best is None or score > best[0]:
                    best=(score, thr, S)

    (_,), thr_best, Sbest = best[0:1], best[1], best[2]
    use_nir = args.use_nir and ("nir_over_red" in thr_best)

    # ---- print report ----
    def pct(x,y): return (100.0*x/y) if y else 0.0
    print(f"[OK] Searched {combos} threshold combos")
    print("\n== Best thresholds ==")
    print(f"  y_over_g >= {thr_best['y_over_g']:.4f}")
    print(f"  r_over_g >= {thr_best['r_over_g']:.4f}")
    if use_nir:
        print(f"  nir_over_red <= {thr_best['nir_over_red']:.4f}  (only if distance fixed)")

    print("\n== Overall ==")
    print(f"  n={Sbest['n']}  accuracy={pct(Sbest['tp']+Sbest['tn'], Sbest['n']):.2f}%")
    print(f"  TP={Sbest['tp']}  TN={Sbest['tn']}  FP={Sbest['fp']}  FN={Sbest['fn']}")

    print("\nPer-distance:")
    for d, M in sorted(Sbest["per_distance"].items()):
        n=M["n"]; acc=pct(M.get('tp',0)+M.get('tn',0), n)
        print(f"  {d:8s} n={n:3d} acc={acc:6.2f}%  (tp={M.get('tp',0)} tn={M.get('tn',0)} fp={M.get('fp',0)} fn={M.get('fn',0)})")

    if Sbest["misfiles"]:
        print("\nMisclassified files (any row wrong):")
        for p in Sbest["misfiles"]:
            print("  -", p)

    # Emit a ready-to-paste JSON snippet
    print("\n== Paste into cal/apple_cal.json ==")
    print('{')
    print('  "decision": {')
    print('    "rules": [')
    print(f'      {{ "index": "y_over_g", "op": ">=", "value": {thr_best["y_over_g"]:.4f}, "vote": "ripe" }},')
    print(f'      {{ "index": "r_over_g", "op": ">=", "value": {thr_best["r_over_g"]:.4f}, "vote": "ripe" }}' +
          (',' if use_nir else ''))
    if use_nir:
        print(f'      {{ "index": "nir_over_red", "op": "<=", "value": {thr_best["nir_over_red"]:.4f}, "vote": "ripe" }}')
    print('    ],')
    print('    "fallback": "unripe"')
    print('  }')
    print('}')

    # Optionally write into cal/apple_cal.json
    if args.write_cal:
        try:
            cal=json.load(open(args.cal))
        except Exception:
            cal={}
        cal.setdefault("decision",{}).setdefault("rules",[])
        rules = [
            {"index":"y_over_g","op":">=","value":float(thr_best["y_over_g"]),"vote":"ripe"},
            {"index":"r_over_g","op":">=","value":float(thr_best["r_over_g"]),"vote":"ripe"},
        ]
        if use_nir:
            rules.append({"index":"nir_over_red","op":"<=","value":float(thr_best["nir_over_red"]),"vote":"ripe"})
        cal["decision"]["rules"] = rules
        cal["decision"]["fallback"] = "unripe"
        Path(args.cal).parent.mkdir(parents=True, exist_ok=True)
        with open(args.cal,"w") as f:
            json.dump(cal,f,indent=2)
        print(f"\n[OK] Wrote best thresholds into {args.cal}")

if __name__ == "__main__":
    main()
