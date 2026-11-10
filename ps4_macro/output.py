"""Keyboard and mouse output through pynput."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .targets import TargetAction

try:  # Importing pynput can fail on a headless or unconfigured machine.
    from pynput.keyboard import Controller as KeyboardController
    from pynput.keyboard import Key, KeyCode
    from pynput.mouse import Button, Controller as MouseController

    _PYNPUT_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - depends on the host system
    KeyboardController = None  # type: ignore[assignment]
    Key = None  # type: ignore[assignment]
    KeyCode = None  # type: ignore[assignment]
    Button = None  # type: ignore[assignment]
    MouseController = None  # type: ignore[assignment]
    _PYNPUT_IMPORT_ERROR = exc


class OutputError(RuntimeError):
    """Raised when a simulated input cannot be sent."""


@dataclass(frozen=True, slots=True)
class _Held:
    kind: str
    value: str


def _special_keys() -> dict[str, object]:
    if Key is None:
        return {}
    names = {
        "alt": "alt",
        "alt_l": "alt_l",
        "alt_r": "alt_r",
        "backspace": "backspace",
        "caps_lock": "caps_lock",
        "cmd": "cmd",
        "cmd_l": "cmd_l",
        "cmd_r": "cmd_r",
        "ctrl": "ctrl",
        "ctrl_l": "ctrl_l",
        "ctrl_r": "ctrl_r",
        "delete": "delete",
        "down": "down",
        "end": "end",
        "enter": "enter",
        "esc": "esc",
        "home": "home",
        "insert": "insert",
        "left": "left",
        "page_down": "page_down",
        "page_up": "page_up",
        "right": "right",
        "shift": "shift",
        "shift_l": "shift_l",
        "shift_r": "shift_r",
        "space": "space",
        "tab": "tab",
        "up": "up",
    }
    for number in range(1, 21):
        names[f"f{number}"] = f"f{number}"
    return {name: getattr(Key, attr) for name, attr in names.items() if hasattr(Key, attr)}


SPECIAL_KEYS = _special_keys()

_MOUSE_BUTTONS = {}
if Button is not None:
    _MOUSE_BUTTONS = {
        "left": Button.left,
        "right": Button.right,
        "middle": Button.middle,
    }


class OutputDriver:
    """Serialises pynput calls and keeps track of currently held inputs."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._keyboard = None
        self._mouse = None
        self._held: dict[_Held, bool] = {}
        self.error: str | None = None
        self._initialise()

    def _initialise(self) -> None:
        if _PYNPUT_IMPORT_ERROR is not None:
            self.error = f"pynput could not be imported: {_PYNPUT_IMPORT_ERROR}"
            return
        try:
            self._keyboard = KeyboardController()
            self._mouse = MouseController()
        except Exception as exc:  # pragma: no cover - platform dependent
            self.error = f"Output device unavailable: {exc}"

    @property
    def available(self) -> bool:
        return self.error is None and self._keyboard is not None and self._mouse is not None

    def _resolve_key(self, value: str):
        if KeyCode is None:
            raise OutputError("Keyboard output is not available.")
        special = SPECIAL_KEYS.get(value)
        if special is not None:
            return special
        if len(value) == 1:
            return KeyCode.from_char(value)
        raise OutputError(f"Unknown keyboard key: {value!r}")

    def press(self, target: TargetAction) -> None:
        if not self.available:
            raise OutputError(self.error or "Output device is unavailable.")
        with self._lock:
            try:
                if target.kind == "mouse":
                    button = _MOUSE_BUTTONS.get(target.value)
                    if button is None:
                        raise OutputError(f"Unknown mouse button: {target.value!r}")
                    self._mouse.press(button)
                else:
                    self._keyboard.press(self._resolve_key(target.value))
                self._held[_Held(target.kind, target.value)] = True
            except OutputError:
                raise
            except Exception as exc:
                raise OutputError(f"Could not press {target.label}: {exc}") from exc

    def release(self, target: TargetAction) -> None:
        if not self.available:
            return
        with self._lock:
            try:
                if target.kind == "mouse":
                    button = _MOUSE_BUTTONS.get(target.value)
                    if button is not None:
                        self._mouse.release(button)
                else:
                    self._keyboard.release(self._resolve_key(target.value))
            except Exception:
                # A failed release must not mask the worker's primary error or
                # prevent other held inputs from being cleaned up.
                pass
            finally:
                self._held.pop(_Held(target.kind, target.value), None)

    def release_all(self) -> None:
        if not self.available:
            return
        with self._lock:
            held = list(self._held)
            for item in held:
                try:
                    if item.kind == "mouse":
                        button = _MOUSE_BUTTONS.get(item.value)
                        if button is not None:
                            self._mouse.release(button)
                    else:
                        self._keyboard.release(self._resolve_key(item.value))
                except Exception:
                    pass
                self._held.pop(item, None)
