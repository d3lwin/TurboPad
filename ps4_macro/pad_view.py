"""The live DualShock 4 visualiser."""

from __future__ import annotations

import math
import tkinter as tk
from pathlib import Path

from . import theme
from .controller import PadState

try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - Pillow is a runtime requirement
    Image = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]

# The SVG artwork occupies 600x400 inside a slightly larger view box.  The
# extra room holds the drop shadow and the shoulder read-outs.
PAD_W = 600
PAD_H = 400
PAD_OFFSET = 10
VIEW_W = 620
VIEW_H = 430

ASSET_PATH = Path(__file__).resolve().parent.parent / "assets" / "ds4_front.png"

ACCENTS: dict[str, str] = {
    "cross": theme.CROSS,
    "circle": theme.CIRCLE,
    "square": theme.SQUARE,
    "triangle": theme.TRIANGLE,
    "share": "#8ec5ff",
    "options": "#8ec5ff",
    "ps": theme.SYSTEM,
    "dpad_up": theme.DPAD,
    "dpad_down": theme.DPAD,
    "dpad_left": theme.DPAD,
    "dpad_right": theme.DPAD,
    "l3": theme.DPAD,
    "r3": theme.DPAD,
    "l1": theme.SHOULDER,
    "r1": theme.SHOULDER,
    "l2": theme.SHOULDER,
    "r2": theme.SHOULDER,
}

FACE_BUTTONS = {
    "triangle": (472.1, 85.1),
    "cross": (472.1, 164.9),
    "square": (432.0, 124.8),
    "circle": (513.1, 124.8),
}

DPAD_KEYS = {
    "dpad_up": (129.7, 98.5, 19.0, 16.0),
    "dpad_down": (129.7, 153.5, 19.0, 16.0),
    "dpad_left": (95.0, 126.0, 16.0, 19.0),
    "dpad_right": (164.5, 126.0, 16.0, 19.0),
}


class PadCanvas(tk.Canvas):
    def __init__(self, parent: tk.Misc, *, font_family: str) -> None:
        super().__init__(
            parent,
            bg=theme.CARD,
            bd=0,
            highlightthickness=0,
            width=VIEW_W,
            height=VIEW_H,
        )
        self.font_family = font_family
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._state = PadState()
        self._spam_active = False
        self._signature: tuple | None = None
        self._items: dict[str, dict[str, int]] = {}
        self._sticks: dict[str, dict[str, int | float]] = {}
        self._trigger_items: dict[str, dict[str, object]] = {}
        self._overlay: dict[str, int] = {}
        self._lightbar_item = 0
        self._lightbar_glow = 0
        self._photo = None
        self._source = None
        self._last_width = 0
        self._last_height = 0
        if Image is not None and ASSET_PATH.exists():
            self._source = Image.open(ASSET_PATH).convert("RGBA")
        self.bind("<Configure>", self._on_configure)

    # ------------------------------------------------------------------ helpers
    def _x(self, value: float) -> float:
        return self._offset_x + (PAD_OFFSET + value) * self._scale

    def _y(self, value: float) -> float:
        return self._offset_y + (PAD_OFFSET + value) * self._scale

    def _font(self, size: int | float, weight: str = "normal") -> tuple:
        return (self.font_family, max(6, round(size * self._scale)), weight)

    def _width(self, amount: float = 1.0) -> int:
        return max(1, round(amount * self._scale))

    def _rounded_points(self, x1: float, y1: float, x2: float, y2: float, radius: float) -> list[float]:
        radius = max(0.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
        points: list[float] = []
        corners = (
            (x2 - radius, y1 + radius, -90, 0),
            (x2 - radius, y2 - radius, 0, 90),
            (x1 + radius, y2 - radius, 90, 180),
            (x1 + radius, y1 + radius, 180, 270),
        )
        for cx, cy, start, end in corners:
            steps = 8
            for step in range(steps + 1):
                angle = math.radians(start + (end - start) * step / steps)
                px = cx + radius * math.cos(angle)
                py = cy + radius * math.sin(angle)
                points.extend((self._x(px), self._y(py)))
        return points

    def _rounded_rect(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        radius: float,
        *,
        fill: str,
        outline: str = "",
        width: float = 1.0,
    ) -> int:
        return self.create_polygon(
            *self._rounded_points(x1, y1, x2, y2, radius),
            fill=fill,
            outline=outline,
            width=self._width(width),
            joinstyle=tk.ROUND,
        )

    def _move_rounded_rect(
        self,
        item: int,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        radius: float,
    ) -> None:
        self.coords(item, *self._rounded_points(x1, y1, x2, y2, radius))

    # ------------------------------------------------------------------ drawing
    def _on_configure(self, event: tk.Event) -> None:
        width = max(1, event.width)
        height = max(1, event.height)
        if width == self._last_width and height == self._last_height:
            return
        self._last_width = width
        self._last_height = height
        self._scale = min(width / VIEW_W, height / VIEW_H)
        self._offset_x = (width - VIEW_W * self._scale) / 2
        self._offset_y = (height - VIEW_H * self._scale) / 2
        self._build()

    def _build(self) -> None:
        self.delete("all")
        self._items.clear()
        self._sticks.clear()
        self._trigger_items.clear()
        self._overlay = {}
        self._lightbar_item = 0
        self._lightbar_glow = 0

        self._draw_artwork()
        self._draw_lightbar()
        self._draw_face_buttons()
        self._draw_dpad()
        self._draw_pill("share", 188.75, 71.75, 9.25, 15.75)
        self._draw_pill("options", 412.5, 71.75, 9.5, 15.75)
        self._draw_round("ps", 300.0, 203.4, 13.75)
        self._draw_sticks()
        self._draw_shoulders()
        self._build_overlay()

        self._signature = None
        self._apply_state(self._state, spam_active=self._spam_active)

    def _draw_artwork(self) -> None:
        if self._source is None or ImageTk is None:
            self.create_text(
                self._x(PAD_W / 2),
                self._y(PAD_H / 2),
                text="Controller artwork unavailable\nInstall Pillow and run the app from the project folder",
                fill=theme.RED,
                font=self._font(11, "bold"),
                justify="center",
                width=self._width(320),
            )
            return

        size = (
            max(1, round(VIEW_W * self._scale)),
            max(1, round(VIEW_H * self._scale)),
        )
        resized = self._source.resize(size, Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(resized)
        self.create_image(
            self._offset_x,
            self._offset_y,
            image=self._photo,
            anchor="nw",
        )

    def _draw_lightbar(self) -> None:
        self._lightbar_glow = self.create_line(
            self._x(228),
            self._y(47),
            self._x(372),
            self._y(47),
            fill=theme.ACCENT,
            width=self._width(9),
            capstyle=tk.ROUND,
            stipple="gray25",
            state="hidden",
        )
        self._lightbar_item = self.create_line(
            self._x(228),
            self._y(47),
            self._x(372),
            self._y(47),
            fill="#1d5c78",
            width=self._width(3),
            capstyle=tk.ROUND,
        )

    # ------------------------------------------------------------------ controls
    def _circle(self, control: str, cx: float, cy: float, radius: float) -> None:
        accent = ACCENTS[control]
        ring = self.create_oval(
            self._x(cx - radius),
            self._y(cy - radius),
            self._x(cx + radius),
            self._y(cy + radius),
            outline=accent,
            fill="",
            width=self._width(2.0),
            state="hidden",
        )
        self._items[control] = {"ring": ring}

    def _rounded_control(
        self,
        control: str,
        cx: float,
        cy: float,
        half_w: float,
        half_h: float,
        radius: float,
    ) -> None:
        accent = ACCENTS[control]
        ring = self._rounded_rect(
            cx - half_w,
            cy - half_h,
            cx + half_w,
            cy + half_h,
            radius,
            fill="",
            outline=accent,
            width=2.0,
        )
        self.itemconfigure(ring, state="hidden")
        self._items[control] = {"ring": ring}

    def _draw_face_buttons(self) -> None:
        for control, (x, y) in FACE_BUTTONS.items():
            self._circle(control, x, y, 21.0)

    def _draw_dpad(self) -> None:
        for control, (x, y, half_w, half_h) in DPAD_KEYS.items():
            self._rounded_control(control, x, y, half_w, half_h, 9.0)

    def _draw_pill(self, control: str, cx: float, cy: float, half_w: float, half_h: float) -> None:
        self._rounded_control(control, cx, cy, half_w + 3.0, half_h + 4.0, 11.0)

    def _draw_round(self, control: str, cx: float, cy: float, radius: float) -> None:
        self._circle(control, cx, cy, radius + 2.5)

    # ------------------------------------------------------------------- sticks
    def _draw_sticks(self) -> None:
        for control, cx, cy in (("l3", 213.4, 197.9), ("r3", 388.3, 197.9)):
            accent = ACCENTS[control]
            ring = self.create_oval(
                self._x(cx - 21),
                self._y(cy - 21),
                self._x(cx + 21),
                self._y(cy + 21),
                outline=accent,
                fill="",
                width=self._width(2.0),
                state="hidden",
            )
            vector = self.create_line(
                self._x(cx),
                self._y(cy),
                self._x(cx),
                self._y(cy),
                fill=accent,
                width=self._width(1.6),
                state="hidden",
            )
            dot = self.create_oval(
                self._x(cx - 4),
                self._y(cy - 4),
                self._x(cx + 4),
                self._y(cy + 4),
                fill=accent,
                outline="",
                state="hidden",
            )
            self._sticks[control] = {
                "ring": ring,
                "vector": vector,
                "dot": dot,
                "cx": cx,
                "cy": cy,
                "reach": 15.0,
            }

    # ----------------------------------------------------------------- shoulders
    def _draw_shoulders(self) -> None:
        specs = (
            ("l2", 112.0, 8.0, 175.0, 11.5, "L2", "left"),
            ("l1", 112.0, 20.0, 175.0, 23.5, "L1", "left"),
            ("r2", 425.0, 8.0, 488.0, 11.5, "R2", "right"),
            ("r1", 425.0, 20.0, 488.0, 23.5, "R1", "right"),
        )
        for control, x1, y1, x2, y2, label, side in specs:
            accent = ACCENTS[control]
            base = self._rounded_rect(
                x1,
                y1,
                x2,
                y2,
                (y2 - y1) / 2,
                fill=theme.CARD_ALT,
                outline=theme.BORDER_SOFT,
                width=1.0,
            )
            fill = self._rounded_rect(
                x1 + 1.0,
                y1 + 1.0,
                x2 - 1.0,
                y2 - 1.0,
                (y2 - y1) / 2 - 1.0,
                fill=accent,
                outline="",
            )
            self.itemconfigure(fill, state="hidden")
            label_x = x1 - 5.0 if side == "left" else x2 + 5.0
            text = self.create_text(
                self._x(label_x),
                self._y((y1 + y2) / 2),
                text=label,
                fill=theme.MUTED,
                font=self._font(6.8, "bold"),
                anchor="e" if side == "left" else "w",
            )
            self._trigger_items[control] = {
                "base": base,
                "fill": fill,
                "text": text,
                "bounds": (x1 + 1.0, y1 + 1.0, x2 - 1.0, y2 - 1.0),
                "mirror": side == "right",
                "analog": control in ("l2", "r2"),
                "label": label,
            }

    # ------------------------------------------------------------------- overlay
    def _build_overlay(self) -> None:
        rect = self._rounded_rect(
            214,
            49,
            386,
            142,
            14,
            fill=theme.BG,
            outline=theme.BORDER,
            width=1.0,
        )
        self.itemconfigure(rect, stipple="gray75")
        title = self.create_text(
            self._x(300),
            self._y(88),
            text="NO CONTROLLER",
            fill=theme.TEXT,
            font=self._font(12, "bold"),
        )
        message = self.create_text(
            self._x(300),
            self._y(107),
            text="Connect via USB or Bluetooth",
            fill=theme.TEXT_SOFT,
            font=self._font(7.4),
            width=self._width(158),
            justify="center",
        )
        hint = self.create_text(
            self._x(300),
            self._y(125),
            text="Auto-detect is on",
            fill=theme.ACCENT,
            font=self._font(6.8, "bold"),
        )
        self._overlay = {
            "rect": rect,
            "title": title,
            "message": message,
            "hint": hint,
        }

    # ------------------------------------------------------------------- updates
    def set_state(self, state: PadState, spam_active: bool = False) -> None:
        signature = (
            state.connected,
            state.error,
            spam_active,
            tuple(state.buttons.get(name, False) for name in sorted(state.buttons)),
            tuple(round(state.triggers.get(name, 0.0), 2) for name in sorted(state.triggers)),
            tuple(round(state.axes.get(name, 0.0), 2) for name in sorted(state.axes)),
        )
        if signature == self._signature:
            return
        self._signature = signature
        self._state = state
        self._spam_active = spam_active
        self._apply_state(state, spam_active=spam_active)

    def _apply_state(self, state: PadState, spam_active: bool = False) -> None:
        connected = state.connected

        if self._lightbar_item:
            if spam_active:
                colour = theme.ACCENT
                width = 4
            elif connected:
                colour = "#2f8fbd"
                width = 3
            else:
                colour = "#16384a"
                width = 3
            self.itemconfigure(self._lightbar_item, fill=colour, width=self._width(width))
        if self._lightbar_glow:
            if spam_active:
                self.itemconfigure(
                    self._lightbar_glow,
                    fill=theme.ACCENT,
                    state="normal",
                )
            else:
                self.itemconfigure(self._lightbar_glow, state="hidden")

        for control, items in self._items.items():
            active = connected and state.buttons.get(control, False)
            self.itemconfigure(items["ring"], state="normal" if active else "hidden")

        for control, items in self._trigger_items.items():
            is_analog = bool(items["analog"])
            if not connected:
                value = 0.0
            elif is_analog:
                value = max(0.0, min(1.0, state.triggers.get(control, 0.0)))
            else:
                value = 1.0 if state.buttons.get(control, False) else 0.0

            x1, y1, x2, y2 = items["bounds"]  # type: ignore[misc]
            usable = x2 - x1
            if bool(items["mirror"]):
                fill_x1 = x2 - usable * value
                fill_x2 = x2
            else:
                fill_x1 = x1
                fill_x2 = x1 + usable * value
            radius = max(0.0, (y2 - y1) / 2 - 0.5)
            if value > 0.02:
                self._move_rounded_rect(items["fill"], fill_x1, y1, fill_x2, y2, radius)  # type: ignore[arg-type]
                self.itemconfigure(items["fill"], state="normal")
                self.itemconfigure(items["text"], fill=ACCENTS[control])
                self.itemconfigure(items["base"], outline=ACCENTS[control])
            else:
                self.itemconfigure(items["fill"], state="hidden")
                self.itemconfigure(items["text"], fill=theme.MUTED)
                self.itemconfigure(items["base"], outline=theme.BORDER_SOFT)

        for control, items in self._sticks.items():
            side = "left" if control == "l3" else "right"
            if connected:
                axis_x = max(-1.0, min(1.0, state.axes.get(f"{side}_x", 0.0)))
                axis_y = max(-1.0, min(1.0, state.axes.get(f"{side}_y", 0.0)))
            else:
                axis_x = axis_y = 0.0
            cx = float(items["cx"])  # type: ignore[arg-type]
            cy = float(items["cy"])  # type: ignore[arg-type]
            reach = float(items["reach"])  # type: ignore[arg-type]
            knob_x = cx + axis_x * reach
            knob_y = cy + axis_y * reach
            moving = (axis_x * axis_x + axis_y * axis_y) ** 0.5 > 0.12
            pressed = connected and state.buttons.get(control, False)
            active = connected and (moving or pressed)

            self.coords(
                items["ring"],
                self._x(knob_x - 21),
                self._y(knob_y - 21),
                self._x(knob_x + 21),
                self._y(knob_y + 21),
            )
            self.coords(
                items["dot"],
                self._x(knob_x - 4),
                self._y(knob_y - 4),
                self._x(knob_x + 4),
                self._y(knob_y + 4),
            )
            self.coords(
                items["vector"],
                self._x(cx),
                self._y(cy),
                self._x(knob_x),
                self._y(knob_y),
            )

            item_state = "normal" if active else "hidden"
            self.itemconfigure(items["ring"], state=item_state)
            self.itemconfigure(items["dot"], state=item_state)
            self.itemconfigure(
                items["vector"],
                state="normal" if moving else "hidden",
            )

        self._update_overlay(state)

    def _update_overlay(self, state: PadState) -> None:
        if not self._overlay:
            return
        if state.connected:
            for item in self._overlay.values():
                self.itemconfigure(item, state="hidden")
            return
        for item in self._overlay.values():
            self.itemconfigure(item, state="normal")
        if state.error:
            self.itemconfigure(self._overlay["title"], text="CONTROLLER OFFLINE")
            self.itemconfigure(self._overlay["message"], text=state.error)
            self.itemconfigure(
                self._overlay["hint"],
                text="Check pygame and permissions",
            )
        else:
            self.itemconfigure(self._overlay["title"], text="NO CONTROLLER")
            self.itemconfigure(
                self._overlay["message"],
                text="Connect via USB or Bluetooth",
            )
            self.itemconfigure(self._overlay["hint"], text="Auto-detect is on")
