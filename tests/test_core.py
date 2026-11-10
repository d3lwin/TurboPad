from __future__ import annotations

import time
import unittest

from ps4_macro.controller import (
    DEFAULT_MAPPING,
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
        self.held: set[str] = set()

    def press(self, target: TargetAction) -> None:
        self.events.append(("press", target.value))
        self.held.add(target.value)

    def release(self, target: TargetAction) -> None:
        self.events.append(("release", target.value))
        self.held.discard(target.value)

    def release_all(self) -> None:
        for value in list(self.held):
            self.events.append(("release", value))
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
