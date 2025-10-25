#!/usr/bin/env python3
import argparse, csv, math, json, sys
from statistics import mean, pstdev

INDEX_KEYS = ['y_over_g', 'r_over_g', 'nir_over_red', 'green_drop']

# Repeatability (CV) targets
CV_THRESH = {'r_over_g': 0.10, 'nir_over_red': 0.15, 'green_drop': 0.15, 'y_over_g': 0.15}

# Separation (Δ) targets — now includes y_over_g
DELTA_THRESH = {'r_over_g': 1.2, 'nir_over_red': 0.10, 'green_drop': 0.08, 'y_over_g': 0.10}

def read_index_row(path):
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        row = next(reader, None)
        if not row:
            raise ValueError(f'No data row in {path}')
        vals = {}
        for k in INDEX_KEYS:
            try:
                vals[k] = float(row.get(k, 'nan'))
            except Exception:
                vals[k] = float('nan')
        vals['__file__'] = str(path)
        vals['label'] = row.get('label', '')
        return vals

def collect(files):
    vals = []
    for p in files:
        try:
            vals.append(read_index_row(p))
        except Exception as e:
            print(f'[WARN] Skipping {p}: {e}', file=sys.stderr)
    if not vals:
        raise SystemExit('[ERR] No valid index rows found.')
    return vals

def cv(values):
    if len(values) <= 1:
        return float('nan')
    m = mean(values)
    if m == 0:
        return float('nan')
    return pstdev(values) / m

def fmt_pct(x):
    return 'nan' if (x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))) else f'{x*100:.1f}%%'

def fmt_num(x):
    return 'nan' if (x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))) else f'{x:.3f}'

def repeatability(files, spot_name):
    rows = collect(files)
    series = {k: [r[k] for r in rows if not math.isnan(r[k])] for k in INDEX_KEYS}
    report = {'mode': 'repeatability', 'spot': spot_name, 'n': len(rows), 'metrics': {}, 'files': [r['__file__'] for r in rows]}
    print(f"\nRepeatability on '{spot_name}' (n={len(rows)} runs)")
    for k, vals in series.items():
        if not vals:
            print(f'  {k}: no data')
            report['metrics'][k] = {'mean': None, 'cv': None, 'pass': False}
            continue
        m = mean(vals)
        c = cv(vals)
        thr = CV_THRESH.get(k, 0.15)
        ok = (c <= thr) if (not math.isnan(c)) else False
        print(f"  {k:12s}  mean={fmt_num(m):>7}   CV={fmt_pct(c):>6}   {'✅' if ok else '❌'}  (≤ {int(thr*100)}%)")
        report['metrics'][k] = {'mean': m, 'cv': c, 'pass': ok, 'threshold': thr}
    return report

def separation(files_A, files_B, name_A, name_B):
    rowsA = collect(files_A)
    rowsB = collect(files_B)
    meanA = {k: mean([r[k] for r in rowsA if not math.isnan(r[k])]) if any(not math.isnan(r[k]) for r in rowsA) else float('nan') for k in INDEX_KEYS}
    meanB = {k: mean([r[k] for r in rowsB if not math.isnan(r[k])]) if any(not math.isnan(r[k]) for r in rowsB) else float('nan') for k in INDEX_KEYS}
    report = {'mode': 'separation', 'A': {'name': name_A, 'n': len(rowsA)}, 'B': {'name': name_B, 'n': len(rowsB)}, 'deltas': {}}
    print(f"\nSeparation {name_A} (n={len(rowsA)})  vs  {name_B} (n={len(rowsB)})")
    for k in INDEX_KEYS:
        a = meanA[k]; b = meanB[k]
        d = abs(a - b) if (not math.isnan(a) and not math.isnan(b)) else float('nan')
        thr = DELTA_THRESH.get(k, None)
        ok = (d >= thr) if (thr is not None and not math.isnan(d)) else False
        thr_str = f'≥ {thr:.2f}' if thr is not None else ''
        print(f"  Δ{k:10s}  {fmt_num(d):>7}   {'✅' if ok else '❌'}  {thr_str:>8}    (A={fmt_num(a)}, B={fmt_num(b)})")
        report['deltas'][k] = {'delta': d, 'pass': ok, 'threshold': thr, 'mean_A': a, 'mean_B': b}
    return report

def main():
    parser = argparse.ArgumentParser(description='FRAD stability (CV) and separation (Δ) checker for index CSVs.')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_rep = sub.add_parser('repeat', help='Compute CV for one spot across multiple index CSV files')
    p_rep.add_argument('spot', help='Name for this spot (e.g., green_spot)')
    p_rep.add_argument('files', nargs='+', help='Index CSV files for repeated runs of the same spot')
    p_rep.add_argument('--json-out', default='repeatability_summary.json', help='Path to write JSON summary')

    p_sep = sub.add_parser('sep', help='Compute Δ between two groups of index CSV files')
    p_sep.add_argument('--A-name', default='A', help='Name for group A')
    p_sep.add_argument('--B-name', default='B', help='Name for group B')
    p_sep.add_argument('--json-out', default='separation_summary.json', help='Path to write JSON summary')
    p_sep.add_argument('A_files', nargs='+', help='Index CSV files for group A (e.g., green spot runs)')
    p_sep.add_argument('--', dest='sep_marker', nargs=0)  # visual separator
    p_sep.add_argument('B_files', nargs='+', help='Index CSV files for group B (e.g., brown/red spot runs)')

    args = parser.parse_args()

    if args.cmd == 'repeat':
        rep = repeatability(args.files, args.spot)
        with open(args.json_out, 'w') as jf:
            json.dump(rep, jf, indent=2)
        print(f"\n[OK] JSON summary written → {args.json_out}")
    elif args.cmd == 'sep':
        rep = separation(args.A_files, args.B_files, args.A_name, args.B_name)
        with open(args.json_out, 'w') as jf:
            json.dump(rep, jf, indent=2)
        print(f"\n[OK] JSON summary written → {args.json_out}")
    else:
        print('[ERR] Unknown command.')

if __name__ == '__main__':
    main()
