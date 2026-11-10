"""Cross-platform controller discovery and normalised DualShock 4 state."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:
    import pygame
except Exception as exc:  # pragma: no cover - depends on installation
    pygame = None  # type: ignore[assignment]
    _PYGAME_IMPORT_ERROR: Exception | None = exc
else:
    _PYGAME_IMPORT_ERROR = None


FACE_CONTROLS = ("cross", "circle", "square", "triangle")
DPAD_CONTROLS = ("dpad_up", "dpad_down", "dpad_left", "dpad_right")
SHOULDER_CONTROLS = ("l1", "r1")
TRIGGER_CONTROLS = ("l2", "r2")
SYSTEM_CONTROLS = ("share", "options", "ps", "l3", "r3")

CONTROL_LABELS = {
    "cross": "Cross",
    "circle": "Circle",
    "square": "Square",
    "triangle": "Triangle",
    "l1": "L1",
    "r1": "R1",
    "l2": "L2",
    "r2": "R2",
    "share": "Share",
    "options": "Options",
    "ps": "PS",
    "l3": "L3",
    "r3": "R3",
    "dpad_up": "D-pad Up",
    "dpad_down": "D-pad Down",
    "dpad_left": "D-pad Left",
    "dpad_right": "D-pad Right",
}

# Ordered by how likely they are to be useful as a turbo trigger.
ACTIVATION_CONTROLS = (
    "r2",
    "l2",
    "r1",
    "l1",
    "cross",
    "circle",
    "square",
    "triangle",
    "share",
    "options",
    "ps",
    "l3",
    "r3",
    "dpad_up",
    "dpad_down",
    "dpad_left",
    "dpad_right",
)

ALL_CONTROLS = FACE_CONTROLS + SHOULDER_CONTROLS + TRIGGER_CONTROLS + SYSTEM_CONTROLS + DPAD_CONTROLS


def empty_buttons() -> dict[str, bool]:
    return {name: False for name in ALL_CONTROLS}


def empty_triggers() -> dict[str, float]:
    return {name: 0.0 for name in TRIGGER_CONTROLS}


def empty_axes() -> dict[str, float]:
    return {"left_x": 0.0, "left_y": 0.0, "right_x": 0.0, "right_y": 0.0}


@dataclass(slots=True)
class PadState:
    connected: bool = False
    name: str = ""
    buttons: dict[str, bool] = field(default_factory=empty_buttons)
    triggers: dict[str, float] = field(default_factory=empty_triggers)
    axes: dict[str, float] = field(default_factory=empty_axes)
    error: str = ""

    def control_value(self, control: str) -> float:
        if control in TRIGGER_CONTROLS:
            return self.triggers.get(control, 0.0)
        return 1.0 if self.buttons.get(control, False) else 0.0

    def control_active(self, control: str, threshold: float = 0.35) -> bool:
        if not self.connected:
            return False
        return self.control_value(control) >= threshold

    def active_controls(self, threshold: float = 0.25) -> set[str]:
        if not self.connected:
            return set()
        return {name for name in ALL_CONTROLS if self.control_value(name) >= threshold}

    def stick_magnitude(self, side: str) -> float:
        x = self.axes.get(f"{side}_x", 0.0)
        y = self.axes.get(f"{side}_y", 0.0)
        return min(1.0, (x * x + y * y) ** 0.5)


# Fallback for a Linux/PyGame DualShock 4 that SDL cannot match to a mapping.
# SDL's semantic names are still used when a game-controller mapping exists.
DEFAULT_MAPPING = {
    "a": "b0",
    "b": "b1",
    "x": "b3",
    "y": "b2",
    "back": "b8",
    "start": "b9",
    "guide": "b10",
    "leftshoulder": "b4",
    "rightshoulder": "b5",
    "leftstick": "b11",
    "rightstick": "b12",
    "lefttrigger": "a2",
    "righttrigger": "a5",
    "leftx": "a0",
    "lefty": "a1",
    "rightx": "a3",
    "righty": "a4",
    "dpup": "h0.1",
    "dpdown": "h0.4",
    "dpleft": "h0.8",
    "dpright": "h0.2",
}

_SEMANTIC_TO_CONTROL = {
    "a": "cross",
    "b": "circle",
    "x": "square",
    "y": "triangle",
    "leftshoulder": "l1",
    "rightshoulder": "r1",
    "back": "share",
    "start": "options",
    "guide": "ps",
    "leftstick": "l3",
    "rightstick": "r3",
}

_DPAD_TO_CONTROL = {
    "dpup": "dpad_up",
    "dpdown": "dpad_down",
    "dpleft": "dpad_left",
    "dpright": "dpad_right",
}


@dataclass(frozen=True, slots=True)
class Binding:
    kind: str
    index: int
    mask: int = 0
    invert: bool = False


def parse_binding(spec: str | None) -> Binding | None:
    """Parse an SDL binding such as ``b0``, ``a2``, ``a3~`` or ``h0.4``."""

    if not spec:
        return None
    spec = spec.strip()
    invert = spec.endswith("~")
    if invert:
        spec = spec[:-1]
    if len(spec) < 2:
        return None
    kind = spec[0].lower()
    try:
        if kind == "h":
            index_text, mask_text = spec[1:].split(".", 1)
            return Binding("h", int(index_text), int(mask_text), invert)
        if kind in {"a", "b"}:
            return Binding(kind, int(spec[1:]), invert=invert)
    except (TypeError, ValueError):
        return None
    return None


def effective_mapping(mapping: dict[str, str] | None) -> dict[str, str]:
    """Merge an SDL mapping over the fallback so no important control is lost."""

    merged = dict(DEFAULT_MAPPING)
    if mapping:
        for key, value in mapping.items():
            if value:
                merged[key] = value
    return merged


class ControllerManager:
    """Polls the first available gamepad and exposes a stable PS4-style state."""

    def __init__(self) -> None:
        self._ready = False
        self._init_error = ""
        self._joy = None
        self._sdl_controller = None
        self._mapping: dict[str, str] = dict(DEFAULT_MAPPING)
        self._joy_name = ""
        self._instance_id: int | None = None
        self._last_scan = 0.0
        self._last_state = PadState()
        self._last_connected = False
        self._initialise()

    @property
    def initialisation_error(self) -> str:
        return self._init_error

    def _initialise(self) -> None:
        if pygame is None:
            self._init_error = f"pygame could not be imported: {_PYGAME_IMPORT_ERROR}"
            return
        try:
            pygame.display.init()
            pygame.joystick.init()
            pygame.event.pump()
            self._ready = True
            self._scan(force=True)
        except Exception as exc:  # pragma: no cover - platform dependent
            self._init_error = f"Controller backend unavailable: {exc}"

    def _scan(self, force: bool = False) -> None:
        if not self._ready or pygame is None:
            return
        now = time.monotonic()
        if not force and self._joy is not None:
            return
        if not force and now - self._last_scan < 1.0:
            return
        self._last_scan = now

        if self._joy is not None:
            return

        try:
            count = pygame.joystick.get_count()
        except pygame.error:
            return
        if count <= 0:
            return

        chosen = None
        chosen_name = ""
        preferred = ("dualshock", "ps4", "wireless controller", "playstation", "sony")
        for index in range(count):
            candidate = None
            try:
                candidate = pygame.joystick.Joystick(index)
                candidate.init()
                name = candidate.get_name() or f"Gamepad {index + 1}"
            except pygame.error:
                if candidate is not None:
                    try:
                        candidate.quit()
                    except pygame.error:
                        pass
                continue

            if chosen is None:
                chosen, chosen_name = candidate, name
            elif any(token in name.lower() for token in preferred):
                try:
                    chosen.quit()
                except pygame.error:
                    pass
                chosen, chosen_name = candidate, name
                break
            else:
                try:
                    candidate.quit()
                except pygame.error:
                    pass

        if chosen is None:
            return

        self._joy = chosen
        self._joy_name = chosen_name
        try:
            self._instance_id = chosen.get_instance_id()
        except (AttributeError, pygame.error):
            self._instance_id = None

        mapping: dict[str, str] = {}
        try:
            from pygame._sdl2 import controller as sdl_controller

            sdl_controller.init()
            self._sdl_controller = sdl_controller.Controller.from_joystick(chosen)
            mapping = self._sdl_controller.get_mapping() or {}
        except Exception:
            self._sdl_controller = None
            mapping = {}
        self._mapping = effective_mapping(mapping)

    def _disconnect(self) -> None:
        if self._joy is not None:
            try:
                self._joy.quit()
            except Exception:
                pass
        self._joy = None
        self._sdl_controller = None
        self._instance_id = None
        self._joy_name = ""
        self._mapping = dict(DEFAULT_MAPPING)

    def _binding(self, semantic: str) -> Binding | None:
        return parse_binding(self._mapping.get(semantic))

    def _button(self, semantic: str) -> bool:
        if self._joy is None:
            return False
        binding = self._binding(semantic)
        if binding is None:
            return False
        try:
            if binding.kind == "b":
                return bool(self._joy.get_button(binding.index))
            if binding.kind == "a":
                value = self._joy.get_axis(binding.index)
                return value < -0.5 if binding.invert else value > 0.5
            if binding.kind == "h":
                hat = self._joy.get_hat(binding.index)
                return self._hat_has(hat, binding.mask)
        except (pygame.error, IndexError):
            return False
        return False

    def _axis(self, semantic: str, fallback: float = 0.0) -> float:
        if self._joy is None:
            return fallback
        binding = self._binding(semantic)
        if binding is None:
            return fallback
        try:
            if binding.kind == "a":
                value = float(self._joy.get_axis(binding.index))
                if binding.invert:
                    value = -value
                return max(-1.0, min(1.0, value))
            if binding.kind == "b":
                return 1.0 if self._joy.get_button(binding.index) else 0.0
            if binding.kind == "h":
                return 1.0 if self._hat_has(self._joy.get_hat(binding.index), binding.mask) else 0.0
        except (pygame.error, IndexError):
            return fallback
        return fallback

    def _trigger(self, semantic: str) -> float:
        if self._joy is None:
            return 0.0
        binding = self._binding(semantic)
        if binding is None:
            return 0.0
        try:
            if binding.kind == "a":
                value = float(self._joy.get_axis(binding.index))
                if binding.invert:
                    value = -value
                return max(0.0, min(1.0, (value + 1.0) / 2.0))
            if binding.kind == "b":
                return 1.0 if self._joy.get_button(binding.index) else 0.0
        except (pygame.error, IndexError):
            return 0.0
        return 0.0

    def _digital(self, semantic: str) -> bool:
        if self._joy is None:
            return False
        binding = self._binding(semantic)
        if binding is None:
            return False
        try:
            if binding.kind == "h":
                return self._hat_has(self._joy.get_hat(binding.index), binding.mask)
            if binding.kind == "b":
                active = bool(self._joy.get_button(binding.index))
                return not active if binding.invert else active
            if binding.kind == "a":
                value = self._joy.get_axis(binding.index)
                if binding.invert:
                    return value < -0.5
                return value > 0.5
        except (pygame.error, IndexError):
            return False
        return False

    @staticmethod
    def _hat_has(hat: tuple[int, int], mask: int) -> bool:
        x, y = hat
        if mask == 1:
            return y > 0
        if mask == 2:
            return x > 0
        if mask == 4:
            return y < 0
        if mask == 8:
            return x < 0
        return False

    def _handle_events(self) -> None:
        if pygame is None or not self._ready:
            return
        try:
            pygame.event.pump()
            events = pygame.event.get()
        except pygame.error:
            return
        for event in events:
            if event.type == pygame.JOYDEVICEREMOVED:
                if self._instance_id is None or getattr(event, "instance_id", None) == self._instance_id:
                    self._disconnect()
            elif event.type == pygame.JOYDEVICEADDED:
                self._last_scan = 0.0

    def poll(self) -> PadState:
        if not self._ready:
            return PadState(connected=False, error=self._init_error)

        self._handle_events()
        self._scan()
        if self._joy is None:
            if self._last_connected:
                self._last_connected = False
            self._last_state = PadState(connected=False, error=self._init_error)
            return self._last_state

        try:
            if not self._joy.get_init():
                self._disconnect()
                self._last_state = PadState(connected=False)
                return self._last_state
        except pygame.error:
            self._disconnect()
            self._last_state = PadState(connected=False)
            return self._last_state

        buttons = empty_buttons()
        for semantic, control in _SEMANTIC_TO_CONTROL.items():
            buttons[control] = self._button(semantic)
        for semantic, control in _DPAD_TO_CONTROL.items():
            buttons[control] = self._digital(semantic)

        triggers = {
            "l2": self._trigger("lefttrigger"),
            "r2": self._trigger("righttrigger"),
        }
        buttons["l2"] = triggers["l2"] >= 0.35
        buttons["r2"] = triggers["r2"] >= 0.35

        axes = {
            "left_x": self._axis("leftx"),
            "left_y": self._axis("lefty"),
            "right_x": self._axis("rightx"),
            "right_y": self._axis("righty"),
        }

        self._last_connected = True
        self._last_state = PadState(
            connected=True,
            name=self._joy_name,
            buttons=buttons,
            triggers=triggers,
            axes=axes,
        )
        return self._last_state

    def shutdown(self) -> None:
        self._disconnect()
        if pygame is not None and self._ready:
            try:
                pygame.joystick.quit()
            except Exception:
                pass
            try:
                pygame.display.quit()
            except Exception:
                pass
        self._ready = False
