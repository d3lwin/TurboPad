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

DEFAULT_PULSE_MS = 30
MIN_PULSE_MS = 5
MAX_PULSE_MS = 150

# Keep a little breathing room between a release and the next press so games
# that poll input once per frame always see a fresh key-down edge.
MIN_GAP_SECONDS = 0.004


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
        pulse_ms: int = DEFAULT_PULSE_MS,
        watchdog: float = 0.0,
    ) -> None:
        self._output = output
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._target = target
        self._rate = self._clamp_rate(rate)
        self._pulse_ms = self._clamp_pulse(pulse_ms)
        self._mode: Mode = mode
        self._active = False
        self._activation_down = False
        self._panic_latched = False
        self._presses = 0
        self._error: str | None = None
        self._started = False
        self._restart_schedule = True
        self._watchdog = max(0.0, float(watchdog))
        self._last_heartbeat = time.monotonic()
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._commit_press = False

    @staticmethod
    def _clamp_rate(rate: int) -> int:
        return max(MIN_RATE, min(MAX_RATE, int(rate)))

    @staticmethod
    def _clamp_pulse(pulse_ms: int) -> int:
        return max(MIN_PULSE_MS, min(MAX_PULSE_MS, int(pulse_ms)))

    @staticmethod
    def effective_pulse_ms(rate: int, pulse_ms: int) -> float:
        """Return the press duration actually used for a rate/pulse pair."""

        interval_ms = 1000.0 / max(1, int(rate))
        gap_ms = MIN_GAP_SECONDS * 1000.0
        pulse = max(float(MIN_PULSE_MS), min(float(pulse_ms), float(MAX_PULSE_MS)))
        return max(3.0, min(pulse, interval_ms - gap_ms))

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._last_heartbeat = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="turbo-spammer", daemon=True)
        self._thread.start()
        if self._watchdog > 0:
            self._watch_thread = threading.Thread(
                target=self._watch,
                name="turbo-watchdog",
                daemon=True,
            )
            self._watch_thread.start()

    def heartbeat(self) -> None:
        """Tell the spammer that the UI main loop is still alive."""

        self._last_heartbeat = time.monotonic()

    def _watch(self) -> None:
        """Stop the macro if the UI thread stops responding."""

        while not self._watch_stop.wait(0.25):
            with self._lock:
                active = self._active
                last = self._last_heartbeat
                timeout = self._watchdog
            if active and timeout > 0 and time.monotonic() - last > timeout:
                self.panic()
                with self._lock:
                    self._error = "Macro stopped: UI stopped responding"
                self._wake.set()

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

    def set_pulse_ms(self, pulse_ms: int) -> None:
        with self._lock:
            self._pulse_ms = self._clamp_pulse(pulse_ms)
        self._wake.set()

    def set_mode(self, mode: Mode) -> None:
        with self._lock:
            self._mode = mode
            self._active = False
            self._activation_down = False
            self._panic_latched = False
            self._restart_schedule = True
        self._wake.set()

    def activation_changed(self, pressed: bool) -> None:
        """Called on every physical edge of the selected activation control."""

        stop_output = False
        with self._lock:
            if pressed and not self._activation_down:
                if self._panic_latched:
                    # Panic was pressed while this control was held; wait for
                    # a release so it cannot immediately re-arm the turbo.
                    pass
                elif self._mode == "toggle":
                    self._active = not self._active
                    self._panic_latched = False
                else:
                    self._active = True
            elif not pressed:
                self._panic_latched = False
                if self._mode == "hold":
                    self._active = False
            self._activation_down = pressed
            if not self._active:
                stop_output = True
            else:
                # Start the next pulse on a fresh schedule so the timing loop
                # cannot fire twice in a row with no key-up gap.
                self._restart_schedule = True
            self._error = None if pressed else self._error
        if stop_output:
            self._output.release_all()
        self._wake.set()

    def reset_activation(self) -> None:
        with self._lock:
            self._activation_down = False
            self._active = False
            self._panic_latched = False
            self._restart_schedule = True
            self._error = None
        self._output.release_all()
        self._wake.set()

    def controller_lost(self) -> None:
        """Stop and release everything when the controller disappears."""

        with self._lock:
            self._active = False
            self._activation_down = False
            self._panic_latched = False
            self._restart_schedule = True
        self._output.emergency_release()
        self._wake.set()
        self._release_soon()

    def panic(self) -> None:
        """Stop immediately and ignore a still-held activation until it is released."""

        with self._lock:
            self._active = False
            # Only latch when the activation is physically down; otherwise the
            # next deliberate press should be allowed to start again.
            self._panic_latched = self._activation_down
            self._restart_schedule = True
        self._output.emergency_release()
        self._wake.set()
        self._release_soon()

    def _release_soon(self) -> None:
        """Send one more release shortly after a stop.

        This catches the tiny race where the worker had already committed to a
        press when the stop arrived. If a new activation started in the
        meantime, leave it alone.
        """

        def sweep() -> None:
            time.sleep(0.12)
            with self._lock:
                if self._active or self._stop.is_set():
                    return
            self._output.emergency_release()

        threading.Thread(target=sweep, name="turbo-release-sweep", daemon=True).start()

    def clear_error(self) -> None:
        with self._lock:
            self._error = None

    def shutdown(self) -> None:
        self._stop.set()
        self._watch_stop.set()
        with self._lock:
            self._active = False
        self._output.emergency_release()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.6)
        watch = self._watch_thread
        if watch is not None and watch.is_alive():
            watch.join(timeout=0.5)
        # The worker always releases after its hold, but do a final pass in
        # case the press completed while shutdown was racing it.
        self._output.emergency_release()

    def _wait(self, seconds: float) -> bool:
        """Wait for a duration or until awakened; returns False when stopping."""

        if seconds <= 0:
            return not self._stop.is_set()
        return not self._stop.wait(seconds)

    def _run(self) -> None:
        next_tick = time.monotonic()
        while not self._stop.is_set():
            # Clear before inspecting state: an activation that lands between
            # the read and the wait still sets the event and wakes us.
            self._wake.clear()
            with self._lock:
                active = self._active
                target = self._target
                rate = self._rate
                pulse_ms = self._pulse_ms
                restart = self._restart_schedule
                self._restart_schedule = False

            if not active:
                # Block until the activation changes instead of polling.
                self._wake.wait()
                next_tick = time.monotonic()
                continue

            now = time.monotonic()
            if restart:
                # A fresh activation starts a fresh schedule; without this the
                # first two pulses can share a key-down with no gap between.
                next_tick = now

            interval = 1.0 / max(1, rate)
            hold = TurboSpammer.effective_pulse_ms(rate, pulse_ms) / 1000.0

            # Re-check active state while holding the lock to prevent a race
            # where controller_lost/panic sets _active=False after we read it
            # but before we press.
            with self._lock:
                if not self._active:
                    continue
                # Mark that we're committing to a press so emergency_release
                # knows a key-down is in flight.
                self._commit_press = True

            try:
                self._output.press(target)
            except OutputError as exc:
                with self._lock:
                    self._active = False
                    self._error = str(exc)
                    self._commit_press = False
                self._output.release_all()
                self._wake.set()
                continue
            except Exception as exc:  # guard the thread against driver surprises
                with self._lock:
                    self._active = False
                    self._error = f"Output error: {exc}"
                    self._commit_press = False
                self._output.release_all()
                self._wake.set()
                continue

            # Clear the commit flag now that press() has been called.
            with self._lock:
                self._commit_press = False

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
                remaining = MIN_GAP_SECONDS
            if not self._wait(remaining):
                break
