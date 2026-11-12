"""TurboPad's main window and application logic."""

from __future__ import annotations

import atexit
import signal
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from . import theme
from .controller import (
    ACTIVATION_CONTROLS,
    CONTROL_LABELS,
    ControllerManager,
    PadState,
)
from .output import OutputDriver
from .pad_view import PadCanvas
from .spammer import DEFAULT_PULSE_MS, MAX_RATE, MIN_RATE, TurboSpammer
from .targets import (
    BUILTIN_TARGETS,
    DEFAULT_TARGET,
    TargetAction,
    target_from_capture,
)
from .widgets import Card, LevelSlider, SegmentedControl, flat_button

try:
    from pynput.keyboard import GlobalHotKeys
except Exception:
    GlobalHotKeys = None  # type: ignore[assignment]


class FontBook:
    def __init__(self, root: tk.Misc) -> None:
        available = {name.lower(): name for name in tkfont.families(root)}
        self.family = self._pick(
            available,
            (
                "inter",
                "segoe ui",
                "sf pro text",
                "helvetica neue",
                "roboto",
                "noto sans",
                "dejavu sans",
                "arial",
            ),
        )
        self.mono = self._pick(
            available,
            (
                "jetbrains mono",
                "cascadia code",
                "sf mono",
                "menlo",
                "consolas",
                "roboto mono",
                "fira code",
                "dejavu sans mono",
                "courier new",
            ),
        )
        self.display = tkfont.Font(root, family=self.family, size=21, weight="bold")
        self.title = tkfont.Font(root, family=self.family, size=15, weight="bold")
        self.state = tkfont.Font(root, family=self.family, size=16, weight="bold")
        self.h2 = tkfont.Font(root, family=self.family, size=11, weight="bold")
        self.body = tkfont.Font(root, family=self.family, size=10)
        self.body_bold = tkfont.Font(root, family=self.family, size=10, weight="bold")
        self.small = tkfont.Font(root, family=self.family, size=9)
        self.small_bold = tkfont.Font(root, family=self.family, size=9, weight="bold")
        self.tiny = tkfont.Font(root, family=self.family, size=8)
        self.tiny_bold = tkfont.Font(root, family=self.family, size=8, weight="bold")
        self.micro = tkfont.Font(root, family=self.family, size=7)
        self.micro_bold = tkfont.Font(root, family=self.family, size=7, weight="bold")
        self.mono_small = tkfont.Font(root, family=self.mono, size=8)

    @staticmethod
    def _pick(available: dict[str, str], candidates: tuple[str, ...]) -> str:
        for candidate in candidates:
            if candidate in available:
                return available[candidate]
        return tkfont.nametofont("TkDefaultFont").actual("family")


class MacroApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TurboPad - DualShock 4 Macro Spammer")
        self.geometry("1200x700")
        self.minsize(1100, 660)
        self.configure(bg=theme.BG)
        self.option_add("*tearOff", False)

        self.fonts = FontBook(self)
        self._configure_styles()

        self.output = OutputDriver()
        self.target: TargetAction = DEFAULT_TARGET
        self.activation_id = "r2"
        self.rate = 20
        self.pulse_ms = DEFAULT_PULSE_MS
        self.mode = "hold"
        self.targets: list[TargetAction] = list(BUILTIN_TARGETS)
        self._activation_down = False
        self._pad_was_connected = False
        self._last_pad_change = 0.0
        self._previous_active: set[str] = set()
        self._last_input_at = 0.0
        self._last_connection: tuple[bool, str, str] | None = None
        self._last_engine_text = ""
        self._last_engine_color = ""
        self._last_dot_color = ""
        self._last_badge_text = ""
        self._last_detail = ""
        self._last_detail_color = ""
        self._last_count_text = ""
        self._last_input_text = ""
        self._last_input_color = ""
        self._last_footer = ""
        self._last_footer_color = ""
        self._toast_until = 0.0
        self._toast_text = ""
        self._toast_color = theme.MUTED
        self._panic_request = threading.Event()
        self._capturing = False
        self._closing = False
        self._hotkey_listener = None
        self._hotkey_ready = False
        self._tick_after: str | None = None
        self._combo_since: float | None = None
        self._combo_fired = False

        self.spammer = TurboSpammer(
            self.output,
            target=self.target,
            rate=self.rate,
            mode=self.mode,  # type: ignore[arg-type]
            pulse_ms=self.pulse_ms,
            watchdog=1.5,
        )
        self.controller = ControllerManager(on_lost=self._on_controller_lost)
        self.spammer.start()

        atexit.register(self._release_on_exit)
        self._install_signal_handlers()

        self._build_ui()
        self._bind_events()
        self._install_hotkey()
        self._update_mode_hint()
        self._update_rate_labels()
        self._refresh_target_combo()
        self._sync_engine(force=True)
        self._tick_after = self.after(16, self._tick)

    # ------------------------------------------------------------------- styling
    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Turbo.TCombobox",
            fieldbackground=theme.INPUT,
            background=theme.INPUT,
            foreground=theme.TEXT,
            arrowcolor=theme.MUTED,
            bordercolor=theme.BORDER,
            lightcolor=theme.BORDER,
            darkcolor=theme.BORDER,
            insertcolor=theme.TEXT,
            padding=7,
            relief="flat",
        )
        style.map(
            "Turbo.TCombobox",
            fieldbackground=[("readonly", theme.INPUT), ("disabled", theme.CARD_ALT)],
            foreground=[("readonly", theme.TEXT), ("disabled", theme.DIM)],
            background=[("readonly", theme.INPUT), ("active", theme.CARD_ALT)],
            selectbackground=[("readonly", theme.INPUT)],
            selectforeground=[("readonly", theme.TEXT)],
            bordercolor=[("focus", theme.ACCENT), ("!focus", theme.BORDER)],
            arrowcolor=[("active", theme.ACCENT), ("!active", theme.MUTED)],
        )
        self.option_add("*TCombobox*Listbox.background", theme.INPUT)
        self.option_add("*TCombobox*Listbox.foreground", theme.TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", theme.ACCENT_DARK)
        self.option_add("*TCombobox*Listbox.selectForeground", theme.ACCENT)
        self.option_add("*TCombobox*Listbox.borderWidth", 0)
        self.option_add("*TCombobox*Listbox.font", self.fonts.body)

    # ------------------------------------------------------------------ UI build
    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=theme.BG)
        header.pack(fill="x", padx=20, pady=(14, 8))
        self._build_header(header)

        main = tk.Frame(self, bg=theme.BG)
        main.pack(fill="both", expand=True, padx=16, pady=(0, 6))
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=0, minsize=366)

        self._build_dashboard(main).grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        right = tk.Frame(main, bg=theme.BG)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_side_panel(right)

        footer = tk.Frame(self, bg=theme.BG)
        footer.pack(fill="x", padx=20, pady=(0, 9))
        self._build_footer(footer)

    def _build_header(self, parent: tk.Frame) -> None:
        logo = tk.Canvas(parent, width=44, height=44, bg=theme.BG, highlightthickness=0)
        logo.pack(side="left", padx=(0, 12))
        self._rounded_canvas_rect(logo, 1, 1, 43, 43, 11, fill=theme.ACCENT, outline="")
        logo.create_text(
            22,
            22,
            text="TP",
            fill=theme.BG,
            font=(self.fonts.family, 14, "bold"),
        )

        brand = tk.Frame(parent, bg=theme.BG)
        brand.pack(side="left")
        tk.Label(
            brand,
            text="TURBOPAD",
            bg=theme.BG,
            fg=theme.TEXT,
            font=self.fonts.display,
        ).pack(anchor="w")
        tk.Label(
            brand,
            text="DUALSHOCK 4 MACRO SPAMMER",
            bg=theme.BG,
            fg=theme.MUTED,
            font=self.fonts.micro_bold,
        ).pack(anchor="w", pady=(1, 0))

        right = tk.Frame(parent, bg=theme.BG)
        right.pack(side="right")

        panic = tk.Frame(
            right,
            bg=theme.AMBER_DARK,
            highlightthickness=1,
            highlightbackground="#5d451c",
        )
        panic.pack(side="right", padx=(10, 0))
        tk.Label(
            panic,
            text="F8",
            bg=theme.AMBER,
            fg=theme.BG,
            font=self.fonts.tiny_bold,
            padx=7,
            pady=4,
        ).pack(side="left", padx=4, pady=4)
        tk.Label(
            panic,
            text="PANIC STOP",
            bg=theme.AMBER_DARK,
            fg=theme.AMBER,
            font=self.fonts.tiny_bold,
            padx=6,
        ).pack(side="left", padx=(0, 4))

        connection = tk.Frame(
            right,
            bg=theme.CARD,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
        )
        connection.pack(side="right")
        status_holder = tk.Frame(connection, bg=theme.CARD)
        status_holder.pack(side="left", padx=(10, 7), pady=8)
        self.connection_dot = tk.Canvas(
            status_holder,
            width=12,
            height=12,
            bg=theme.CARD,
            highlightthickness=0,
        )
        self.connection_dot.pack(side="left", padx=(0, 7))
        self.connection_dot_item = self.connection_dot.create_oval(
            2,
            2,
            10,
            10,
            fill=theme.AMBER,
            outline="",
        )
        text_holder = tk.Frame(connection, bg=theme.CARD)
        text_holder.pack(side="left", padx=(0, 12), pady=(5, 5))
        self.connection_name = tk.Label(
            text_holder,
            text="Searching for controller...",
            bg=theme.CARD,
            fg=theme.TEXT,
            font=self.fonts.small_bold,
            anchor="w",
        )
        self.connection_name.pack(anchor="w")
        self.connection_detail = tk.Label(
            text_holder,
            text="USB or Bluetooth",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.fonts.micro,
            anchor="w",
        )
        self.connection_detail.pack(anchor="w")

    def _build_dashboard(self, parent: tk.Misc) -> Card:
        card = Card(parent, padding=0)
        header = tk.Frame(card.body, bg=theme.CARD)
        header.pack(fill="x", padx=16, pady=(12, 0))

        titles = tk.Frame(header, bg=theme.CARD)
        titles.pack(side="left")
        tk.Label(
            titles,
            text="INPUT TESTING MAP",
            bg=theme.CARD,
            fg=theme.TEXT_SOFT,
            font=self.fonts.small_bold,
        ).pack(anchor="w")
        tk.Label(
            titles,
            text="Press any button or move a stick to test live input",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.fonts.tiny,
        ).pack(anchor="w", pady=(1, 0))

        live = tk.Frame(header, bg=theme.ACCENT_DARK)
        live.pack(side="right")
        live_dot = tk.Canvas(live, width=10, height=10, bg=theme.ACCENT_DARK, highlightthickness=0)
        live_dot.pack(side="left", padx=(8, 4), pady=6)
        live_dot.create_oval(2, 2, 8, 8, fill=theme.ACCENT, outline="")
        tk.Label(
            live,
            text="LIVE",
            bg=theme.ACCENT_DARK,
            fg=theme.ACCENT,
            font=self.fonts.micro_bold,
            padx=0,
        ).pack(side="left", padx=(0, 8))

        self.pad_view = PadCanvas(card.body, font_family=self.fonts.family)
        self.pad_view.pack(fill="both", expand=True, padx=6, pady=(0, 0))

        footer = tk.Frame(card.body, bg=theme.CARD)
        footer.pack(fill="x", padx=16, pady=(4, 11))
        tk.Label(
            footer,
            text="LAST INPUT",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.fonts.micro_bold,
        ).pack(side="left")
        self.last_input_label = tk.Label(
            footer,
            text="\u2014",
            bg=theme.CARD,
            fg=theme.TEXT_SOFT,
            font=self.fonts.small_bold,
        )
        self.last_input_label.pack(side="left", padx=(8, 0))
        tk.Label(
            footer,
            text="Analog sticks light up too",
            bg=theme.CARD,
            fg=theme.DIM,
            font=self.fonts.micro,
        ).pack(side="right")
        return card

    def _build_side_panel(self, parent: tk.Frame) -> None:
        self.status_card = Card(parent, padding=11)
        self.status_card.pack(fill="x")
        self._build_status_card(self.status_card.body)

        self.settings_card = Card(parent, padding=9)
        self.settings_card.pack(fill="x", pady=8)
        self._build_settings_card(self.settings_card.body)

        self.safety_card = Card(parent, padding=10)
        self.safety_card.pack(fill="x", side="bottom")
        self._build_safety_card(self.safety_card.body)

    def _build_status_card(self, parent: tk.Frame) -> None:
        top = tk.Frame(parent, bg=theme.CARD)
        top.pack(fill="x")
        tk.Label(
            top,
            text="MACRO ENGINE",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.fonts.micro_bold,
        ).pack(side="left")
        self.output_badge = tk.Label(
            top,
            text="OUTPUT READY",
            bg=theme.CARD,
            fg=theme.ACCENT,
            font=self.fonts.micro_bold,
        )
        self.output_badge.pack(side="right")

        row = tk.Frame(parent, bg=theme.CARD)
        row.pack(fill="x", pady=(5, 0))
        self.state_dot = tk.Canvas(
            row,
            width=16,
            height=16,
            bg=theme.CARD,
            highlightthickness=0,
        )
        self.state_dot.pack(side="left", padx=(0, 7), pady=(2, 0))
        self.state_dot_item = self.state_dot.create_oval(
            3,
            3,
            13,
            13,
            fill=theme.ACCENT,
            outline="",
        )
        self.state_label = tk.Label(
            row,
            text="READY",
            bg=theme.CARD,
            fg=theme.ACCENT,
            font=self.fonts.state,
        )
        self.state_label.pack(side="left")

        counter = tk.Frame(row, bg=theme.CARD)
        counter.pack(side="right")
        self.count_label = tk.Label(
            counter,
            text="0",
            bg=theme.CARD,
            fg=theme.TEXT,
            font=self.fonts.title,
        )
        self.count_label.pack(anchor="e")
        tk.Label(
            counter,
            text="PRESSES",
            bg=theme.CARD,
            fg=theme.DIM,
            font=self.fonts.micro_bold,
        ).pack(anchor="e")

        self.engine_detail = tk.Label(
            parent,
            text="Hold R2 to fire \u00b7 Space",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.fonts.tiny,
            anchor="w",
            justify="left",
            wraplength=310,
        )
        self.engine_detail.pack(fill="x", pady=(3, 0))

    def _build_settings_card(self, parent: tk.Frame) -> None:
        self._field_label(parent, "OUTPUT TARGET", "Simulated key or mouse button")
        target_row = tk.Frame(parent, bg=theme.CARD)
        target_row.pack(fill="x", pady=(3, 0))
        target_row.grid_columnconfigure(0, weight=1)

        self.target_var = tk.StringVar(value=self.target.label)
        self.target_combo = ttk.Combobox(
            target_row,
            textvariable=self.target_var,
            style="Turbo.TCombobox",
            state="readonly",
            values=[target.label for target in self.targets],
            font=self.fonts.body,
            height=16,
        )
        self.target_combo.grid(row=0, column=0, sticky="ew")
        self.target_combo.bind("<<ComboboxSelected>>", self._on_target_selected)
        self.capture_button = flat_button(
            target_row,
            text="Capture",
            command=self._toggle_capture,
            font=self.fonts.tiny_bold,
            background=theme.INPUT,
            foreground=theme.TEXT_SOFT,
            active_background=theme.CARD_ALT,
            padx=9,
            pady=8,
        )
        self.capture_button.grid(row=0, column=1, padx=(7, 0), sticky="ns")
        self.test_button = flat_button(
            target_row,
            text="Test",
            command=self._test_target,
            font=self.fonts.tiny_bold,
            background=theme.INPUT,
            foreground=theme.TEXT_SOFT,
            active_background=theme.CARD_ALT,
            padx=9,
            pady=8,
        )
        self.test_button.grid(row=0, column=2, padx=(5, 0), sticky="ns")

        self._field_label(parent, "ACTIVATION BUTTON", "Hold or tap this controller control", top=9)
        self.activation_var = tk.StringVar(value=CONTROL_LABELS[self.activation_id])
        self.activation_combo = ttk.Combobox(
            parent,
            textvariable=self.activation_var,
            style="Turbo.TCombobox",
            state="readonly",
            values=[CONTROL_LABELS[control] for control in ACTIVATION_CONTROLS],
            font=self.fonts.body,
            height=12,
        )
        self.activation_combo.pack(fill="x", pady=(3, 0))
        self.activation_combo.bind("<<ComboboxSelected>>", self._on_activation_selected)

        speed_head = tk.Frame(parent, bg=theme.CARD)
        speed_head.pack(fill="x", pady=(9, 0))
        tk.Label(
            speed_head,
            text="SPAM SPEED",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.fonts.micro_bold,
        ).pack(side="left")
        self.rate_label = tk.Label(
            speed_head,
            text="20 Hz",
            bg=theme.CARD,
            fg=theme.ACCENT,
            font=self.fonts.h2,
        )
        self.rate_label.pack(side="right")

        self.rate_slider = LevelSlider(
            parent,
            minimum=MIN_RATE,
            maximum=MAX_RATE,
            value=self.rate,
            command=self._on_rate_changed,
            background=theme.CARD,
            accent=theme.ACCENT,
        )
        self.rate_slider.pack(fill="x", pady=(0, 0))
        scale_labels = tk.Frame(parent, bg=theme.CARD)
        scale_labels.pack(fill="x")
        tk.Label(
            scale_labels,
            text="1 Hz",
            bg=theme.CARD,
            fg=theme.DIM,
            font=self.fonts.micro,
        ).pack(side="left", padx=(11, 0))
        self.interval_label = tk.Label(
            scale_labels,
            text="50 ms / press",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.fonts.micro,
        )
        self.interval_label.pack(side="left", expand=True)
        tk.Label(
            scale_labels,
            text="60 Hz",
            bg=theme.CARD,
            fg=theme.DIM,
            font=self.fonts.micro,
        ).pack(side="right", padx=(0, 8))

        self.preset_buttons: dict[int, tk.Button] = {}
        preset_row = tk.Frame(parent, bg=theme.CARD)
        preset_row.pack(fill="x", pady=(4, 0))
        for column, preset in enumerate((5, 10, 20, 30, 45, 60)):
            preset_row.grid_columnconfigure(column, weight=1)
            button = flat_button(
                preset_row,
                text=str(preset),
                command=lambda value=preset: self._apply_rate_preset(value),
                font=self.fonts.micro_bold,
                background=theme.INPUT,
                foreground=theme.MUTED,
                active_background=theme.ACCENT_DARK,
                active_foreground=theme.ACCENT,
                padx=2,
                pady=3,
            )
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 2, 0))
            self.preset_buttons[preset] = button

        pulse_row = tk.Frame(parent, bg=theme.CARD)
        pulse_row.pack(fill="x", pady=(5, 0))
        tk.Label(
            pulse_row,
            text="PULSE WIDTH",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.fonts.micro_bold,
        ).pack(side="left")
        self.pulse_buttons: dict[int, tk.Button] = {}
        for value in reversed((10, 20, 30, 50, 80)):
            button = flat_button(
                pulse_row,
                text=f"{value}",
                command=lambda pulse=value: self._apply_pulse(pulse),
                font=self.fonts.micro_bold,
                background=theme.INPUT,
                foreground=theme.MUTED,
                active_background=theme.ACCENT_DARK,
                active_foreground=theme.ACCENT,
                padx=6,
                pady=2,
            )
            button.pack(side="right", padx=(2, 0))
            self.pulse_buttons[value] = button

        mode_row = tk.Frame(parent, bg=theme.CARD)
        mode_row.pack(fill="x", pady=(8, 0))
        tk.Label(
            mode_row,
            text="ACTIVATION MODE",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.fonts.micro_bold,
        ).pack(side="left")
        self.mode_control = SegmentedControl(
            parent,
            options=(("Hold", "hold"), ("Toggle", "toggle")),
            value=self.mode,
            command=self._on_mode_changed,
            font=self.fonts.tiny_bold,
            background=theme.CARD,
        )
        self.mode_control.pack(fill="x", pady=(3, 0))
        self.mode_hint = tk.Label(
            parent,
            text="Hold R2 to fire",
            bg=theme.CARD,
            fg=theme.DIM,
            font=self.fonts.micro,
            anchor="w",
        )
        self.mode_hint.pack(fill="x", pady=(2, 0))

    def _build_safety_card(self, parent: tk.Frame) -> None:
        self.stop_button = flat_button(
            parent,
            text="\u25a0  STOP TURBO",
            command=self.panic_stop,
            font=self.fonts.small_bold,
            background=theme.RED_DARK,
            foreground="#ffd9df",
            active_background="#561a25",
            active_foreground="#ffffff",
            padx=12,
            pady=9,
        )
        self.stop_button.pack(fill="x")
        self.hotkey_hint = tk.Label(
            parent,
            text="F8 \u00b7 L1+R1+Options \u00b7 works in-game",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.fonts.micro,
        )
        self.hotkey_hint.pack(pady=(5, 0))

    def _build_footer(self, parent: tk.Frame) -> None:
        self.footer_message = tk.Label(
            parent,
            text="Waiting for a controller",
            bg=theme.BG,
            fg=theme.MUTED,
            font=self.fonts.tiny,
            anchor="w",
        )
        self.footer_message.pack(side="left")
        tk.Label(
            parent,
            text="INPUT  pygame    OUTPUT  pynput",
            bg=theme.BG,
            fg=theme.DIM,
            font=self.fonts.mono_small,
        ).pack(side="right")

    def _field_label(self, parent: tk.Frame, title: str, hint: str, *, top: int = 0) -> None:
        row = tk.Frame(parent, bg=theme.CARD)
        row.pack(fill="x", pady=(top, 0))
        tk.Label(
            row,
            text=title,
            bg=theme.CARD,
            fg=theme.MUTED,
            font=self.fonts.micro_bold,
        ).pack(side="left")
        tk.Label(
            row,
            text=hint,
            bg=theme.CARD,
            fg=theme.DIM,
            font=self.fonts.micro,
        ).pack(side="right")

    @staticmethod
    def _rounded_canvas_rect(
        canvas: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        radius: float,
        **kwargs,
    ) -> int:
        import math

        points: list[float] = []
        corners = (
            (x2 - radius, y1 + radius, -90, 0),
            (x2 - radius, y2 - radius, 0, 90),
            (x1 + radius, y2 - radius, 90, 180),
            (x1 + radius, y1 + radius, 180, 270),
        )
        for cx, cy, start, end in corners:
            for step in range(5):
                angle = math.radians(start + (end - start) * step / 4)
                points.extend((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        return canvas.create_polygon(points, **kwargs)

    # ------------------------------------------------------------------- events
    def _bind_events(self) -> None:
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<KeyPress>", self._on_key_press, add="+")
        self.bind_all("<F8>", self._on_f8, add="+")

    def _install_hotkey(self) -> None:
        if GlobalHotKeys is None:
            self.hotkey_hint.configure(text="F8 (focused) \u00b7 L1+R1+Options in-game")
            return
        try:
            self._hotkey_listener = GlobalHotKeys({"<f8>": self._request_panic})
            self._hotkey_listener.start()
            self._hotkey_ready = True
        except Exception:
            self._hotkey_listener = None
            self._hotkey_ready = False
            self.hotkey_hint.configure(text="F8 (focused) \u00b7 L1+R1+Options in-game")

    def _install_signal_handlers(self) -> None:
        for name in ("SIGINT", "SIGTERM", "SIGHUP"):
            signum = getattr(signal, name, None)
            if signum is None:
                continue
            try:
                signal.signal(signum, self._on_signal)
            except (ValueError, OSError):
                pass

    def _on_signal(self, _signum: int, _frame: object) -> None:
        # Release output from the signal handler itself: the Tk loop may be
        # blocked, but a stuck key must not survive Ctrl+C or a terminal close.
        self.spammer.panic()
        try:
            self.after(0, self._on_close)
        except Exception:
            pass

    def _release_on_exit(self) -> None:
        try:
            self.output.close()
        except Exception:
            pass

    def _on_controller_lost(self) -> None:
        """Called from the controller watchdog thread."""

        # This must not touch Tk. The output is released here so a hung main
        # loop cannot keep the last key pressed.
        self._activation_down = False
        self.spammer.controller_lost()

    def _request_panic(self) -> None:
        # Release on the hotkey listener's thread as well; the UI tick may be
        # stalled (or the game may hold the keyboard focus).
        self.spammer.panic()
        self._panic_request.set()

    def _on_f8(self, _event: tk.Event) -> str:
        self.panic_stop()
        return "break"

    def _on_key_press(self, event: tk.Event) -> str | None:
        if not self._capturing:
            return None
        if event.keysym == "Escape":
            self._cancel_capture()
            return "break"
        if event.keysym == "F8":
            self._toast("F8 is reserved for panic stop", theme.AMBER, 3.0)
            return "break"
        target = target_from_capture(event.keysym, event.char)
        if target is None:
            return "break"
        if target.value == "f8":
            self._toast("F8 is reserved for panic stop", theme.AMBER, 3.0)
            return "break"
        existing = next(
            (item for item in self.targets if item.kind == target.kind and item.value == target.value),
            None,
        )
        if existing is None:
            self.targets.append(target)
            existing = target
        self._finish_capture(existing)
        return "break"

    def _toggle_capture(self) -> None:
        if self._capturing:
            self._cancel_capture()
            return
        self._capturing = True
        self.capture_button.configure(
            text="Press a key...",
            fg=theme.ACCENT,
            bg=theme.ACCENT_DARK,
        )
        self.focus_force()
        self._toast("Press any keyboard key to use it as the target (Esc to cancel)", theme.MUTED, 5.0)

    def _cancel_capture(self) -> None:
        self._capturing = False
        self.capture_button.configure(
            text="Capture",
            fg=theme.TEXT_SOFT,
            bg=theme.INPUT,
        )
        self._toast("Key capture cancelled", theme.MUTED, 2.0)

    def _finish_capture(self, target: TargetAction) -> None:
        self._capturing = False
        self.capture_button.configure(
            text="Capture",
            fg=theme.TEXT_SOFT,
            bg=theme.INPUT,
        )
        self._refresh_target_combo()
        self.target = target
        self.target_var.set(target.label)
        self.spammer.set_target(target)
        self._toast(f"Output target: {target.label}", theme.ACCENT, 2.5)
        self._sync_engine(force=True)

    def _refresh_target_combo(self) -> None:
        self.target_combo.configure(values=[target.label for target in self.targets])

    def _target_from_label(self, label: str) -> TargetAction | None:
        return next((target for target in self.targets if target.label == label), None)

    def _on_target_selected(self, _event: tk.Event) -> None:
        target = self._target_from_label(self.target_var.get())
        if target is None:
            return
        self.target = target
        self.spammer.set_target(target)
        self._toast(f"Output target: {target.label}", theme.ACCENT, 2.0)
        self._sync_engine(force=True)

    def _on_activation_selected(self, _event: tk.Event) -> None:
        label = self.activation_var.get()
        control = next(
            (control for control in ACTIVATION_CONTROLS if CONTROL_LABELS[control] == label),
            None,
        )
        if control is None:
            return
        self.activation_id = control
        self._activation_down = False
        self.spammer.reset_activation()
        self._update_mode_hint()
        self._toast(f"Activation: {CONTROL_LABELS[control]}", theme.ACCENT, 2.0)
        self._sync_engine(force=True)

    def _on_rate_changed(self, value: int) -> None:
        self.rate = int(value)
        self.spammer.set_rate(self.rate)
        self._update_rate_labels()
        self._sync_engine(force=True)

    def _update_rate_labels(self) -> None:
        self.rate_label.configure(text=f"{self.rate} Hz")
        interval_ms = 1000.0 / max(1, self.rate)
        press_ms = TurboSpammer.effective_pulse_ms(self.rate, self.pulse_ms)
        self.interval_label.configure(
            text=f"{press_ms:.0f} ms press \u00b7 {interval_ms:.0f} ms cycle"
        )
        if hasattr(self, "preset_buttons"):
            for value, button in self.preset_buttons.items():
                active = value == self.rate
                button.configure(
                    bg=theme.ACCENT_DARK if active else theme.INPUT,
                    fg=theme.ACCENT if active else theme.MUTED,
                )
        if hasattr(self, "pulse_buttons"):
            for value, button in self.pulse_buttons.items():
                active = value == self.pulse_ms
                button.configure(
                    bg=theme.ACCENT_DARK if active else theme.INPUT,
                    fg=theme.ACCENT if active else theme.MUTED,
                )

    def _apply_rate_preset(self, value: int) -> None:
        self.rate = int(value)
        self.rate_slider.set(self.rate)
        self.spammer.set_rate(self.rate)
        self._update_rate_labels()
        self._sync_engine(force=True)

    def _apply_pulse(self, value: int) -> None:
        self.pulse_ms = int(value)
        self.spammer.set_pulse_ms(self.pulse_ms)
        self._update_rate_labels()
        self._sync_engine(force=True)
        self._toast(f"Pulse width: {self.pulse_ms} ms", theme.ACCENT, 2.0)

    def _test_target(self) -> None:
        if not self.output.available:
            self._toast(self.output.error or "Output device unavailable", theme.RED, 4.0)
            return
        if self.spammer.active:
            self._toast("Stop the turbo before testing the target", theme.AMBER, 2.5)
            return
        if self.target.kind == "mouse":
            self._toast(
                "Mouse tests would click the cursor location \u2014 use the target in-game",
                theme.AMBER,
                3.5,
            )
            return
        self.focus_force()
        self._test_action = self.target
        self.after(25, self._send_test_pulse)

    def _send_test_pulse(self) -> None:
        action = getattr(self, "_test_action", self.target)
        try:
            self.output.press(action)
        except Exception as exc:
            self._toast(f"Test failed: {exc}", theme.RED, 4.0)
            return
        self.after(45, lambda: self._finish_test_pulse(action))
        self._toast(f"Test pulse sent: {action.label}", theme.ACCENT, 2.0)

    def _finish_test_pulse(self, action: TargetAction) -> None:
        self.output.release(action)

    def _on_mode_changed(self, mode: str) -> None:
        self.mode = mode
        self._activation_down = False
        self.spammer.set_mode(mode)  # type: ignore[arg-type]
        self.spammer.reset_activation()
        self._update_mode_hint()
        label = "Hold" if mode == "hold" else "Toggle"
        self._toast(f"Activation mode: {label}", theme.ACCENT, 2.0)
        self._sync_engine(force=True)

    def _update_mode_hint(self) -> None:
        label = CONTROL_LABELS[self.activation_id]
        if self.mode == "hold":
            hint = f"Hold {label} to fire"
        else:
            hint = f"Tap {label} to toggle on / off"
        self.mode_hint.configure(text=hint)
        self._sync_engine(force=True)

    # --------------------------------------------------------------------- tick
    def _tick(self) -> None:
        if self._closing:
            return
        delay = 20
        self.spammer.heartbeat()
        try:
            if self._panic_request.is_set():
                self._panic_request.clear()
                self.panic_stop()

            state = self.controller.poll()
            self._handle_connection_loss(state)
            self._check_panic_combo(state)
            changed = self.pad_view.set_state(state, spam_active=self.spammer.active)
            if changed:
                self._last_pad_change = time.monotonic()
            self._update_connection(state)
            self._handle_activation(state)
            self._detect_last_input(state)
            self._sync_engine()
            self._refresh_footer(state)

            # A disconnected or idle app has nothing to animate: poll slowly to
            # keep idle CPU usage near zero, but snap back once input changes.
            if not state.connected:
                delay = 150
            elif time.monotonic() - self._last_pad_change > 0.8:
                delay = 40
            if self.state() == "iconic":
                delay = max(delay, 300)
        except Exception as exc:  # never let a driver/UI error leave keys down
            print(f"TurboPad tick error: {exc}", flush=True)
            try:
                self.spammer.controller_lost()
            except Exception:
                pass
            self._toast("Internal error \u00b7 turbo stopped", theme.RED, 4.0)
        finally:
            self.spammer.heartbeat()
            if not self._closing:
                self._tick_after = self.after(delay, self._tick)

    def _check_panic_combo(self, state: PadState) -> None:
        """Controller-only killswitch that works while the game has focus."""

        pressed = (
            state.connected
            and state.buttons.get("l1", False)
            and state.buttons.get("r1", False)
            and state.buttons.get("options", False)
        )
        if not pressed:
            self._combo_since = None
            self._combo_fired = False
            return
        now = time.monotonic()
        if self._combo_since is None:
            self._combo_since = now
            return
        if not self._combo_fired and now - self._combo_since >= 0.6:
            self._combo_fired = True
            self.spammer.panic()
            self._toast("PANIC \u00b7 L1 + R1 + Options", theme.RED, 4.0)

    def _handle_connection_loss(self, state: PadState) -> None:
        if self._pad_was_connected and not state.connected:
            self._activation_down = False
            self.spammer.controller_lost()
            self._toast("Controller disconnected \u00b7 turbo stopped", theme.AMBER, 4.0)
        self._pad_was_connected = state.connected

    def _update_connection(self, state: PadState) -> None:
        signature = (state.connected, state.name, state.error)
        if signature == self._last_connection:
            return
        self._last_connection = signature
        if state.connected:
            self.connection_dot.itemconfigure(self.connection_dot_item, fill=theme.ACCENT)
            lower_name = state.name.lower()
            if any(token in lower_name for token in ("wireless controller", "dualshock", "ps4")):
                display_name = "DualShock 4"
                detail = f"{state.name or 'Controller'} \u00b7 connected"
            else:
                display_name = state.name or "Game controller"
                detail = "Connected \u00b7 USB or Bluetooth"
            self.connection_name.configure(text=display_name, fg=theme.TEXT)
            self.connection_detail.configure(text=detail, fg=theme.MUTED)
        elif state.error:
            self.connection_dot.itemconfigure(self.connection_dot_item, fill=theme.RED)
            self.connection_name.configure(text="Controller backend error", fg=theme.RED)
            self.connection_detail.configure(text="See README for setup", fg=theme.MUTED)
        else:
            self.connection_dot.itemconfigure(self.connection_dot_item, fill=theme.AMBER)
            self.connection_name.configure(text="Searching for controller...", fg=theme.TEXT)
            self.connection_detail.configure(text="USB or Bluetooth", fg=theme.MUTED)

    def _handle_activation(self, state: PadState) -> None:
        if not state.connected:
            if self._activation_down:
                self._activation_down = False
                self.spammer.reset_activation()
            return
        pressed = state.control_pressed(self.activation_id, self._activation_down)
        if pressed == self._activation_down:
            return
        self._activation_down = pressed
        self.spammer.activation_changed(pressed)
        if self.mode == "toggle" and pressed:
            if self.spammer.active:
                self._toast("Turbo latched ON", theme.ACCENT, 2.0)
            else:
                self._toast("Turbo latched OFF", theme.MUTED, 2.0)

    def _detect_last_input(self, state: PadState) -> None:
        if not state.connected:
            self._previous_active = set()
            self._last_input_at = 0.0
            self._set_last_input("\u2014", theme.TEXT_SOFT)
            return
        active = state.active_controls(threshold=0.22)
        new_inputs = active - self._previous_active
        self._previous_active = active
        if new_inputs:
            order = (
                "cross",
                "circle",
                "square",
                "triangle",
                "l1",
                "r1",
                "l2",
                "r2",
                "dpad_up",
                "dpad_down",
                "dpad_left",
                "dpad_right",
                "share",
                "options",
                "ps",
                "l3",
                "r3",
            )
            chosen = next((name for name in order if name in new_inputs), None)
            if chosen:
                label = CONTROL_LABELS[chosen]
                if chosen in ("l2", "r2"):
                    label = f"{label}  {state.triggers.get(chosen, 0.0) * 100:.0f}%"
                self._set_last_input(label, theme.ACCENT)
                self._last_input_at = time.monotonic()
        elif self._last_input_at and time.monotonic() - self._last_input_at > 1.8:
            if self._last_input_text != "\u2014" and self._last_input_color != theme.TEXT_SOFT:
                self._set_last_input(self._last_input_text, theme.TEXT_SOFT)

    def _set_last_input(self, text: str, color: str) -> None:
        if text == self._last_input_text and color == self._last_input_color:
            return
        self._last_input_text = text
        self._last_input_color = color
        self.last_input_label.configure(text=text, fg=color)

    def _sync_engine(self, force: bool = False) -> None:
        snapshot = self.spammer.snapshot()
        if snapshot.error:
            state_text = "OUTPUT ERROR"
            state_color = theme.RED
        elif snapshot.active:
            state_text = "FIRING"
            state_color = theme.ACCENT
        else:
            state_text = "READY"
            state_color = theme.ACCENT
        if snapshot.mode == "toggle" and not snapshot.active:
            state_text = "TOGGLE OFF"

        pulse_off = snapshot.active and int(time.monotonic() * 5) % 2 == 0
        dot_color = theme.ACCENT_MID if pulse_off else state_color
        if force or dot_color != self._last_dot_color:
            self._last_dot_color = dot_color
            self.state_dot.itemconfigure(self.state_dot_item, fill=dot_color)

        if (
            force
            or state_text != self._last_engine_text
            or state_color != self._last_engine_color
        ):
            self._last_engine_text = state_text
            self._last_engine_color = state_color
            self.state_label.configure(text=state_text, fg=state_color)

        count_text = f"{snapshot.presses:,}"
        if force or count_text != self._last_count_text:
            self._last_count_text = count_text
            self.count_label.configure(text=count_text)

        activation_label = CONTROL_LABELS[self.activation_id]
        if snapshot.error:
            detail = snapshot.error
            detail_color = theme.RED
        elif snapshot.active:
            detail = f"Spamming {self.target.label} at {self.rate} Hz"
            detail_color = theme.MUTED
        elif self.mode == "hold":
            detail = f"Hold {activation_label} to fire \u00b7 {self.target.label}"
            detail_color = theme.MUTED
        else:
            detail = f"Tap {activation_label} to toggle \u00b7 {self.target.label}"
            detail_color = theme.MUTED
        if force or detail != self._last_detail or detail_color != self._last_detail_color:
            self._last_detail = detail
            self._last_detail_color = detail_color
            self.engine_detail.configure(text=detail, fg=detail_color)

        badge = "OUTPUT READY" if self.output.available else "OUTPUT OFFLINE"
        if force or badge != self._last_badge_text:
            self._last_badge_text = badge
            self.output_badge.configure(
                text=badge,
                fg=theme.ACCENT if self.output.available else theme.RED,
            )

    def _refresh_footer(self, state: PadState) -> None:
        now = time.monotonic()
        if now < self._toast_until:
            text, color = self._toast_text, self._toast_color
        elif not self.output.available:
            text, color = self.output.error or "Output device unavailable", theme.RED
        elif state.error:
            text, color = state.error, theme.RED
        elif not state.connected:
            text, color = "Waiting for controller \u00b7 connect via USB or Bluetooth", theme.AMBER
        else:
            text = "Controller connected \u00b7 configure your macro or start firing"
            color = theme.MUTED
        if text != self._last_footer or color != self._last_footer_color:
            self._last_footer = text
            self._last_footer_color = color
            self.footer_message.configure(text=text, fg=color)

    def _toast(self, text: str, color: str = theme.ACCENT, seconds: float = 3.0) -> None:
        self._toast_text = text
        self._toast_color = color
        self._toast_until = time.monotonic() + seconds
        self._last_footer = ""
        self._last_footer_color = ""

    # ------------------------------------------------------------------ actions
    def panic_stop(self) -> None:
        self.spammer.panic()
        self._toast("Turbo stopped \u00b7 release the activation button to re-arm", theme.AMBER, 4.0)
        self._sync_engine(force=True)

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._tick_after is not None:
            try:
                self.after_cancel(self._tick_after)
            except tk.TclError:
                pass
        try:
            self.spammer.shutdown()
        finally:
            if self._hotkey_listener is not None:
                try:
                    self._hotkey_listener.stop()
                except Exception:
                    pass
            self.output.close()
            self.controller.shutdown()
            self.destroy()
