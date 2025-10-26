#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import RPi.GPIO as GPIO
import time
import threading


class ButtonHandler:
    def __init__(self, pin, on_scan, on_reset, on_shutdown,
                 hold_time=5.0, double_tap_window=0.4, bouncetime=200):

        self.pin = pin
        self.on_scan = on_scan
        self.on_reset = on_reset
        self.on_shutdown = on_shutdown
        self.hold_time = hold_time
        self.double_tap_window = double_tap_window

        self.last_press_time = 0.0
        self.press_count = 0

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        GPIO.add_event_detect(
            self.pin, GPIO.FALLING,
            callback=self._pressed, bouncetime=bouncetime
        )

    def _pressed(self, channel):
        press_start = time.time()

        # HOLD DETECT
        while GPIO.input(self.pin) == GPIO.LOW:
            time.sleep(0.05)
            if time.time() - press_start >= self.hold_time:
                self.on_shutdown()
                self.press_count = 0
                return

        # TAP / DOUBLE TAP
        now = time.time()
        if now - self.last_press_time < self.double_tap_window:
            self.press_count += 1
        else:
            self.press_count = 1
        self.last_press_time = now

        def evaluate():
            time.sleep(self.double_tap_window)
            if self.press_count == 1:
                self.on_scan()
            elif self.press_count == 2:
                self.on_reset()
            self.press_count = 0

        threading.Thread(target=evaluate, daemon=True).start()

    @staticmethod
    def cleanup():
        GPIO.cleanup()
