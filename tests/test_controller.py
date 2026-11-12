from __future__ import annotations

import unittest

from ps4_macro.controller import ControllerManager, PadState, effective_mapping


class FakeJoystick:
    def __init__(self) -> None:
        self.buttons = {0: True, 1: False, 2: True, 3: False, 4: True, 8: True}
        self.axes = {0: 0.5, 1: -0.25, 2: -1.0, 3: -0.75, 4: 0.4, 5: -1.0}
        self.hats = {0: (-1, 1)}

    def get_button(self, index: int) -> int:
        return int(self.buttons.get(index, False))

    def get_axis(self, index: int) -> float:
        return self.axes.get(index, 0.0)

    def get_hat(self, index: int) -> tuple[int, int]:
        return self.hats.get(index, (0, 0))


def manager_with(fake: FakeJoystick, mapping: dict[str, str] | None = None) -> ControllerManager:
    manager = ControllerManager.__new__(ControllerManager)
    manager._joy = fake
    manager._set_mapping(effective_mapping(mapping))
    return manager


class ControllerReadTests(unittest.TestCase):
    def test_face_buttons_follow_sdl_mapping(self) -> None:
        # This is the mapping reported for a real DualShock 4 on Linux.
        mapping = {"x": "b3", "y": "b2", "a": "b0", "b": "b1"}
        manager = manager_with(FakeJoystick(), mapping)
        self.assertTrue(manager._button("a"))
        self.assertFalse(manager._button("b"))
        self.assertTrue(manager._button("y"))
        self.assertFalse(manager._button("x"))

    def test_triggers_are_normalised(self) -> None:
        manager = manager_with(FakeJoystick())
        # a2 = -1 in the fake -> fully released; a5 = -1 -> released.
        self.assertEqual(manager._trigger("lefttrigger"), 0.0)
        manager._joy.axes[2] = 1.0
        self.assertEqual(manager._trigger("lefttrigger"), 1.0)

    def test_dpad_hat_bits(self) -> None:
        manager = manager_with(FakeJoystick())
        self.assertTrue(manager._digital("dpup"))
        self.assertFalse(manager._digital("dpdown"))
        self.assertTrue(manager._digital("dpleft"))
        self.assertFalse(manager._digital("dpright"))


class PadStateTests(unittest.TestCase):
    def test_trigger_hysteresis_prevents_chatter(self) -> None:
        state = PadState(connected=True)
        state.triggers["r2"] = 0.30
        self.assertFalse(state.control_pressed("r2", False))
        state.triggers["r2"] = 0.40
        self.assertTrue(state.control_pressed("r2", False))
        state.triggers["r2"] = 0.25  # below the press threshold but above release
        self.assertTrue(state.control_pressed("r2", True))
        state.triggers["r2"] = 0.15
        self.assertFalse(state.control_pressed("r2", True))

    def test_disconnected_pad_never_presses(self) -> None:
        state = PadState(connected=False)
        state.buttons["cross"] = True
        self.assertFalse(state.control_pressed("cross", False))


if __name__ == "__main__":
    unittest.main()
