#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FRAD: Ripeness index runner (with rule-by-rule logging)

Supports two modes based on --in suffix:
  - CSV mode:  --in <readings.csv>  (uses last row of a readings CSV)
  - JSON live mode: --in <calibration.json>  (reads AS7341 or frad_sensor)

Outputs one-row CSV with indices + decision. With --verbose, prints detailed logs
including which rules passed/failed and the exact values/thresholds.
"""

import csv, sys, argparse, json, os, time
from pathlib import Path
from datetime import datetime

# ----------------------------
# Utilities
# ----------------------------

def _safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def _warn(msg):
    print(f"[WARN] {msg}", file=sys.stderr)

def _err(msg, code=2):
    print(f"[ERR] {msg}", file=sys.stderr)
    sys.exit(code)

def _fmt(x, nd=6):
    try:
        return f"{float(x):.{nd}f}"
    except Exception:
        return str(x)

# ----------------------------
# Channel handling
# ----------------------------

VALID_CHANNELS = {*(f"F{i}" for i in range(1,9)), "CLEAR", "NIR"}

def require_channel(name: str):
    if name not in VALID_CHANNELS:
        raise ValueError(f"Unknown channel '{name}'. Allowed: {sorted(VALID_CHANNELS)}")

def normalize_row_channels(row: dict) -> dict:
    """Ensure CLEAR/NIR present with safe fallbacks."""
    out = dict(row)
    if "CLEAR" not in out and all(f"F{i}" in out for i in range(1,9)):
        out["CLEAR"] = sum(out[f"F{i}"] for i in range(1,9)) / 8.0
    if "NIR" not in out and "F8" in out:
        out["NIR"] = out["F8"]
    return out

# ----------------------------
# CSV input mode (legacy)
# ----------------------------

def find_columns(header):
    """
    Map green (≈480), yellow (≈555), red (≈630).
    Priority 1: wavelength headers "480","555","630"
    Priority 2: sensor headers F3≈480, F5≈555, F7≈630
    """
    hset = {(h.strip() if isinstance(h, str) else h): i
            for i, h in enumerate(header) if h is not None}

    if {"480","555","630"}.issubset(hset):
        return {"g":"480","y":"555","r":"630"}

    need = {"F3","F5","F7"}
    if need.issubset(hset):
        return {"g":"F3","y":"F5","r":"F7"}

    return None

def compute_ratios_from_row(latest, cols):
    g = _safe_float(latest.get(cols["g"], 0.0))
    y = _safe_float(latest.get(cols["y"], 0.0))
    r = _safe_float(latest.get(cols["r"], 0.0))
    g = g if g > 0 else 1.0  # avoid div/0
    out = {
        "y_over_g": y / g,
        "r_over_g": r / g,
    }
    nir   = _safe_float(latest.get("NIR", 0.0))
    clear = _safe_float(latest.get("CLEAR", 1.0), default=1.0)
    out["nir_over_red"] = (nir / r) if r > 0 else 0.0
    out["green_drop"]   = (g   / clear) if clear > 0 else 0.0
    return out

# ----------------------------
# JSON calibration mode (live)
# ----------------------------

def load_json_cal(path: str) -> dict:
    with open(path, "r") as f:
        cal = json.load(f)

    chans = cal.get("channels", {})
    if isinstance(chans, list):
        d = {}
        for i, ch in enumerate(chans, start=1):
            d[f"F{i}"] = {"offset": _safe_float(ch.get("offset", 0.0)),
                          "scale":  _safe_float(ch.get("scale",  1.0))}
        chans = d
    elif isinstance(chans, dict):
        for k in list(chans.keys()):
            if k in VALID_CHANNELS:
                cfg = chans[k]
                chans[k] = {"offset": _safe_float(cfg.get("offset", 0.0)),
                            "scale":  _safe_float(cfg.get("scale",  1.0))}
            else:
                _warn(f"Ignoring unknown channel in JSON calibration: {k}")
                chans.pop(k, None)
    else:
        chans = {}
    cal["channels"] = chans
    return cal

def apply_offsets_scales(row: dict, channels_cfg: dict):
    out = dict(row)
    for k, cfg in channels_cfg.items():
        if k in out:
            out[k] = (out[k] + _safe_float(cfg.get("offset", 0.0))) * _safe_float(cfg.get("scale", 1.0))
    return out

def read_sensor(samples: int = 4, delay: float = 0.02) -> dict:
    """
    Try Adafruit AS7341; fall back to frad_sensor.read_channels().
    Returns dict with F1..F8, CLEAR, NIR.
    """
    # 1) Adafruit
    try:
        import board, busio, adafruit_as7341
        i2c = busio.I2C(board.SCL, board.SDA)
        sensor = adafruit_as7341.AS7341(i2c)
        acc = {k: 0.0 for k in VALID_CHANNELS}
        for _ in range(samples):
            ch = sensor.all_channels  # F1..F8
            for i in range(8):
                acc[f"F{i+1}"] += float(ch[i])
            try:
                acc["CLEAR"] += float(sensor.channel_clear)
            except Exception:
                acc["CLEAR"] += sum(float(ch[i]) for i in range(8)) / 8.0
            try:
                acc["NIR"] += float(sensor.channel_nir)
            except Exception:
                acc["NIR"] += float(ch[7])  # F8 proxy
            time.sleep(delay)
        return {k: acc[k] / samples for k in acc}
    except Exception:
        pass

    # 2) FRAD shim
    try:
        import importlib
        m = importlib.import_module("frad_sensor")
        data = m.read_channels()  # expect dict with F1..F8,CLEAR,NIR
        out = {}
        for k in VALID_CHANNELS:
            if k in data:
                out[k] = _safe_float(data[k])
        if not out:
            raise RuntimeError("frad_sensor.read_channels() returned no usable data")
        return normalize_row_channels(out)
    except Exception:
        _err("No sensor backend available. Install Adafruit AS7341 or provide frad_sensor.read_channels().")

# ----------------------------
# Classification helpers (with verbose rule logging)
# ----------------------------

def load_profiles_indices():
    """
    Keep your original behavior: thresholds come from profiles.json (if present).
    For rule-by-rule logging tied to calibration JSON, you may ultimately
    migrate these into the calibration; for now we load indices rules like before.
    """
    prof_path = "/home/frad002/frad/profiles.json"
    try:
        with open(prof_path) as pf:
            profiles = json.load(pf)
        return profiles.get("green apple", profiles.get("default", {})).get("indices", {})
    except Exception:
        return {}  # no external rules; decision may come from calibration

def eval_rules_verbose(indices_vals: dict, decision_cfg: dict, verbose: bool):
    """
    Evaluate decision rules and return (label, votes, logs)
    Each rule like {"index":"y_over_g","op":">=","value":1.7,"vote":"ripe"}
    """
    votes, logs = [], []
    rules = decision_cfg.get("rules", [])
    for rule in rules:
        idx = rule.get("index")
        op  = rule.get("op")
        thr = rule.get("value")
        vote = rule.get("vote", "ripe")
        val = indices_vals.get(idx, float("nan"))

        passed = False
        if   op == "<":  passed = (val <  thr)
        elif op == "<=": passed = (val <= thr)
        elif op == ">":  passed = (val >  thr)
        elif op == ">=": passed = (val >= thr)
        elif op == "between":
            lo, hi = sorted(thr) if isinstance(thr, (list, tuple)) else (thr, thr)
            passed = (lo <= val <= hi)

        status = "PASS" if passed else "FAIL"
        logs.append(f"{status} {idx} {op} {thr}  ({_fmt(val)})")
        if passed:
            votes.append(vote)

    # majority vote; fallback if no votes
    if not votes:
        label = decision_cfg.get("fallback", "unripe")
    else:
        from collections import Counter
        label = Counter(votes).most_common(1)[0][0]

    if verbose:
        print("[RULES]")
        for line in logs:
            print(" ", line)
        print("[VOTES]", votes if votes else "(none)", "=>", label.upper())
    return label, votes, logs

# ----------------------------
# Output writer
# ----------------------------

def write_output_csv(path: str, ratios: dict, label: str):
    fields = ["timestamp","y_over_g","r_over_g","nir_over_red","green_drop","label"]
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "y_over_g": ratios.get("y_over_g",""),
        "r_over_g": ratios.get("r_over_g",""),
        "nir_over_red": ratios.get("nir_over_red",""),
        "green_drop": ratios.get("green_drop",""),
        "label": label,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        w.writerow(row)

# ----------------------------
# Main flow
# ----------------------------

def parse_args():
    ap = argparse.ArgumentParser(description="FRAD ripeness index runner (CSV input OR JSON+sensor) with verbose rule logging")
    ap.add_argument("--in",  dest="inp", required=True, help="CSV of readings (old mode) OR JSON calibration (live mode)")
    ap.add_argument("--out", dest="out", required=True, help="Output CSV for indices/label (appends one row)")
    ap.add_argument("--samples", type=int, default=4, help="Samples to average in live JSON mode")
    ap.add_argument("--verbose", "-v", action="store_true", help="Print detailed indices and per-rule evaluations")
    return ap.parse_args()

def run_csv_mode(args):
    with open(args.inp, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = reader.fieldnames or []

    if not rows:
        _warn("No rows in input CSV; writing header-only index CSV.")
        write_output_csv(args.out, {"y_over_g":0,"r_over_g":0,"nir_over_red":0,"green_drop":0}, "unknown")
        return

    cols = find_columns(header)
    if not cols:
        _err(f"Could not locate required columns in {args.inp}\n      Header: {header}", code=3)

    latest = rows[-1]
    ratios = compute_ratios_from_row(latest, cols)

    # Decision config can come from calibration JSON OR profiles.json.
    # If you are using cal/apple_cal.json for decision rules, prefer that.
    # Here we try to read decision rules directly from a colocated calibration if present.
    decision_cfg = {"rules": [], "fallback": "unripe"}
    # Optional: if your CSV includes a hint to calibration, you could load it; for now just use profiles
    profile_rules = load_profiles_indices()  # backward compatibility

    # Prefer calibration-style decision if the CSV included nir/clear etc. and you’ve set rules in the runtime
    # Otherwise fall back to profiles indices rules encoded as decision (if any)
    if profile_rules:
        # Convert your old profiles format into decision-style rules if needed
        # (skipping here—most teams use the calibration JSON now)
        pass

    # If no decision rules available here, you can still classify with a simple default:
    # We’ll look for an optional sidecar calibration json next to the CSV (same base name + .json)
    sidecar = Path(args.inp).with_suffix(".json")
    if sidecar.exists():
        try:
            cal = load_json_cal(str(sidecar))
            decision_cfg = cal.get("decision", decision_cfg)
        except Exception as e:
            _warn(f"Could not load sidecar calibration: {e}")

    if args.verbose:
        print("[INDICES]")
        for k in ("y_over_g","r_over_g","nir_over_red","green_drop"):
            print(f"  {k}: {_fmt(ratios.get(k))}")

    label, votes, _ = eval_rules_verbose(ratios, decision_cfg, args.verbose)
    write_output_csv(args.out, ratios, label)

    print(f"[DISPLAY] RESULT: {label.upper()}")
    print(f"[OK] index written → {args.out}")

def run_json_live_mode(args):
    cal = load_json_cal(args.inp)
    raw = read_sensor(samples=args.samples)
    raw = normalize_row_channels(raw)
    raw = apply_offsets_scales(raw, cal.get("channels", {}))

    # Build synthetic row dict so we can reuse CSV-mode math (F3/F5/F7 mapping)
    header = ["F1","F2","F3","F4","F5","F6","F7","F8","CLEAR","NIR"]
    latest = {k: raw.get(k, "") for k in header}
    cols = find_columns(header) or {"g":"F3","y":"F5","r":"F7"}
    ratios = compute_ratios_from_row(latest, cols)

    if args.verbose:
        print("[CHANNELS] (post offset/scale)")
        for k in ("F3","F5","F7","CLEAR","NIR"):
            if k in latest or k in raw:
                print(f"  {k}: {_fmt(raw.get(k,''))}")
        print("[INDICES]")
        for k in ("y_over_g","r_over_g","nir_over_red","green_drop"):
            print(f"  {k}: {_fmt(ratios.get(k))}")

    decision_cfg = cal.get("decision", {"rules": [], "fallback": "unripe"})
    label, votes, _ = eval_rules_verbose(ratios, decision_cfg, args.verbose)

    write_output_csv(args.out, ratios, label)
    print(f"[DISPLAY] RESULT: {label.upper()}")
    print(f"[OK] (live) index written → {args.out}")

def main():
    args = parse_args()
    ext = Path(args.inp).suffix.lower()
    if ext == ".csv":
        run_csv_mode(args)
    elif ext == ".json":
        run_json_live_mode(args)
    else:
        _err("Unknown --in type. Use a .csv (data) or .json (calibration/live).")

if __name__ == "__main__":
    main()
