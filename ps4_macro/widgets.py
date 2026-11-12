"""Small, dependency-free Tk widgets used by the dashboard."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence

from . import theme


class Card(tk.Frame):
    """A flat card with a subtle one-pixel border and inner padding."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        padding: int = 14,
        background: str = theme.CARD,
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            bg=background,
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.BORDER,
            **kwargs,
        )
        self.background = background
        self.body = tk.Frame(self, bg=background, bd=0, highlightthickness=0)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)


class LevelSlider(tk.Canvas):
    """A compact, custom-drawn integer slider."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        minimum: int,
        maximum: int,
        value: int,
        command: Callable[[int], None],
        background: str = theme.CARD,
        accent: str = theme.ACCENT,
        height: int = 42,
    ) -> None:
        super().__init__(
            parent,
            bg=background,
            height=height,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self._minimum = minimum
        self._maximum = maximum
        self._value = max(minimum, min(maximum, int(value)))
        self._command = command
        self._accent = accent
        self._background = background
        self._dragging = False

        self.bind("<Configure>", self._on_configure)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Button-4>", lambda _event: self._nudge(1))
        self.bind("<Button-5>", lambda _event: self._nudge(-1))
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Enter>", lambda _event: self._redraw(hover=True))
        self.bind("<Leave>", lambda _event: self._redraw(hover=False))

    @property
    def value(self) -> int:
        return self._value

    def set(self, value: int, notify: bool = False) -> None:
        value = max(self._minimum, min(self._maximum, int(value)))
        changed = value != self._value
        self._value = value
        if changed or notify:
            self._redraw()
        if changed and notify:
            self._command(value)

    def _on_configure(self, _event: tk.Event) -> None:
        self._redraw()

    def _position_to_value(self, x: int) -> int:
        left = 13
        right = max(left + 1, self.winfo_width() - 13)
        fraction = (x - left) / max(1, right - left)
        fraction = max(0.0, min(1.0, fraction))
        return round(self._minimum + fraction * (self._maximum - self._minimum))

    def _apply_x(self, x: int) -> None:
        value = self._position_to_value(x)
        if value == self._value:
            return
        self._value = value
        self._redraw()
        self._command(value)

    def _on_press(self, event: tk.Event) -> None:
        self._dragging = True
        self._apply_x(event.x)

    def _on_drag(self, event: tk.Event) -> None:
        if self._dragging:
            self._apply_x(event.x)

    def _on_release(self, _event: tk.Event) -> None:
        self._dragging = False

    def _on_wheel(self, event: tk.Event) -> None:
        self._nudge(1 if event.delta > 0 else -1)

    def _nudge(self, amount: int) -> None:
        value = max(self._minimum, min(self._maximum, self._value + amount))
        if value != self._value:
            self._value = value
            self._redraw()
            self._command(value)

    def _redraw(self, hover: bool = False) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        y = self.winfo_height() / 2
        left = 13
        right = max(left + 1, width - 13)
        span = right - left
        fraction = (self._value - self._minimum) / max(1, self._maximum - self._minimum)
        thumb_x = left + span * fraction
        track_color = theme.TRACK
        fill_color = self._accent

        # Tick marks give the range a mechanical feel without adding clutter.
        for index in range(1, 6):
            tick_x = left + span * index / 6
            self.create_line(
                tick_x,
                y + 10,
                tick_x,
                y + 13,
                fill=theme.BORDER,
                width=1,
            )

        self.create_line(left, y, right, y, fill=track_color, width=7, capstyle=tk.ROUND)
        if thumb_x > left + 1:
            self.create_line(left, y, thumb_x, y, fill=fill_color, width=7, capstyle=tk.ROUND)

        outer = theme.TEXT if hover or self._dragging else theme.BG
        self.create_oval(
            thumb_x - 9,
            y - 9,
            thumb_x + 9,
            y + 9,
            fill=fill_color,
            outline=outer,
            width=3,
        )
        self.create_oval(
            thumb_x - 3,
            y - 3,
            thumb_x + 3,
            y + 3,
            fill=theme.BG,
            outline="",
        )


class SegmentedControl(tk.Frame):
    """A two-or-more-option flat segmented selector."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        options: Sequence[tuple[str, str]],
        value: str,
        command: Callable[[str], None],
        font: tuple,
        background: str = theme.CARD,
    ) -> None:
        super().__init__(
            parent,
            bg=theme.BORDER_SOFT,
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
        )
        self._segment_options = list(options)
        self._value = value
        self._command = command
        self._font = font
        self._buttons: dict[str, tk.Button] = {}

        for column, (label, option_value) in enumerate(self._segment_options):
            self.grid_columnconfigure(column, weight=1)
            button = tk.Button(
                self,
                text=label,
                command=lambda selected=option_value: self._select(selected),
                font=font,
                bd=0,
                relief="flat",
                overrelief="flat",
                highlightthickness=0,
                cursor="hand2",
                padx=10,
                pady=7,
            )
            button.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 1, 0))
            self._buttons[option_value] = button

        self._refresh()

    @property
    def value(self) -> str:
        return self._value

    def set(self, value: str, notify: bool = False) -> None:
        if value not in self._buttons:
            return
        changed = value != self._value
        self._value = value
        self._refresh()
        if changed and notify:
            self._command(value)

    def _select(self, value: str) -> None:
        if value == self._value:
            return
        self._value = value
        self._refresh()
        self._command(value)

    def _refresh(self) -> None:
        for option_value, button in self._buttons.items():
            selected = option_value == self._value
            button.configure(
                bg=theme.ACCENT if selected else theme.INPUT,
                fg=theme.BG if selected else theme.TEXT_SOFT,
                activebackground=theme.ACCENT_HOVER if selected else theme.CARD_ALT,
                activeforeground=theme.BG if selected else theme.TEXT,
            )


def flat_button(
    parent: tk.Misc,
    *,
    text: str,
    command: Callable[[], None],
    font: tuple,
    background: str = theme.CARD_ALT,
    foreground: str = theme.TEXT,
    active_background: str = theme.BORDER,
    active_foreground: str = theme.TEXT,
    padx: int = 12,
    pady: int = 7,
    cursor: str = "hand2",
) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=command,
        font=font,
        bg=background,
        fg=foreground,
        activebackground=active_background,
        activeforeground=active_foreground,
        bd=0,
        relief="flat",
        overrelief="flat",
        highlightthickness=0,
        padx=padx,
        pady=pady,
        cursor=cursor,
    )
