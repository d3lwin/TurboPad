"""Keyboard and mouse output through pynput."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
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

    def __init__(self, start_guardian: bool = True) -> None:
        self._lock = threading.RLock()
        self._keyboard = None
        self._mouse = None
        self._held: dict[_Held, bool] = {}
        # Everything pressed since launch. A panic re-releases these too, so a
        # key-up lost during a focus change or driver hiccup cannot leave the
        # game with a direction stuck down.
        self._recent: dict[_Held, bool] = {}
        self._guard: subprocess.Popen[str] | None = None
        self.error: str | None = None
        self._initialise()
        if start_guardian and self.available:
            self._spawn_guardian()

    def _guardian_command(self) -> list[str] | None:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--release-guard"]
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.environ.get("PYTHONPATH", "")
        if root not in env_path.split(os.pathsep):
            os.environ["PYTHONPATH"] = root + (os.pathsep + env_path if env_path else "")
        return [sys.executable, "-m", "ps4_macro.guard"]

    def _spawn_guardian(self) -> None:
        if os.environ.get("TURBOPAD_NO_GUARD"):
            return
        command = self._guardian_command()
        if command is None:
            return
        options: dict[str, object] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "text": True,
            "bufsize": 1,
            "close_fds": True,
        }
        if os.name == "nt":
            options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            self._guard = subprocess.Popen(command, **options)  # type: ignore[arg-type]
        except Exception:
            self._guard = None

    def _guard_send(self, item: _Held) -> None:
        guard = self._guard
        if guard is None or guard.stdin is None:
            return
        try:
            guard.stdin.write(f"P|{item.kind}|{item.value}\n")
            guard.stdin.flush()
        except Exception:
            self._guard = None

    def release_targets(self, targets, repeats: int = 2) -> None:
        """Release explicit targets; used by the crash guard and tests."""

        if not self.available:
            return
        with self._lock:
            for target in targets:
                item = _Held(target.kind, target.value)
                for _ in range(max(1, repeats)):
                    self._release_item(item)
                self._held.pop(item, None)

    def close(self) -> None:
        """Release output and stop the crash guard cleanly."""

        self.emergency_release()
        guard = self._guard
        self._guard = None
        if guard is None:
            return
        try:
            if guard.stdin is not None:
                guard.stdin.write("Q\n")
                guard.stdin.flush()
                guard.stdin.close()
        except Exception:
            pass
        try:
            guard.wait(timeout=1.5)
        except Exception:
            try:
                guard.terminate()
            except Exception:
                pass

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
                item = _Held(target.kind, target.value)
                new_target = item not in self._recent
                self._held[item] = True
                self._recent[item] = True
                if new_target:
                    self._guard_send(item)
            except OutputError:
                raise
            except Exception as exc:
                raise OutputError(f"Could not press {target.label}: {exc}") from exc

    def _release_item(self, item: _Held) -> None:
        try:
            if item.kind == "mouse":
                button = _MOUSE_BUTTONS.get(item.value)
                if button is not None:
                    self._mouse.release(button)
            else:
                self._keyboard.release(self._resolve_key(item.value))
        except Exception:
            # A failed release must not mask the worker's primary error or
            # prevent other held inputs from being cleaned up.
            pass

    def release(self, target: TargetAction) -> None:
        if not self.available:
            return
        with self._lock:
            self._release_item(_Held(target.kind, target.value))
            self._held.pop(_Held(target.kind, target.value), None)

    def release_all(self) -> None:
        if not self.available:
            return
        with self._lock:
            for item in list(self._held):
                self._release_item(item)
                self._held.pop(item, None)

    def emergency_release(self) -> None:
        """Release held inputs and re-send every key-up touched this session.

        Repeating the release is deliberate: games running under Wine or with a
        keyboard grab occasionally miss a single synthetic key-up, which then
        looks like an endless direction drift in a menu.
        """

        if not self.available:
            return
        with self._lock:
            for item in list(self._recent):
                for _ in range(5):
                    self._release_item(item)
                    time.sleep(0.01)
            self._held.clear()
