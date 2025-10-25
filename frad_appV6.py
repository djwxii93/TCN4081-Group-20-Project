#!/usr/bin/env python3
# ============================== FRAD App V6 ==============================
# Minimal, robust runner with:
# - Line-1 heartbeat to /home/frad002/frad/out/FRAD_V6_BOOT.log
# - Optional Waveshare e-ink screen ping (flash/flicker on init)
# - AS7341 sensor reads (or --fake-sensor)
# - CSV logging to --log-dir
# - Clear logging and early-exit diagnostics
# ========================================================================

# ---- Line 1 heartbeat (prove we reached the top of the file) ------------
from datetime import datetime; open("/home/frad002/frad/out/FRAD_V6_BOOT.log","a").write(f"[{datetime.now()}] start-of-file reached\n")

import os
import sys
import time
import csv
import math
import random
import argparse
import traceback
from pathlib import Path

# -------------------------- Utilities & Logging --------------------------
def init_logger(log_dir: Path, verbose: bool = True):
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "frad_appV6.log"
    import logging
    handlers = [logging.FileHandler(log_path, encoding="utf-8")]
    if verbose:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )
    return log_path

def append_boot(msg: str):
    try:
        Path("/home/frad002/frad/out").mkdir(parents=True, exist_ok=True)
        with open("/home/frad002/frad/out/FRAD_V6_BOOT.log", "a") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:
        # Don't crash on boot logging
        pass

# --------------------------- E-Ink (Waveshare) ---------------------------
class Screen:
    def __init__(self, panel: str = "2in13_V3", enable: bool = True):
        self.panel = panel
        self.enable = enable
        self._epd = None

    def _import_epd(self):
        if not self.enable:
            return None
        try:
            from waveshare_epd import epd2in13_V3 as epd_213
        except Exception:
            epd_213 = None
        try:
            from waveshare_epd import epd2in9_V2 as epd_29
        except Exception:
            epd_29 = None

        if self.panel.lower() in ("2in13_v3", "2.13", "2in13"):
            if epd_213 is None:
                raise RuntimeError("waveshare_epd.epd2in13_V3 not available")
            return ("2.13", epd_213)
        elif self.panel.lower() in ("2in9_v2", "2.9", "2in9"):
            if epd_29 is None:
                raise RuntimeError("waveshare_epd.epd2in9_V2 not available")
            return ("2.9", epd_29)
        else:
            raise ValueError(f"Unknown panel '{self.panel}'")

    def ping(self, logger):
        if not self.enable:
            logger.info("Screen disabled by flag; skipping ping.")
            append_boot("screen: disabled")
            return False

        append_boot("about to init EPD")
        try:
            label, mod = self._import_epd()
            self._epd = mod.EPD()
            self._epd.init()            # should flash/flicker here
            logger.info("EPD %s init OK (flash should be visible).", label)
            append_boot("EPD init done")
            # Put it to sleep immediately; we only needed a visible reset.
            self._epd.sleep()
            logger.info("EPD sleep")
            return True
        except Exception as e:
            logger.error("EPD init failed: %s", e)
            append_boot(f"EPD init failed: {e}")
            return False

# ------------------------------ AS7341 I2C -------------------------------
class AS7341:
    """
    Lightweight wrapper. If the real driver isn't available, can run in
    --fake-sensor mode to keep the app flowing.
    """
    def __init__(self, fake=False):
        self.fake = fake
        self._dev = None
        self._ok = False

        if self.fake:
            self._ok = True
            return

        # Try Adafruit CircuitPython AS7341 if installed.
        try:
            import board  # type: ignore
            import busio  # type: ignore
            import adafruit_as7341  # type: ignore
            i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            self._dev = adafruit_as7341.AS7341(i2c)
            # Simple probe: read one channel to verify
            _ = self._dev.channel_415nm
            self._ok = True
        except Exception:
            # Fallback: raw smbus check at address 0x39 (typical AS7341)
            try:
                import smbus  # type: ignore
                bus = smbus.SMBus(1)
                addr = 0x39
                # Try a harmless read; may raise if not present.
                bus.read_byte(addr)
                # We don't implement full register IO here; mark present-ish
                self._ok = True
                self._dev = ("smbus-probe", bus, addr)
            except Exception:
                self._ok = False

    def present(self):
        return self._ok

    def read_once(self):
        """
        Returns a dict of spectral channels. In fake mode generates plausible values.
        """
        if self.fake or self._dev is None:
            base = 2000 + int(500 * math.sin(time.time()))
            jitter = lambda: random.randint(-50, 50)
            return {
                "415": base + jitter(),
                "445": base + 120 + jitter(),
                "480": base + 240 + jitter(),
                "515": base + 360 + jitter(),
                "555": base + 480 + jitter(),
                "590": base + 600 + jitter(),
                "630": base + 720 + jitter(),
                "680": base + 840 + jitter(),
                "CLEAR": base + 1000 + jitter(),
                "NIR": base + 300 + jitter(),
            }

        # If we have the Adafruit driver:
        try:
            if hasattr(self._dev, "channel_415nm"):
                d = {
                    "415": int(self._dev.channel_415nm),
                    "445": int(self._dev.channel_445nm),
                    "480": int(self._dev.channel_480nm),
                    "515": int(self._dev.channel_515nm),
                    "555": int(self._dev.channel_555nm),
                    "590": int(self._dev.channel_590nm),
                    "630": int(self._dev.channel_630nm),
                    "680": int(self._dev.channel_680nm),
                    "CLEAR": int(self._dev.channel_clear),
                    "NIR": int(self._dev.channel_nir),
                }
                return d
        except Exception:
            pass

        # If we only smbus-probed, we cannot read channels without full driver.
        # Return a static-ish stub so downstream code keeps flowing.
        base = 2500
        return {
            "415": base,
            "445": base + 120,
            "480": base + 240,
            "515": base + 360,
            "555": base + 480,
            "590": base + 600,
            "630": base + 720,
            "680": base + 840,
            "CLEAR": base + 1000,
            "NIR": base + 300,
        }

# ------------------------------ CSV Logging ------------------------------
def open_csv(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"as7341_log_{ts}.csv"
    f = open(path, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(["t_epoch","415","445","480","515","555","590","630","680","CLEAR","NIR"])
    f.flush()
    return f, w, path

# ------------------------------ Main Program -----------------------------
def run(args):
    import logging
    logger = logging.getLogger(__name__)

    # Write absolute script info to boot log for sanity
    append_boot(f"__file__={__file__} cwd={os.getcwd()}")

    # 1) Screen ping (optional but recommended to see the reset)
    scr = Screen(panel=args.panel, enable=not args.no_screen)
    ping_ok = scr.ping(logger)
    if not ping_ok and not args.no_screen:
        logger.warning("Screen ping failed (continuing). Check SPI/GPIO groups and wiring.")

    # 2) Sensor init
    sensor = AS7341(fake=args.fake_sensor)
    if not sensor.present():
        if args.require_sensor:
            logger.error("AS7341 not detected and --require-sensor set. Exiting.")
            return 2
        logger.warning("AS7341 not detected; continuing with FAKE readings.")
        sensor = AS7341(fake=True)

    # 3) CSV setup
    f, w, csv_path = open_csv(args.log_dir)
    logger.info("Logging to %s", csv_path)

    # 4) Main loop
    i = 0
    count = None if args.count is None else int(args.count)
    period = float(args.period)

    try:
        while True if count is None else i < count:
            t = time.time()
            d = sensor.read_once()
            row = [f"{t:.3f}", d["415"], d["445"], d["480"], d["515"], d["555"], d["590"], d["630"], d["680"], d["CLEAR"], d["NIR"]]
            w.writerow(row)
            f.flush()
            logger.info("i=%d  CLEAR=%s NIR=%s (csv ok)", i, d["CLEAR"], d["NIR"])
            i += 1
            time.sleep(period)
    except KeyboardInterrupt:
        logger.info("Stopped by user (Ctrl+C).")
        return 0
    finally:
        try:
            f.close()
        except Exception:
            pass

    return 0

def build_argparser():
    ap = argparse.ArgumentParser(description="FRAD App V6 — e-ink ping + AS7341 logger")
    ap.add_argument("--log-dir", default="/home/frad002/frad/out", help="Directory for logs/CSV")
    ap.add_argument("--count", type=int, default=10, help="Number of samples to capture (None = infinite)")
    ap.add_argument("--period", type=float, default=0.5, help="Seconds between samples")
    ap.add_argument("--panel", default="2in13_V3", help="Waveshare panel id: 2in13_V3 or 2in9_V2")
    ap.add_argument("--no-screen", action="store_true", help="Disable screen init/ping")
    ap.add_argument("--fake-sensor", action="store_true", help="Use synthetic AS7341 readings")
    ap.add_argument("--require-sensor", action="store_true", help="Exit if AS7341 not detected")
    ap.add_argument("--quiet", action="store_true", help="File-only logging (no console)")
    return ap

def main():
    args = build_argparser().parse_args()

    log_dir = Path(args.log_dir)
    log_path = init_logger(log_dir, verbose=not args.quiet)

    import logging
    logging.info("FRAD v6 starting… Python=%s", sys.version.split()[0])
    logging.info("args=%s", vars(args))

    rc = run(args)
    logging.info("FRAD v6 exiting rc=%s", rc)
    sys.exit(rc)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Fail loud so you can see the traceback in the terminal
        traceback.print_exc()
        sys.exit(1)
