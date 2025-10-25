from __future__ import annotations
"""
FRAD unified driver (frad_app.py)

Now with profiles.json integration and e-paper display feedback:
- Captures photo (camera_capture.py)
- Classifies fruit (fruit_id.py)
- Loads fruit-specific profile (profiles.json)
- Runs spectral pipeline with correct IT/gain, cal file, thresholds
- Produces final JSON linking photo, spectra, and score
- Shows "SCANNING..." (landscape) with a progress bar, then RESULT on Waveshare 2.13" e-paper

PATCHED:
- Timeouts for subprocess stages (prevents "infinite normalize" symptom)
- Assert non-empty inputs/outputs around each stage
- Fix image var name (jpg_path) in final JSON
- Capture once, classify, then (optionally) re-capture with profile camera args
- Safer display handling and clearer error surfacing
- Inline normalizer fallback if as7341_norm.py times out
- Score fallback: retry without --thresholds if first call fails
- Profile-based ripeness threshold override (_apply_threshold_overrides)
- FRAD_FORCE_FRUIT override + fruit name shown on e-ink (prints UNKNOWN if unknown)
- "apple" displayed as "green apple" (profile loading remains compatible)
"""

import argparse
import csv
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from datetime import datetime
from statistics import mean
from typing import Dict, Any, Optional
from pathlib import Path

# ----------------------------
# Optional display (safe fallback)
# ----------------------------
class _NoopDisplay:
    def __init__(self, *_, **__): pass
    def show_scanning(self): print("[DISPLAY] SCANNING...")
    def show_step(self, step: int, total: int, label: str = ""): print(f"[DISPLAY] STEP {step}/{total} {label}".strip())
    def show_result(self, label: str, invert: bool = False): print(f"[DISPLAY] RESULT: {label} (invert={invert})")
    def show_message(self, top: str, bottom: str = ""): print(f"[DISPLAY] {top} {bottom}".strip())
    def clear(self): pass
    def sleep(self): pass

def _make_display(disable: bool = False, full_every: int = 15):
    if disable:
        return _NoopDisplay()
    try:
        from frad_display import EInkDisplay
        return EInkDisplay(full_every=full_every)   # landscape by default
    except Exception as e:
        print(f"[WARN] E-ink display unavailable ({e}); continuing without screen.")
        return _NoopDisplay()

# ----------------------------
# Camera + fruit ID imports
# ----------------------------
import fruit_id

# ----------------------------
# Configuration
# ----------------------------
MODE = os.environ.get("FRAD_MODE", "cli").lower()
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
LOGS_DIR = PROJECT_ROOT / "logs"
OUT_DIR = PROJECT_ROOT / "out"
CAL_DIR = PROJECT_ROOT / "cal"
PROFILE_PATH = PROJECT_ROOT / "profiles.json"

OUT_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
CAL_DIR.mkdir(exist_ok=True)

# Load profiles
if PROFILE_PATH.exists():
    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        PROFILES: Dict[str, Any] = json.load(f)
else:
    PROFILES = {}
    print("??  Warning: profiles.json not found. Using empty defaults.")

# Default command templates for CLI mode
CLI = {
    "log": [
        sys.executable,
        str(PROJECT_ROOT / "as7341_log.py"),
        "--out", "{out}",
        "--count", "{count}",
        "--it", "{it}",
        "--gain", "{gain}"
    ],
    "norm": [sys.executable, str(PROJECT_ROOT / "as7341_norm.py"), "--in", "{inp}", "--out", "{out}"],
    "cal": [
        sys.executable,
        str(PROJECT_ROOT / "calibrate_index.py"),
        "--in", "{inp}",
        "--out", "{out}",
        "--cal", "{calfile}"
    ],
    "index": [sys.executable, str(PROJECT_ROOT / "ripeness_index_run.py"), "--in", "{inp}", "--out", "{out}"],
    "score": [
        sys.executable,
        str(PROJECT_ROOT / "ripeness_score.py"),
        "--in", "{inp}",
        "--out", "{out}",
        "--thresholds", "{thresholds}"
    ]
}

# ----------------------------
# Helpers
# ----------------------------
def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _run(cmd: list[str], timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    """
    Run a subprocess command with optional timeout and unbuffered Python output for child processes.
    Raises TimeoutExpired / CalledProcessError for the caller to handle.
    """
    try:
        if cmd and cmd[0] and cmd[0].endswith(("python", "python3")) and "-u" not in cmd:
            cmd.insert(1, "-u")
    except Exception:
        pass
    print("$", " ".join(cmd))
    return subprocess.run(cmd, check=True, timeout=timeout)

def _assert_nonempty_file(p: Path, label: str):
    if not p.exists():
        raise FileNotFoundError(f"{label}: missing file -> {p}")
    if p.stat().st_size == 0:
        raise RuntimeError(f"{label}: file is empty -> {p}")

def _which_or_raise(exe: str):
    if shutil.which(exe) is None:
        raise FileNotFoundError(f"Required executable not found on PATH: {exe}")

def load_profile(fruit: str) -> dict:
    return PROFILES.get(fruit) or PROFILES.get("unknown", {})

def _canon_name(name: str) -> str:
    return (name or "").lower().replace("_", " ").strip()

def _display_name_for_fruit(fruit: str) -> str:
    """Map 'apple' to 'green apple' for display; pass through others; use 'UNKNOWN' if empty."""
    if not fruit or _canon_name(fruit) in ("", "unknown"):
        return "UNKNOWN"
    if _canon_name(fruit) == "apple":
        return "green apple"
    return fruit

def _profile_candidates_for_fruit(fruit: str):
    """
    Generate reasonable profile keys for a given fruit.
    Ensures 'green apple' displays while profiles can still be stored under 'apple'.
    """
    c = _canon_name(fruit)
    candidates = [fruit]  # as-is
    if c == "apple":
        candidates += ["green apple"]
    if c == "green apple":
        candidates += ["apple"]
    candidates += ["unknown"]
    # de-dup while preserving order
    seen = set()
    ordered = []
    for k in candidates:
        if k not in seen:
            seen.add(k)
            ordered.append(k)
    return ordered

# ----------------------------
# Inline normalizer fallback (if external script hangs)
# ----------------------------
def _normalize_inline(inp: Path, out: Path, window: int = 5) -> Path:
    """
    Minimal drop-in replacement for as7341_norm.py:
    - Reads CSV with headers
    - Finds CLEAR column (case-insensitive contains 'clear')
    - Normalizes all numeric spectral channels by CLEAR
    - Applies moving average (window) on normalized channels
    - Writes CSV to 'out'
    """
    if not inp.exists():
        raise FileNotFoundError(f"Inline normalize: input missing -> {inp}")
    with inp.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise RuntimeError("Inline normalize: empty input")
    headers = reader.fieldnames or []
    clear_col = next((h for h in headers if h and "clear" in h.lower()), None)
    if not clear_col:
        raise RuntimeError(f"Inline normalize: CLEAR column not found in {headers}")

    numeric_cols = [h for h in headers if h != clear_col]
    norm_rows = []
    for r in rows:
        out_r = dict(r)
        try:
            clr = float(r.get(clear_col, "0") or "0")
        except:
            clr = 0
        for c in numeric_cols:
            try:
                val = float(r.get(c, "0") or "0")
                out_r[c] = f"{val / clr if clr > 0 else 0:.8f}"
            except:
                out_r[c] = "0"
        out_r[clear_col] = "1.0" if clr > 0 else "0"
        norm_rows.append(out_r)

    buf, smoothed = [], []
    for r in norm_rows:
        buf.append(r)
        if len(buf) > window:
            buf.pop(0)
        out_r = dict(r)
        for c in numeric_cols:
            vals = [float(x.get(c, "0") or "0") for x in buf]
            out_r[c] = f"{mean(vals):.8f}"
        smoothed.append(out_r)

    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(smoothed)
    return out

# ----------------------------
# Index threshold override helpers
# ----------------------------
def _read_last_row_csv(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        last = None
        for row in r:
            last = row
    if last is None:
        raise RuntimeError(f"Index CSV has no data: {path}")
    return last

def _to_float_safe(v, default=0.0):
    try:
        return float(v)
    except:
        return default

def _apply_threshold_overrides(index_csv: Path, thresholds: dict, current_summary: dict) -> dict:
    """
    thresholds example in profiles.json:
      "indices": {
        "ripe_if": {
          "ri": {">=": 0.36},
          "nir_red_ratio": {">=": 1.08}
        }
      }
    Checks all listed conditions on the FINAL row of index CSV.
    If all pass, force label=RIPE (and bump confidence).
    """
    if not thresholds or not isinstance(thresholds, dict):
        return current_summary

    row = _read_last_row_csv(index_csv)
    features = {k: _to_float_safe(v) for k, v in row.items()}

    # Friendly aliases (no-op if missing)
    if "nir/red" in features and "nir_red_ratio" not in features:
        features["nir_red_ratio"] = features["nir/red"]
    if "ripe_index" in features and "ri" not in features:
        features["ri"] = features["ripe_index"]

    ops = {
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        ">":  lambda a, b: a >  b,
        "<":  lambda a, b: a <  b,
        "==": lambda a, b: abs(a - b) < 1e-9,
    }

    for feat, cond in thresholds.items():
        if not isinstance(cond, dict) or not cond:
            continue
        op, thr = next(iter(cond.items()))
        if op not in ops:
            print(f"[WARN] Unknown operator {op} for {feat}")
            return current_summary
        val = features.get(feat)
        if val is None:
            print(f"[WARN] Feature '{feat}' not found in index CSV; available: {list(features.keys())[:10]}...")
            return current_summary
        if not ops[op](val, float(thr)):
            # Any failed check keeps original summary
            return current_summary

    new_summary = dict(current_summary or {})
    new_summary["label"] = "ripe"
    new_summary["confidence"] = max(0.9, float(new_summary.get("confidence") or 0.0))
    new_summary["override"] = "profiles.indices.ripe_if"
    return new_summary

# ----------------------------
# Profiles I/O + autotune helpers
# ----------------------------
def _load_profiles() -> Dict[str, Any]:
    if PROFILE_PATH.exists():
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save_profiles_safe(new_profiles: Dict[str, Any]):
    # backup
    try:
        if PROFILE_PATH.exists():
            backup = PROFILE_PATH.with_suffix(".bak")
            shutil.copyfile(PROFILE_PATH, backup)
            print(f"[info] Backed up profiles.json ? {backup}")
    except Exception as e:
        print(f"[WARN] Could not back up profiles.json: {e}")
    # write
    tmp = PROFILE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(new_profiles, f, indent=2)
    os.replace(tmp, PROFILE_PATH)
    print(f"[info] Wrote updated thresholds to {PROFILE_PATH}")

def _maybe_autotune_thresholds(fruit: str, index_csv: Path):
    """
    Env var: FRAD_AUTOTUNE="<fruit>:<feature>:<op>:<margin>"
    - feature: column in index csv (e.g., ri, nir_red_ratio, nir/red)
    - op: >= or <=
    - margin: multiplier applied to current value (e.g., 0.98)
    Also treats 'apple' and 'green apple' as equivalent for matching.
    """
    env = os.environ.get("FRAD_AUTOTUNE", "").strip()
    if not env:
        return None
    try:
        target_fruit, feature, op, margin = [x.strip() for x in env.split(":")]
        margin = float(margin)
    except Exception:
        print(f"[WARN] FRAD_AUTOTUNE malformed. Expected '<fruit>:<feature>:<op>:<margin>'")
        return None

    cf = _canon_name(fruit)
    ct = _canon_name(target_fruit)
    apple_like = {"apple", "green apple", "red apple"}
    if not (cf == ct or (cf in apple_like and ct in apple_like)):
        # not tuning this fruit on this run
        return None

    last = _read_last_row_csv(index_csv)
    if feature == "nir_red_ratio" and "nir/red" in last and "nir_red_ratio" not in last:
        last["nir_red_ratio"] = last["nir/red"]

    val = _to_float_safe(last.get(feature))
    if val == 0.0 and str(last.get(feature, "")).strip() == "":
        print(f"[WARN] Feature '{feature}' missing in {index_csv.name}. Headers: {list(last.keys())[:10]}")
        return None

    if op not in (">=", "<="):
        print(f"[WARN] Unsupported operator '{op}'. Use '>=' or '<='.")
        return None

    tuned = val * margin if op == ">=" else val / max(1e-9, margin)

    profs = _load_profiles()
    # Choose a stable profile key to write to:
    # prefer exact fruit name if it exists; else write to 'apple' when fruit is 'green apple'
    write_key = fruit
    if fruit not in profs and _canon_name(fruit) == "green apple" and "apple" in profs:
        write_key = "apple"

    fruit_prof = profs.get(write_key, {}) or {}
    indices = fruit_prof.get("indices", {}) or {}
    ripe_if = indices.get("ripe_if", {}) or {}
    ripe_if[feature] = {op: float(f"{tuned:.6f}")}
    indices["ripe_if"] = ripe_if
    fruit_prof["indices"] = indices
    profs[write_key] = fruit_prof
    _save_profiles_safe(profs)

    print(f"[autotune] Set profiles['{write_key}']['indices']['ripe_if']['{feature}'] = {{'{op}': {tuned:.6f}}}")
    return {"profile_key": write_key, "feature": feature, "op": op, "threshold": tuned, "current_value": val, "margin": margin}

# ----------------------------
# CLI wrappers with timeouts + I/O checks
# ----------------------------
def cli_log_samples(out_path: Path, count: int, it: int, gain: int) -> Path:
    cmd = [c.format(out=str(out_path), count=str(count), it=str(it), gain=str(gain)) for c in CLI["log"]]
    _which_or_raise(str(sys.executable))
    _run(cmd, timeout=120)  # tune as needed for your sampling rate
    _assert_nonempty_file(out_path, "LOG stage output")
    return out_path

def cli_normalize(inp: Path, out: Path) -> Path:
    _assert_nonempty_file(inp, "NORMALIZE input")
    cmd = [c.format(inp=str(inp), out=str(out)) for c in CLI["norm"]]
    try:
        _run(cmd, timeout=60)  # prevents infinite wait if internal stabilization never converges
        _assert_nonempty_file(out, "NORMALIZE output")
        return out
    except subprocess.TimeoutExpired as te:
        print(f"[WARN] as7341_norm.py timed out; using inline normalizer fallback. {te}")
        _normalize_inline(inp, out, window=5)
        _assert_nonempty_file(out, "INLINE NORMALIZE output")
        return out

def cli_calibrate(inp: Path, out: Path, calfile: Path) -> Path:
    _assert_nonempty_file(inp, "CALIBRATE input")
    if not calfile.exists():
        raise FileNotFoundError(f"CAL file not found: {calfile}")
    cmd = [c.format(inp=str(inp), out=str(out), calfile=str(calfile)) for c in CLI["cal"]]
    _run(cmd, timeout=60)
    _assert_nonempty_file(out, "CALIBRATE output")
    return out

def cli_index(inp: Path, out: Path) -> Path:
    _assert_nonempty_file(inp, "INDEX input")
    cmd = [c.format(inp=str(inp), out=str(out)) for c in CLI["index"]]
    _run(cmd, timeout=30)
    _assert_nonempty_file(out, "INDEX output")
    return out

def cli_score(inp: Path, out: Path, thresholds: dict) -> dict:
    _assert_nonempty_file(inp, "SCORE input")

    # Write thresholds (may be unused if scorer doesn't support them)
    thresh_path = OUT_DIR / "thresholds_tmp.json"
    try:
        with open(thresh_path, "w", encoding="utf-8") as f:
            json.dump(thresholds or {}, f)
    except Exception as e:
        print(f"[WARN] Could not write thresholds_tmp.json ({e}); proceeding without it.")

    cmd_with = [
        sys.executable, str(PROJECT_ROOT / "ripeness_score.py"),
        "--in", str(inp), "--out", str(out),
        "--thresholds", str(thresh_path)
    ]
    cmd_without = [
        sys.executable, str(PROJECT_ROOT / "ripeness_score.py"),
        "--in", str(inp), "--out", str(out)
    ]

    # Try WITH thresholds first; if that fails for any reason, retry WITHOUT.
    res = subprocess.run(cmd_with, capture_output=True, text=True)
    if res.returncode != 0:
        print("[WARN] ripeness_score.py failed with --thresholds; retrying without it.")
        if res.stderr:
            print("[WARN] scorer stderr (with thresholds):")
            print(res.stderr.strip())
        _run(cmd_without, timeout=15)

    # Load summary if produced
    summary = {"label": "unknown", "confidence": None, "source": str(inp)}
    if out.exists():
        try:
            with open(out, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception as e:
            print(f"[WARN] Could not parse score output JSON ({e}); using default summary.")
    else:
        print("[WARN] Score output file not found; using default summary.")
    return summary

def cli_capture_jpeg(out_path: Path, extra_args: list[str] = []) -> Path:
    # Non-fatal: if camera wrapper fails, we still proceed with spectra
    cmd = ["python3", str(PROJECT_ROOT / "camera_capture.py"), "--out", str(out_path)] + list(extra_args)
    print(" ".join(cmd))
    rc = subprocess.run(cmd, check=False).returncode
    if rc != 0:
        print(f"[WARN] camera_capture.py exited with code {rc} (continuing)")
    return out_path

# ----------------------------
# Core pipeline
# ----------------------------
def run_pipeline(sample_count: int = 50, display_enabled: bool = True) -> dict:
    start = time.time()
    ts = _ts()

    # Initialize display (safe fallback if missing)
    display = _make_display(disable=not display_enabled, full_every=15)

    # Show initial scanning screen
    try:
        display.show_scanning()
    except Exception:
        pass

    try:
        # 0) Capture photo (initial) + classify fruit
        display.show_step(1, 5, "CAPTURE")
        jpg_path = OUT_DIR / f"raw_{ts}.jpg"

        # First capture without profile-specific args (we don't know fruit yet)
        cli_capture_jpeg(jpg_path, extra_args=[])

        # Classify fruit and allow override
        fruit_meta = fruit_id.classify(jpg_path)
        fruit_type = fruit_meta.get("fruit", "unknown")
        fruit_type = os.environ.get("FRAD_FORCE_FRUIT", fruit_type)  # < override for testing

        # For display: show "green apple" instead of bare "apple"; show UNKNOWN if unknown
        display_fruit = _display_name_for_fruit(fruit_type)
        try:
            display.show_message("FRUIT", display_fruit.upper())
        except Exception:
            pass

        # Load profile trying reasonable candidates
        profile = {}
        for key in _profile_candidates_for_fruit(fruit_type):
            prof = load_profile(key)
            if prof:
                profile = prof
                break

        # If profile defines camera args and we want profile-consistent image, re-capture
        prof_cam_args = profile.get("camera_args") or profile.get("camera", {}).get("args", [])
        if prof_cam_args:
            jpg_path = OUT_DIR / f"raw_{ts}_prof.jpg"
            cli_capture_jpeg(jpg_path, extra_args=prof_cam_args)

        print(f"Captured {jpg_path}, fruit_id -> {fruit_meta}, fruit_type -> {fruit_type}, display_fruit -> {display_fruit}, loaded profile -> {profile}")

        # Extract profile params with safe defaults
        it = int(profile.get("as7341", {}).get("integration_time_ms", 100))
        gain = int(profile.get("as7341", {}).get("gain", 4))
        cal_file = profile.get("cal_file", str(CAL_DIR / "default_cal.json"))
        thresholds = profile.get("indices", {}).get("ripe_if", {})

        # 1) Acquire/log
        display.show_step(2, 5, "LOGGING")
        raw_path = LOGS_DIR / f"raw_{ts}.csv"
        print(f"[1/5] Logging {sample_count} samples -> {raw_path} (IT={it}, gain={gain})")
        cli_log_samples(raw_path, sample_count, it, gain)

        # 2) Normalize
        display.show_step(3, 5, "NORMALIZE")
        norm_path = OUT_DIR / f"norm_{ts}.csv"
        print(f"[2/5] Normalizing -> {norm_path}")
        cli_normalize(raw_path, norm_path)

        # 3) Calibrate
        display.show_step(4, 5, "CALIBRATE")
        cal_path = OUT_DIR / f"cal_{ts}.csv"
        print(f"[3/5] Calibrating -> {cal_path} (cal_file={cal_file})")
        cli_calibrate(norm_path, cal_path, Path(cal_file))

        # 4) Compute index
        display.show_step(5, 5, "INDEX+SCORE")
        idx_path = OUT_DIR / f"index_{ts}.csv"
        print(f"[4/5] Computing index -> {idx_path}")
        cli_index(cal_path, idx_path)

        # Optional: auto-tune thresholds from THIS run (if FRAD_AUTOTUNE is set)
        try:
            _maybe_autotune_thresholds(fruit_type, idx_path)
        except Exception as e:
            print(f"[WARN] Autotune failed: {e}")

        # 5) Score
        score_path = OUT_DIR / f"score_{ts}.json"
        print(f"[5/5] Scoring -> {score_path}")
        summary = cli_score(idx_path, score_path, thresholds)

        # Apply explicit profile thresholds as an override (works even if ripeness_score.py ignores --thresholds)
        try:
            summary = _apply_threshold_overrides(idx_path, thresholds, summary)
        except Exception as e:
            print(f"[WARN] Threshold override failed: {e}")

        # Display final result
        try:
            label = (summary.get("label") or "UNKNOWN").upper()
            invert = (label == "RIPE")
            display.show_result(label, invert=invert)
        except Exception:
            pass

        # Final result tying image + spectra
        final = {
            "timestamp": ts,
            "duration_s": round(time.time() - start, 3),
            "image": str(jpg_path),
            "fruit": {"detected": fruit_meta, "used": fruit_type, "display_name": display_fruit},
            "profile": profile,
            "raw": str(raw_path),
            "normalized": str(norm_path),
            "calibrated": str(cal_path),
            "index": str(idx_path),
            "summary": summary,
        }
        final_path = OUT_DIR / f"{ts}_result.json"
        with open(final_path, "w", encoding="utf-8") as f:
            json.dump(final, f, indent=2)
        print(f"\n=== Done -> {final_path}\nResult: {json.dumps(summary, indent=2)}")

        try:
            display.sleep()
        except Exception:
            pass
        return final

    except subprocess.TimeoutExpired as te:
        try:
            display.show_message("TIMEOUT", "SEE LOGS")
        except Exception:
            pass
        print(f"[ERROR] Subprocess timeout: {te}", file=sys.stderr)
        raise
    except Exception:
        try:
            display.show_message("ERROR", "SEE LOGS")
        except Exception:
            pass
        raise

# ----------------------------
# CLI entrypoint
# ----------------------------
def main():
    p = argparse.ArgumentParser(description="FRAD unified driver with profiles.json and e-paper display")
    p.add_argument("--count", type=int, default=50, help="Samples to log during acquisition")
    p.add_argument("--no-display", action="store_true", help="Disable e-paper display output")
    args = p.parse_args()
    run_pipeline(sample_count=args.count, display_enabled=not args.no_display)

if __name__ == "__main__":
    main()
