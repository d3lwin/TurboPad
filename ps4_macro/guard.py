"""A tiny detached process that releases keys if TurboPad dies.

The main process streams every target it has pressed into this guard through
stdin. If the main process crashes, is killed, or the desktop session tears it
down, the pipe reaches EOF and the guard sends a final key-up for everything it
saw. This is what prevents a game from being left with a direction held down
(and scrolling forever) after a hard exit.
"""

from __future__ import annotations

import sys

from .output import OutputDriver
from .targets import TargetAction

_RELEASES = 3


def run_guardian() -> int:
    driver = OutputDriver(start_guardian=False)
    if not driver.available:
        return 1

    seen: dict[tuple[str, str], TargetAction] = {}
    normal_exit = False
    try:
        for line in sys.stdin:
            parts = line.strip().split("|", 2)
            if len(parts) != 3 or parts[0] != "P":
                if line.strip() == "Q":
                    normal_exit = True
                    break
                continue
            kind, value = parts[1], parts[2]
            if kind not in ("key", "mouse") or not value:
                continue
            seen[(kind, value)] = TargetAction(key=value, label=value, kind=kind, value=value)
    except Exception:
        pass
    finally:
        if not normal_exit:
            try:
                driver.release_targets(seen.values(), repeats=_RELEASES)
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(run_guardian())
