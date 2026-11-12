# TurboPad

A cross-platform desktop **rapid-fire macro spammer** for a connected DualShock 4.
TurboPad reads the controller live, lights up a full PS4 input map, and taps a
keyboard key or mouse button while you hold (or toggle) an activation control.

Built with **Python + Tkinter**, **pygame/SDL2** for controller input,
**pynput** for keyboard/mouse output, and **Pillow** for the controller
artwork.

![TurboPad screenshot](docs/screenshot.png)

*Preview with simulated controller input.*

```
┌─────────────────────────────────────────────────────────────────────┐
│  TP  TURBOPAD                         ● DualShock 4     F8 PANIC   │
│      DUALSHOCK 4 MACRO SPAMMER                                      │
├───────────────────────────────────────────────┬─────────────────────┤
│  INPUT TESTING MAP                            │  MACRO ENGINE       │
│                                               │  READY      0       │
│            ╭─────────────────╮                │  PRESSES            │
│        L2  │   TOUCHPAD      │  R2            ├─────────────────────┤
│      L1    │  ◁   △   ▷      │    R1          │  OUTPUT TARGET      │
│            │  □   ✕   ○      │                │  [ Space        ]   │
│               ◉       ◉                       │  ACTIVATION         │
│                 PS                            │  [ R2           ]   │
│                                               │  SPAM SPEED  20 Hz  │
│                                               │  ───────●────────   │
│                                               │  MODE [Hold|Toggle] │
├───────────────────────────────────────────────┼─────────────────────┤
│  LAST INPUT  Cross       Analog sticks too    │  ■ STOP TURBO       │
└───────────────────────────────────────────────┴─────────────────────┘
```

## Features

- **Automatic controller detection** over USB or Bluetooth. Hot-plugging is
  handled while the app is open.
- **Live input-testing map** styled as a front view of the DualShock 4, with
  face buttons, D-pad, L1/R1, analog L2/R2, sticks, stick clicks, Share,
  Options, and PS lit in real time.
- **Turbo output** from **1 to 60 presses per second**, with accurate per-press
  timing, a tunable **pulse width** (10–80 ms), and automatic key release.
- **Target selector** for keyboard keys and mouse buttons, plus a
  **Capture** button for any key not in the list.
- **Activation selector** for every PS4 control, including analog triggers
  L2/R2. Trigger edges are debounced with hysteresis so latched toggle mode
  cannot flicker on/off.
- **Hold or Toggle** activation mode.
- **Panic stop** with the on-screen button, **F8**, or the controller combo
  **L1 + R1 + Options** (works even while a fullscreen game owns the keyboard).
- Safety behaviour: a controller disconnect, Bluetooth drop, or macro error
  stops the turbo and releases the simulated input immediately. A small
  detached guard process sends a final key-up even if TurboPad is killed.
- No console, game, or controller-specific driver required; it works alongside
  normal controller input.

## Quick start

Requirements: **Python 3.10+**. Tkinter is included with most Python installs
(on Debian/Ubuntu install `python3-tk` if needed).

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Or use the included launcher:

```bash
./run.sh                            # Linux / macOS
run.bat                             # Windows
```

## Using TurboPad

1. Connect the DualShock 4 by USB or pair it over Bluetooth. The status pill in
   the top-right turns green and shows the controller name.
2. Press buttons and move the sticks. The map lights up so you can verify every
   input before configuring the macro.
3. Pick the **output target** to spam (default: `Space`). Use `Capture` to bind
   any keyboard key.
4. Pick the **activation button** (default: `R2`).
5. Set **spam speed** between 1 and 60 Hz. 30 Hz and above is the turbo range.
   For games that sample input once per frame, 20–30 Hz is usually the most
   reliable; higher rates can be useful for event-driven games and macros.
6. Pick a **pulse width**. This is how long each simulated press is held.
   The default is 30 ms. Older or frame-locked games (for example *Ys Origin*)
   may miss very short taps: lower the speed to 10–20 Hz and raise the pulse
   width to 50–80 ms. The line under the slider shows the press/cycle timing
   that will actually be used.
7. Choose **Hold** (fire only while held) or **Toggle** (tap once to start, tap
   again to stop).
8. Press F8, **STOP TURBO**, or hold **L1 + R1 + Options** at any time to stop
   immediately. The controller combo is the reliable killswitch when a game is
   fullscreen and has grabbed the keyboard.

> The target is a keyboard/mouse action. Games that are configured to use the
> corresponding key or mouse button will receive the rapid presses. TurboPad
> intentionally does not install a virtual gamepad driver, which keeps it
> dependency-free and equally usable on Windows, macOS, and Linux.

## Platform notes

### Windows
Works directly. If a game runs as administrator, run TurboPad as administrator
too so simulated input is accepted. Some games ignore synthetic input in
exclusive fullscreen; borderless/windowed mode is usually more reliable.

### macOS
Grant **Accessibility** (and **Input Monitoring**, if prompted) to the terminal
or Python application in *System Settings → Privacy & Security*. Global F8
handling also depends on these permissions.

### Linux
If the controller is visible to the OS but not to TurboPad, make sure your user
can read input devices:

```bash
sudo usermod -aG input "$USER"
# log out and back in
```

The app uses SDL2 through pygame. On **Wayland**, pynput's keyboard/mouse
synthesis can be limited by the compositor; an X11 session gives the broadest
compatibility. Controller input itself is read through SDL and normally works
on both.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "No controller detected" | Reconnect by USB, check `ls /dev/input/js*` on Linux, and verify the user is in the `input` group. |
| Controller shows as a generic gamepad | That is fine — SDL's semantic game-controller mapping is used when available, with a DualShock 4 fallback. |
| Output never reaches a game | Try windowed/borderless mode, run both apps with the same privileges, and check macOS Accessibility permissions. |
| F8 only works while the window is focused | The global hotkey listener could not start (common on Wayland or without macOS permissions). Hold **L1 + R1 + Options** on the controller; that killswitch does not need keyboard focus. |
| Older game ignores the rapid presses | Lower the spam speed to 10–20 Hz and raise **pulse width** to 50–80 ms so each press spans at least one game frame. Keep the game window focused and try borderless/windowed mode. |
| Turbo keeps firing after the controller drops | It should stop automatically within about half a second: the app watches SDL removal events, `/dev/input` device nodes, read failures, and Bluetooth/USB drops. Press F8 or hold **L1 + R1 + Options** if a broken driver still reports stale input. |
| Direction keeps scrolling after the game loses the controller | Fixed by the disconnect watchdog plus the detached release guard: even a hard kill of TurboPad now sends a final key-up. If an older build left a key down, tap the key once manually. |

## Performance

The turbo worker sleeps on an event while inactive, so it uses no measurable CPU
between activations. The UI polls the controller at 50 Hz while input changes,
drops to 25 Hz when a pad is connected but idle, and backs off to about 7 Hz
when disconnected and 3 Hz when minimised. Widgets and the input map are only
redrawn when their values actually change.

## Linux AppImage

The `packaging/` folder contains a reproducible AppImage build:

```bash
./packaging/build_appimage.sh
```

It creates a build virtualenv, freezes the app with PyInstaller (including the
controller artwork), assembles an AppDir, and wraps it with `appimagetool`. The
result is `TurboPad-x86_64.AppImage` in this folder; pass a path as the first
argument to write it somewhere else. A prebuilt AppImage is included.

The AppImage bundles Python, Tk, pygame, Pillow, and pynput, so the target
machine does not need those installed. It requires glibc 2.38 or newer (for
example Ubuntu 24.04+, Debian 13+, or Fedora 39+) and FUSE 2; on systems
without FUSE run it with `--appimage-extract-and-run`.

## Windows executable

`TurboPad.exe` in this folder is a one-file PyInstaller build for 64-bit
Windows 10/11. It bundles Python and all dependencies; no installer is needed.
To build it yourself on Windows:

```bat
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name TurboPad ^
  --add-data "assets;assets" --hidden-import PIL._tkinter_finder ^
  --collect-submodules pynput --collect-submodules pygame run.py
```

## Project layout

```
run.py                     Application entry point
ps4_macro/
  ui.py                    Window, settings, live event loop
  pad_view.py              DualShock 4 input map and live highlights
  controller.py            pygame/SDL controller polling + normalised state
  spammer.py               Turbo timing thread and hold/toggle state machine
  output.py                pynput keyboard/mouse output
  guard.py                 Detached process that releases keys after a crash
  targets.py               Target catalogue and key capture
  widgets.py               Custom slider, segmented control, cards
  theme.py                 Colours and visual tokens
assets/
  ds4_front.png            Dark-theme controller artwork used by the map
  ds4_reference.svg        Original vector source (CC BY 3.0)
  NOTICE.txt               Artwork attribution
tools/build_pad_asset.py   Rebuilds ds4_front.png from the SVG
packaging/                 AppImage + icon build helpers
tests/test_core.py         Spammer, target, and mapping tests
tests/test_controller.py   Normalised controller-state tests
tests/test_assets.py       Bundled artwork and attribution guards
docs/screenshot.png        UI preview
TurboPad-x86_64.AppImage   Prebuilt Linux AppImage
TurboPad.exe               Prebuilt Windows executable
```

## Credits

The controller artwork is derived from
[Dualshock 4 Layout.svg](https://commons.wikimedia.org/wiki/File:Dualshock_4_Layout.svg)
by **Tokyoship**, licensed under
[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). The vector was
recoloured for TurboPad's dark theme and rasterised; the original source and
full attribution are kept in `assets/`. To rebuild the artwork:

```bash
pip install cairosvg
python tools/build_pad_asset.py
```

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests cover target capture, SDL mapping, hold/toggle behaviour, panic
latching, rate clamping, output release, and the bundled artwork.
