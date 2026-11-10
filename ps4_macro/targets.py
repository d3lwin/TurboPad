"""Output target definitions and keyboard-capture helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TargetKind = Literal["key", "mouse"]


@dataclass(frozen=True, slots=True)
class TargetAction:
    """A keyboard key or mouse button that TurboPad can simulate."""

    key: str
    label: str
    kind: TargetKind
    value: str

    @property
    def description(self) -> str:
        if self.kind == "mouse":
            return "Mouse button"
        return "Keyboard key"


# The most useful game keys are listed first, then the full letter/number set.
_BUILTINS: tuple[tuple[str, str, str], ...] = (
    ("space", "Space", "space"),
    ("enter", "Enter", "enter"),
    ("tab", "Tab", "tab"),
    ("escape", "Escape", "esc"),
    ("backspace", "Backspace", "backspace"),
    ("shift", "Shift", "shift"),
    ("ctrl", "Ctrl", "ctrl"),
    ("alt", "Alt", "alt"),
    ("mouse_left", "Left Mouse", "left"),
    ("mouse_right", "Right Mouse", "right"),
    ("mouse_middle", "Middle Mouse", "middle"),
    ("e", "E", "e"),
    ("f", "F", "f"),
    ("r", "R", "r"),
    ("q", "Q", "q"),
    ("c", "C", "c"),
    ("v", "V", "v"),
    ("g", "G", "g"),
    ("1", "1", "1"),
    ("2", "2", "2"),
    ("3", "3", "3"),
    ("4", "4", "4"),
    ("5", "5", "5"),
    ("6", "6", "6"),
    ("7", "7", "7"),
    ("8", "8", "8"),
    ("9", "9", "9"),
    ("0", "0", "0"),
)

_LETTERS = tuple(chr(code) for code in range(ord("a"), ord("z") + 1))
_NUMBERS = tuple(str(number) for number in range(10))
_SPECIALS = (
    ("f1", "F1"),
    ("f2", "F2"),
    ("f3", "F3"),
    ("f4", "F4"),
    ("f5", "F5"),
    ("f6", "F6"),
    ("f7", "F7"),
    ("f8", "F8"),
    ("f9", "F9"),
    ("f10", "F10"),
    ("f11", "F11"),
    ("f12", "F12"),
    ("up", "Arrow Up"),
    ("down", "Arrow Down"),
    ("left", "Arrow Left"),
    ("right", "Arrow Right"),
    ("home", "Home"),
    ("end", "End"),
    ("page_up", "Page Up"),
    ("page_down", "Page Down"),
    ("insert", "Insert"),
    ("delete", "Delete"),
    ("caps_lock", "Caps Lock"),
)


def _build_targets() -> tuple[TargetAction, ...]:
    targets: list[TargetAction] = []
    seen: set[str] = set()

    for key, label, value in _BUILTINS:
        kind: TargetKind = "mouse" if key.startswith("mouse_") else "key"
        targets.append(TargetAction(key, label, kind, value))
        seen.add(key)

    for letter in _LETTERS:
        if letter in seen:
            continue
        targets.append(TargetAction(letter, letter.upper(), "key", letter))

    for number in _NUMBERS:
        if number in seen:
            continue
        targets.append(TargetAction(f"number_{number}", number, "key", number))

    for key, label in _SPECIALS:
        # F8 is reserved for the global panic stop.
        if key == "f8":
            continue
        targets.append(TargetAction(key, label, "key", key))

    return tuple(targets)


BUILTIN_TARGETS = _build_targets()
TARGETS_BY_KEY = {target.key: target for target in BUILTIN_TARGETS}
DEFAULT_TARGET = TARGETS_BY_KEY["space"]


_KEYSYM_MAP = {
    "Return": ("enter", "Enter", "enter"),
    "KP_Enter": ("enter", "Enter", "enter"),
    "Escape": ("escape", "Escape", "esc"),
    "BackSpace": ("backspace", "Backspace", "backspace"),
    "Tab": ("tab", "Tab", "tab"),
    "space": ("space", "Space", "space"),
    "Shift_L": ("shift", "Shift", "shift"),
    "Shift_R": ("shift", "Shift", "shift"),
    "Control_L": ("ctrl", "Ctrl", "ctrl"),
    "Control_R": ("ctrl", "Ctrl", "ctrl"),
    "Alt_L": ("alt", "Alt", "alt"),
    "Alt_R": ("alt", "Alt", "alt"),
    "Super_L": ("cmd", "Cmd / Win", "cmd"),
    "Super_R": ("cmd", "Cmd / Win", "cmd"),
    "Caps_Lock": ("caps_lock", "Caps Lock", "caps_lock"),
    "Delete": ("delete", "Delete", "delete"),
    "Insert": ("insert", "Insert", "insert"),
    "Home": ("home", "Home", "home"),
    "End": ("end", "End", "end"),
    "Page_Up": ("page_up", "Page Up", "page_up"),
    "Page_Down": ("page_down", "Page Down", "page_down"),
    "Up": ("up", "Arrow Up", "up"),
    "Down": ("down", "Arrow Down", "down"),
    "Left": ("left", "Arrow Left", "left"),
    "Right": ("right", "Arrow Right", "right"),
}

for _number in range(1, 13):
    _KEYSYM_MAP[f"F{_number}"] = (f"f{_number}", f"F{_number}", f"f{_number}")


def target_from_capture(keysym: str, char: str) -> TargetAction | None:
    """Translate a Tk key event into an output target.

    Returns ``None`` for modifier-only or unsupported events.
    """

    if keysym in _KEYSYM_MAP:
        key, label, value = _KEYSYM_MAP[keysym]
        return TargetAction(key, label, "key", value)

    if keysym.startswith("KP_"):
        key = keysym[3:].lower()
        if len(key) == 1 and key.isalnum():
            return TargetAction(f"number_{key}", key.upper(), "key", key)

    if char and char.isprintable() and not char.isspace():
        value = char.lower() if char.isalpha() else char
        label = value.upper() if value.isalpha() else value
        return TargetAction(f"captured_{ord(value):x}", f"Key: {label}", "key", value)

    return None


def custom_target_for_char(char: str) -> TargetAction | None:
    """Create a target from a literal character, used by the capture flow."""

    if not char or not char.isprintable() or char.isspace():
        return None
    value = char.lower() if char.isalpha() else char
    label = value.upper() if value.isalpha() else value
    return TargetAction(f"captured_{ord(value):x}", f"Key: {label}", "key", value)
