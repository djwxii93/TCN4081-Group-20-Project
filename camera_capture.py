#!/usr/bin/env python3
"""
camera_capture.py — Cross-compatible still capture for Raspberry Pi Camera Module 2 (IMX219) and 3 (IMX708)
Uses Picamera2/libcamera and avoids autofocus controls unless the camera supports them (CM3 only).
Also supports optional AWB presets, manual exposure/gain, and matching the latest CSV's basename.

Examples
--------
# simplest: save to captures/<timestamp>.jpg
python3 camera_capture.py

# choose resolution and AWB preset
python3 camera_capture.py --width 2028 --height 1520 --awb daylight

# save next to the most recently modified CSV, reusing its basename
python3 camera_capture.py --match-latest

# choose explicit output file
python3 camera_capture.py --out out/snap.jpg
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
from pathlib import Path

from picamera2 import Picamera2

# Optional import: script still works if libcamera.controls isn't importable
try:
    from libcamera import controls
except Exception:
    controls = None


def supports_control(picam2: Picamera2, name: str) -> bool:
    try:
        return name in (picam2.camera_controls or {})
    except Exception:
        return False


def parse_args():
    p = argparse.ArgumentParser(description="Picamera2 still capture (CM2/CM3 safe)")
    p.add_argument("--width", type=int, default=2028, help="Output width (CM2-safe default: 2028)")
    p.add_argument("--height", type=int, default=1520, help="Output height (CM2-safe default: 1520)")
    p.add_argument("--format", default="RGB888",
                   choices=["RGB888", "BGR888", "YUV420", "XBGR8888", "XRGB8888"],
                   help="Main stream pixel format")
    p.add_argument("--out", type=str, default=None, help="Output filename (.jpg/.png)")
    p.add_argument("--dir", type=str, default="captures", help="Output directory if --out not set")
    p.add_argument("--png", action="store_true", help="Save PNG instead of JPEG")
    p.add_argument("--timeout", type=int, default=300, help="Preview/warmup time in ms (default 300)")

    # AWB / exposure
    p.add_argument("--awb", default="auto",
                   choices=["auto", "daylight", "cloudy", "tungsten", "fluorescent", "incandescent", "manual"],
                   help="AWB preset (or manual to set colour gains)")
    p.add_argument("--colour-gains", default=None,
                   help="Manual colour gains as 'r,g' (used only with --awb manual), e.g. 2.0,1.9")
    p.add_argument("--exposure", type=int, default=None, help="Manual exposure time in microseconds")
    p.add_argument("--gain", type=float, default=None, help="Manual analogue gain")

    # Convenience
    p.add_argument("--match-latest", action="store_true",
                   help="Save next to the most recent CSV and reuse its basename")
    p.add_argument("--show-controls", action="store_true",
                   help="Print available camera controls and exit")
    return p.parse_args()


AWB_MAP = {
    "daylight": "Daylight",
    "cloudy": "Cloudy",
    "tungsten": "Tungsten",
    "fluorescent": "Fluorescent",
    "incandescent": "Incandescent",
}


def resolve_output(args) -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = "png" if args.png else "jpg"

    # If explicit path provided
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        return out_path

    # If matching latest CSV's basename
    if args.match-latest:
        candidates = sorted(glob.glob("**/*.csv", recursive=True), key=lambda p: os.path.getmtime(p))
        if not candidates:
            # Fallback to timestamp if nothing to match
            out_dir = Path(args.dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            return out_dir / f"capture_{ts}.{ext}"
        latest = Path(candidates[-1])
        return latest.with_suffix(f".{ext}")

    # Default: captures/capture_<timestamp>.<ext>
    out_dir = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"capture_{ts}.{ext}"


def main():
    args = parse_args()
    picam2 = Picamera2()

    if args.show_controls:
        cfg = picam2.create_preview_configuration()
        picam2.configure(cfg)
        print("Available camera controls:")
        for k, v in (picam2.camera_controls or {}).items():
            print(f"  - {k}: {v}")
        return 0

    # Create a CM2-safe still configuration
    config = picam2.create_still_configuration(
        main={"size": (args.width, args.height), "format": args.format},
        buffer_count=2
    )
    picam2.configure(config)

    # Build control dictionary guarded by capability checks
    ctrl = {}

    # Autofocus only if present (CM3). CM2 lacks AF controls.
    if supports_control(picam2, "AfMode") and controls and hasattr(controls, "AfModeEnum"):
        ctrl["AfMode"] = controls.AfModeEnum.Continuous

    # AWB presets
    if args.awb == "auto":
        if supports_control(picam2, "AwbEnable"):
            ctrl["AwbEnable"] = True
    elif args.awb == "manual":
        if supports_control(picam2, "AwbEnable"):
            ctrl["AwbEnable"] = False
        if args.colour_gains and supports_control(picam2, "ColourGains"):
            try:
                r, g = (float(x.strip()) for x in args.colour_gains.split(","))
                ctrl["ColourGains"] = (r, g)
            except Exception:
                print("Warning: --colour-gains must be 'r,g' floats, e.g. 2.0,1.9", file=sys.stderr)
    else:
        # Named presets -> map to libcamera AwbMode enum if available
        preset = AWB_MAP.get(args.awb)
        if preset and supports_control(picam2, "AwbMode"):
            if controls and hasattr(controls, "AwbMode"):
                enum_val = getattr(controls.AwbMode, preset, None)
                if enum_val is not None:
                    ctrl["AwbMode"] = enum_val

    # Manual exposure/gain
    if args.exposure is not None and supports_control(picam2, "ExposureTime"):
        ctrl["ExposureTime"] = int(args.exposure)
    if args.gain is not None and supports_control(picam2, "AnalogueGain"):
        ctrl["AnalogueGain"] = float(args.gain)

    # Apply controls (best-effort)
    if ctrl:
        try:
            picam2.set_controls(ctrl)
        except Exception as e:
            print(f"Control warning: {e}", file=sys.stderr)

    # Start and optional warmup
    picam2.start()
    if args.timeout and args.timeout > 0:
        import time
        time.sleep(args.timeout / 1000.0)

    out_path = resolve_output(args)
    picam2.capture_file(str(out_path))
    picam2.stop()

    # Write a small JSON sidecar describing settings actually used
    meta = {
        "filename": str(out_path),
        "width": args.width,
        "height": args.height,
        "format": args.format,
        "controls_requested": ctrl,
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
    }
    sidecar = out_path.with_suffix(".json")
    try:
        sidecar.write_text(json.dumps(meta, indent=2))
    except Exception as e:
        print(f"Sidecar write warning: {e}", file=sys.stderr)

    print(f"[ok] Saved {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
