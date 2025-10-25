#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FRAD Evaluator

- Loads decision rules from cal/apple_cal.json ("decision.rules")
- Classifies all CSV rows in:
    out/green_fresh/d*/*.csv   (ground truth = fresh -> should be 'ripe')
    out/green_bad/d*/*.csv     (ground truth = bad   -> should be 'unripe')
- Prints overall accuracy, confusion matrix, per-distance breakdown.
- Optionally writes a JSON report via --json-out.

Usage:
  python3 evaluator.py
  python3 evaluator.py --json-out out/eval_report.json
  python3 evaluator.py --fresh-glob "out/green_fresh/d*/*.csv" --bad-glob "out/green_bad/d*/*.csv"
"""

import argparse, csv, glob, json, os, sys
from collections import defaultdict, Counter
from pathlib import Path

# ---------- rules / classification ----------

def load_rules(cal_path="cal/apple_cal.json"):
    with open(cal_path) as f:
        cal = json.load(f)
    dec = cal.get("decision", {})
    rules = dec.get("rules", [])
    fallback = dec.get("fallback", "unripe")
    return rules, fallback

def apply_rule(val, op, thr):
    try:
        x = float(val)
    except Exception:
        return False
    if op == ">=": return x >= thr
    if op == "<=": return x <= thr
    if op == ">":  return x >  thr
    if op == "<":  return x <  thr
    if op == "between":
        lo, hi = sorted(thr) if isinstance(thr, (list, tuple)) else (thr, thr)
        return lo <= x <= hi
    return False

def classify_row(row, rules, fallback):
    votes = []
    for r in rules:
        idx = r.get("index")
        op  = r.get("op")
        thr = r.get("value")
        vote = r.get("vote", "ripe")
        if idx in row and row[idx] not in ("", None):
            try:
                t = float(thr) if not isinstance(thr, (list, tuple)) else thr
            except Exception:
                t = thr
            if apply_rule(row[idx], op, t):
                votes.append(vote)
    return (Counter(votes).most_common(1)[0][0] if votes else fallback).lower()

# ---------- evaluation ----------

def score_paths(paths, truth_label, rules, fallback):
    """
    truth_label: 'fresh' or 'bad'
      - 'fresh' rows should classify as 'ripe'
      - 'bad'   rows should classify as 'unripe'
    """
    assert truth_label in ("fresh","bad")
    want = "ripe" if truth_label == "fresh" else "unripe"

    tp = tn = fp = fn = 0
    nrows = 0
    misfiles = []
    per_dist = defaultdict(lambda: {"tp":0,"tn":0,"fp":0,"fn":0,"n":0})

    def dist_from_path(p):
        # pull d10mm/d20mm/d30mm (or anything like that) from path if present
        parts = Path(p).parts
        for part in parts:
            if part.startswith("d") and part.endswith("mm"):
                return part
        return "unknown"

    for p in paths:
        with open(p, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            continue
        ok_file = True
        for row in rows:
            pred = classify_row(row, rules, fallback)
            is_correct = (pred == want)
            nrows += 1

            dkey = dist_from_path(p)
            per_dist[dkey]["n"] += 1

            if want == "ripe":   # fresh
                if pred == "ripe":
                    tp += 1; per_dist[dkey]["tp"] += 1
                else:
                    fn += 1; per_dist[dkey]["fn"] += 1; ok_file = False
            else:                # bad
                if pred == "ripe":
                    fp += 1; per_dist[dkey]["fp"] += 1; ok_file = False
                else:
                    tn += 1; per_dist[dkey]["tn"] += 1

        if not ok_file:
            misfiles.append(p)

    return {"tp":tp,"tn":tn,"fp":fp,"fn":fn,"n":nrows,
            "per_distance":per_dist, "misfiles":misfiles}

def percent(x, y):
    return (100.0 * x / y) if y else 0.0

def print_confusion(title, S, want_label):
    print(f"\n{title}")
    n = S["n"]
    tp, tn, fp, fn = S["tp"], S["tn"], S["fp"], S["fn"]
    acc = percent(tp+tn, n)
    print(f"  n={n}  acc={acc:.2f}%")
    print("  Confusion:")
    if want_label == "ripe":
        print(f"    TP (ripe←fresh): {tp}")
        print(f"    FN (unripe←fresh): {fn}")
        print(f"    FP (ripe←bad):    {fp}")
        print(f"    TN (unripe←bad):  {tn}")
    else:
        print(f"    TN (unripe←bad):  {tn}")
        print(f"    FP (ripe←bad):    {fp}")
        print(f"    FN (unripe←fresh):{fn}")
        print(f"    TP (ripe←fresh):  {tp}")

def print_per_distance(per_dist, truth_label):
    if not per_dist: return
    print("\n  Per-distance:")
    for d, M in sorted(per_dist.items()):
        n = M["n"]; acc = percent(M.get("tp",0)+M.get("tn",0), n)
        print(f"    {d:8s}  n={n:3d}  acc={acc:6.2f}%  (tp={M.get('tp',0)} tn={M.get('tn',0)} fp={M.get('fp',0)} fn={M.get('fn',0)})")

# ---------- CLI ----------

def parse_args():
    ap = argparse.ArgumentParser(description="Evaluate FRAD thresholds over fresh/bad datasets.")
    ap.add_argument("--cal", default="cal/apple_cal.json", help="Calibration JSON with decision rules")
    ap.add_argument("--fresh-glob", default="out/green_fresh/d*/*.csv", help="Glob for fresh CSVs")
    ap.add_argument("--bad-glob",   default="out/green_bad/d*/*.csv",   help="Glob for bad CSVs")
    ap.add_argument("--json-out", help="Optional JSON report path")
    return ap.parse_args()

def main():
    args = parse_args()
    rules, fallback = load_rules(args.cal)

    fresh_paths = sorted(glob.glob(args.fresh_glob))
    bad_paths   = sorted(glob.glob(args.bad_glob))

    if not fresh_paths:
        print(f"[WARN] No fresh files matched: {args.fresh_glob}")
    if not bad_paths:
        print(f"[WARN] No bad files matched:   {args.bad_glob}")

    Sf = score_paths(fresh_paths, "fresh", rules, fallback)
    Sb = score_paths(bad_paths,   "bad",   rules, fallback)

    Nf, Nb = Sf["n"], Sb["n"]
    overall_n = Nf + Nb
    overall_acc = percent(Sf["tp"] + Sb["tn"], overall_n)

    # Print report
    print_confusion("Fresh set (truth=fresh, want ripe)", Sf, want_label="ripe")
    print_per_distance(Sf["per_distance"], "fresh")

    print_confusion("Bad set (truth=bad, want unripe)", Sb, want_label="unripe")
    print_per_distance(Sb["per_distance"], "bad")

    print(f"\n== Overall ==")
    print(f"  total={overall_n}  accuracy={overall_acc:.2f}%")
    if Sf["misfiles"] or Sb["misfiles"]:
        print("\nMisclassified files (any row wrong):")
        for p in sorted(set(Sf["misfiles"] + Sb["misfiles"])):
            print("  -", p)

    # Optional JSON
    if args.json_out:
        out = {
            "cal": args.cal,
            "fresh_glob": args.fresh_glob,
            "bad_glob": args.bad_glob,
            "fresh": Sf,
            "bad": Sb,
            "overall": {
                "n": overall_n,
                "accuracy_pct": overall_acc
            }
        }
        # convert defaultdicts for JSON
        def fix(obj):
            if isinstance(obj, defaultdict):
                return {k:fix(v) for k,v in obj.items()}
            return obj
        out["fresh"]["per_distance"] = fix(out["fresh"]["per_distance"])
        out["bad"]["per_distance"]   = fix(out["bad"]["per_distance"])
        Path(os.path.dirname(args.json_out) or ".").mkdir(parents=True, exist_ok=True)
        with open(args.json_out, "w") as f:
            json.dump(out, f, indent=2)
        print(f"\n[OK] JSON report written → {args.json_out}")

if __name__ == "__main__":
    main()
