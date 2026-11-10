"""The turbo loop: turns an activation edge into repeated output taps."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Literal

from .output import OutputDriver, OutputError
from .targets import DEFAULT_TARGET, TargetAction

Mode = Literal["hold", "toggle"]

MIN_RATE = 1
MAX_RATE = 60


@dataclass(frozen=True, slots=True)
class SpamSnapshot:
    active: bool
    presses: int
    rate: int
    mode: str
    target_label: str
    error: str | None
    armed: bool


class TurboSpammer:
    """A timing thread that taps a target while the macro is active."""

    def __init__(
        self,
        output: OutputDriver,
        target: TargetAction = DEFAULT_TARGET,
        rate: int = 20,
        mode: Mode = "hold",
    ) -> None:
        self._output = output
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._target = target
        self._rate = self._clamp_rate(rate)
        self._mode: Mode = mode
        self._active = False
        self._activation_down = False
        self._panic_latched = False
        self._presses = 0
        self._error: str | None = None
        self._started = False

    @staticmethod
    def _clamp_rate(rate: int) -> int:
        return max(MIN_RATE, min(MAX_RATE, int(rate)))

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._thread = threading.Thread(target=self._run, name="turbo-spammer", daemon=True)
        self._thread.start()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def snapshot(self) -> SpamSnapshot:
        with self._lock:
            if self._error:
                error = self._error
            elif not self._output.available:
                error = self._output.error
            else:
                error = None
            return SpamSnapshot(
                active=self._active,
                presses=self._presses,
                rate=self._rate,
                mode=self._mode,
                target_label=self._target.label,
                error=error,
                armed=self._activation_down,
            )

    def set_target(self, target: TargetAction) -> None:
        with self._lock:
            self._target = target
        self._wake.set()

    def set_rate(self, rate: int) -> None:
        with self._lock:
            self._rate = self._clamp_rate(rate)
        self._wake.set()

    def set_mode(self, mode: Mode) -> None:
        with self._lock:
            self._mode = mode
            self._active = False
            self._activation_down = False
            self._panic_latched = False
        self._wake.set()

    def activation_changed(self, pressed: bool) -> None:
        """Called on every physical edge of the selected activation control."""

        stop_output = False
        with self._lock:
            if pressed and not self._activation_down:
                if self._mode == "toggle":
                    self._active = not self._active
                    self._panic_latched = False
                elif not self._panic_latched:
                    self._active = True
            elif not pressed:
                self._panic_latched = False
                if self._mode == "hold":
                    self._active = False
                self._activation_down = False
            self._activation_down = pressed
            if not self._active:
                stop_output = True
            self._error = None if pressed else self._error
        if stop_output:
            self._output.release_all()
        self._wake.set()

    def reset_activation(self) -> None:
        with self._lock:
            self._activation_down = False
            self._active = False
            self._panic_latched = False
            self._error = None
        self._output.release_all()
        self._wake.set()

    def panic(self) -> None:
        """Stop immediately and ignore a still-held activation until it is released."""

        with self._lock:
            self._active = False
            self._panic_latched = True
            if self._mode == "toggle":
                self._activation_down = False
        self._output.release_all()
        self._wake.set()

    def clear_error(self) -> None:
        with self._lock:
            self._error = None

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            self._active = False
        self._output.release_all()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.6)

    def _wait(self, seconds: float) -> bool:
        """Wait for a duration or until awakened; returns False when stopping."""

        if seconds <= 0:
            return not self._stop.is_set()
        return not self._stop.wait(seconds)

    def _run(self) -> None:
        next_tick = time.monotonic()
        while not self._stop.is_set():
            with self._lock:
                active = self._active
                target = self._target
                rate = self._rate

            if not active:
                self._wake.wait(0.025)
                self._wake.clear()
                next_tick = time.monotonic()
                continue

            interval = 1.0 / max(1, rate)
            hold = max(0.004, min(0.03, interval * 0.62))
            try:
                self._output.press(target)
            except OutputError as exc:
                with self._lock:
                    self._active = False
                    self._error = str(exc)
                self._output.release_all()
                self._wake.set()
                continue
            except Exception as exc:  # guard the thread against driver surprises
                with self._lock:
                    self._active = False
                    self._error = f"Output error: {exc}"
                self._output.release_all()
                self._wake.set()
                continue

            if self._wait(hold):
                self._output.release(target)
            else:
                self._output.release(target)
                break

            with self._lock:
                self._presses += 1
                active_now = self._active

            if not active_now:
                next_tick = time.monotonic()
                continue

            next_tick += interval
            remaining = next_tick - time.monotonic()
            if remaining < 0:
                next_tick = time.monotonic()
                remaining = 0.0
            if not self._wait(remaining):
                break
