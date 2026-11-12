"""Launch TurboPad."""

from __future__ import annotations

import sys


def main() -> int:
    if "--release-guard" in sys.argv:
        from ps4_macro.guard import run_guardian

        return run_guardian()
    try:
        from ps4_macro.ui import MacroApp
    except Exception as exc:  # pragma: no cover - startup diagnostics
        print(f"TurboPad could not start: {exc}", file=sys.stderr)
        return 1

    app = MacroApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        app._on_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
