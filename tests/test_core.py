from __future__ import annotations

import time
import unittest

from ps4_macro.controller import (
    ALL_CONTROLS,
    DEFAULT_MAPPING,
    TRIGGER_CONTROLS,
    PadState,
    effective_mapping,
    parse_binding,
)
from ps4_macro.spammer import TurboSpammer
from ps4_macro.targets import DEFAULT_TARGET, TargetAction, target_from_capture


class FakeOutput:
    def __init__(self) -> None:
        self.available = True
        self.error = None
        self.events: list[tuple[str, str]] = []
        self.timed: list[tuple[str, str, float]] = []
        self.held: set[str] = set()
        self.emergency_calls = 0

    def press(self, target: TargetAction) -> None:
        now = time.monotonic()
        self.events.append(("press", target.value))
        self.timed.append(("press", target.value, now))
        self.held.add(target.value)

    def release(self, target: TargetAction) -> None:
        now = time.monotonic()
        self.events.append(("release", target.value))
        self.timed.append(("release", target.value, now))
        self.held.discard(target.value)

    def release_all(self) -> None:
        for value in list(self.held):
            self.events.append(("release", value))
            self.timed.append(("release", value, time.monotonic()))
        self.held.clear()

    def emergency_release(self) -> None:
        self.emergency_calls += 1
        for value in list(self.held):
            self.events.append(("emergency", value))
            self.timed.append(("release", value, time.monotonic()))
        self.held.clear()


def wait_for(predicate, timeout: float = 1.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TargetTests(unittest.TestCase):
    def test_capture_letters_are_lowercase(self) -> None:
        target = target_from_capture("a", "A")
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.kind, "key")
        self.assertEqual(target.value, "a")

    def test_capture_special_keys(self) -> None:
        target = target_from_capture("Return", "\r")
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.value, "enter")

    def test_capture_handles_modifiers_and_unsupported_keys(self) -> None:
        target = target_from_capture("Shift_L", "")
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.value, "shift")
        self.assertIsNone(target_from_capture("Hyper_L", ""))


class MappingTests(unittest.TestCase):
    def test_parse_bindings(self) -> None:
        self.assertEqual(parse_binding("b4").kind, "b")
        self.assertEqual(parse_binding("a2").index, 2)
        binding = parse_binding("h0.8")
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual((binding.kind, binding.index, binding.mask), ("h", 0, 8))
        inverted = parse_binding("a1~")
        self.assertIsNotNone(inverted)
        assert inverted is not None
        self.assertTrue(inverted.invert)
        self.assertIsNone(parse_binding("garbage"))

    def test_sdl_mapping_overrides_fallback(self) -> None:
        merged = effective_mapping({"x": "b3", "y": "b2"})
        self.assertEqual(merged["x"], "b3")
        self.assertEqual(merged["y"], "b2")
        self.assertEqual(merged["lefttrigger"], DEFAULT_MAPPING["lefttrigger"])


class SpammerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = FakeOutput()
        self.spammer = TurboSpammer(self.output, target=DEFAULT_TARGET, rate=40, mode="hold")
        self.spammer.start()

    def tearDown(self) -> None:
        self.spammer.shutdown()

    def test_hold_mode_fires_and_stops(self) -> None:
        self.spammer.activation_changed(True)
        self.assertTrue(wait_for(lambda: self.output.events.count(("press", "space")) >= 2))
        self.spammer.activation_changed(False)
        time.sleep(0.12)
        presses = self.output.events.count(("press", "space"))
        time.sleep(0.12)
        self.assertEqual(self.output.events.count(("press", "space")), presses)
        self.assertFalse(self.output.held)

    def test_toggle_mode_latches(self) -> None:
        self.spammer.set_mode("toggle")
        self.spammer.activation_changed(True)
        self.assertTrue(wait_for(lambda: self.spammer.active))
        self.spammer.activation_changed(False)
        time.sleep(0.08)
        self.assertTrue(self.spammer.active)
        self.spammer.activation_changed(True)
        self.assertFalse(self.spammer.active)
        self.spammer.activation_changed(False)

    def test_toggle_panic_while_held_waits_for_release(self) -> None:
        self.spammer.set_mode("toggle")
        self.spammer.activation_changed(True)
        self.assertTrue(self.spammer.active)

        self.spammer.panic()
        self.assertFalse(self.spammer.active)
        # A duplicate held edge must not re-arm while the control is down.
        self.spammer.activation_changed(True)
        self.assertFalse(self.spammer.active)

        self.spammer.activation_changed(False)
        self.spammer.activation_changed(True)
        self.assertTrue(self.spammer.active)

    def test_controller_lost_stops_toggle_and_releases(self) -> None:
        self.spammer.set_mode("toggle")
        self.spammer.activation_changed(True)
        self.assertTrue(wait_for(lambda: self.output.held))
        self.spammer.controller_lost()
        self.assertFalse(self.spammer.active)
        self.assertFalse(self.output.held)
        self.assertGreater(self.output.emergency_calls, 0)

    def test_watchdog_stops_runaway_when_ui_stalls(self) -> None:
        output = FakeOutput()
        spammer = TurboSpammer(output, rate=20, mode="toggle", watchdog=0.25)
        spammer.start()
        try:
            spammer.heartbeat()
            spammer.activation_changed(True)
            self.assertTrue(wait_for(lambda: output.held, 1.0))
            # Stop calling heartbeat() to emulate a blocked/hung UI loop.
            self.assertTrue(wait_for(lambda: not spammer.active, timeout=2.0))
            self.assertFalse(output.held)
            self.assertGreater(output.emergency_calls, 0)
        finally:
            spammer.shutdown()

    def test_emergency_release_repeats_recent_targets(self) -> None:
        from ps4_macro.output import OutputDriver

        class Keyboard:
            def __init__(self) -> None:
                self.releases: list[str] = []

            def press(self, _key: object) -> None:
                pass

            def release(self, _key: object) -> None:
                self.releases.append("released")

        driver = OutputDriver.__new__(OutputDriver)
        driver._lock = __import__("threading").RLock()
        driver._keyboard = Keyboard()
        driver._mouse = object()
        driver._held = {}
        driver._recent = {}
        driver._guard = None
        driver.error = None
        target = TargetAction("up", "Arrow Up", "key", "up")
        driver.press(target)
        driver.release(target)
        self.assertEqual(driver._held, {})
        driver.emergency_release()
        # One normal key-up plus two emergency key-ups, even though the key was
        # already released, so a lost event cannot leave it logically stuck.
        self.assertEqual(driver._keyboard.releases, ["released"] * 3)

    def test_every_activation_control_can_toggle(self) -> None:
        for control in ALL_CONTROLS:
            output = FakeOutput()
            spammer = TurboSpammer(output, rate=20, mode="toggle")
            spammer.start()
            try:
                state = PadState(connected=True)
                state.buttons[control] = True
                if control in TRIGGER_CONTROLS:
                    state.triggers[control] = 1.0

                pressed = state.control_pressed(control, False)
                self.assertTrue(pressed, control)
                spammer.activation_changed(pressed)
                self.assertTrue(spammer.active, control)

                state.buttons[control] = False
                if control in TRIGGER_CONTROLS:
                    state.triggers[control] = 0.0
                released = state.control_pressed(control, True)
                self.assertFalse(released, control)
                spammer.activation_changed(released)
                self.assertTrue(spammer.active, control)
            finally:
                spammer.shutdown()

    def test_pulse_width_is_respected(self) -> None:
        output = FakeOutput()
        spammer = TurboSpammer(output, rate=10, mode="hold", pulse_ms=60)
        spammer.start()
        try:
            spammer.activation_changed(True)
            self.assertTrue(wait_for(lambda: len(output.timed) >= 6, timeout=1.5))
            spammer.activation_changed(False)
        finally:
            spammer.shutdown()
        time.sleep(0.05)

        durations: list[float] = []
        pressed_at: dict[str, float] = {}
        for kind, value, stamp in output.timed:
            if kind == "press":
                pressed_at[value] = stamp
            elif value in pressed_at:
                durations.append(stamp - pressed_at.pop(value))

        self.assertTrue(durations, "no completed pulses recorded")
        for duration in durations:
            self.assertGreaterEqual(duration, 0.045)
            self.assertLessEqual(duration, 0.095)

    def test_panic_latches_until_release(self) -> None:
        self.spammer.set_mode("hold")
        self.spammer.activation_changed(True)
        self.assertTrue(wait_for(lambda: self.spammer.active))
        self.spammer.panic()
        self.assertFalse(self.spammer.active)
        self.spammer.activation_changed(True)  # still physically held
        self.assertFalse(self.spammer.active)
        self.spammer.activation_changed(False)
        self.spammer.activation_changed(True)
        self.assertTrue(self.spammer.active)

    def test_rate_is_clamped(self) -> None:
        self.spammer.set_rate(999)
        self.assertEqual(self.spammer.snapshot().rate, 60)
        self.spammer.set_rate(0)
        self.assertEqual(self.spammer.snapshot().rate, 1)

    def test_releases_on_shutdown(self) -> None:
        self.spammer.set_rate(1)
        self.spammer.activation_changed(True)
        time.sleep(0.05)
        self.spammer.shutdown()
        self.assertFalse(self.output.held)


if __name__ == "__main__":
    unittest.main()
