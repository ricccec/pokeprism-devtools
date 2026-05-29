"""SameBoy launch helpers for start-state.

Resolves the path to the SameBoy binary so `subprocess.Popen` tracks the
actual app process — not the `open` launcher utility on macOS. The handle
matters for the dev-server TUI's Re-launch: `terminate()` can only kill
a real PID, not a launcher that already exited.

Resolution order:
  1. `$SAMEBOY_BIN` env var (absolute path to the binary)
  2. `which sameboy` / `which SameBoy` (CLI symlink, e.g. via Homebrew)
  3. macOS only: `mdfind` Spotlight lookup for SameBoy.app, then
     `Contents/MacOS/SameBoy` inside it
  4. macOS only: `open -a SameBoy <rom>` — last-ditch fallback. Launches
     successfully but the Popen handle won't track the real SameBoy PID,
     so Re-launch can't terminate the previous instance.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


def build_cmd(rom_path: Path) -> tuple[list[str] | None, bool]:
    """Return ``(cmd, trackable)``.

    ``trackable=True`` means `Popen` will hold a handle to SameBoy's real
    PID and `terminate()` works. ``trackable=False`` means SameBoy
    *will* launch but the handle is to the launcher, not the app — the
    caller should warn the user that Re-launch won't kill the prior
    instance.

    ``cmd=None`` means SameBoy isn't installed (or can't be located on
    a non-macOS host).
    """
    bin_path = _resolve_bin()
    if bin_path is not None:
        return [str(bin_path), str(rom_path)], True
    if sys.platform == "darwin":
        return ["open", "-a", "SameBoy", str(rom_path)], False
    return None, False


def _resolve_bin() -> Path | None:
    # 1. Env var override.
    env = os.environ.get("SAMEBOY_BIN")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p

    # 2. CLI install on $PATH. Try both casings — Homebrew formulas
    # tend to lowercase, hand-installed binaries often keep the
    # app-style "SameBoy".
    for name in ("sameboy", "SameBoy"):
        path = shutil.which(name)
        if path:
            return Path(path)

    # 3. macOS: locate SameBoy.app via Spotlight, then return its inner
    # binary. The inner binary is named "SameBoy" (capital).
    if sys.platform == "darwin":
        app = _spotlight_find_sameboy_app()
        if app is not None:
            return app / "Contents" / "MacOS" / "SameBoy"
    return None


def focus_after_launch() -> None:
    """Bring the just-launched SameBoy to the foreground on macOS.

    Best-effort: silent no-op on other platforms, never raises. We
    spawn SameBoy via `Popen` to keep a trackable PID, but a direct
    spawn doesn't take focus the way `open -a` does — so the terminal
    stays on top after Launch / Re-launch unless we ask AppleScript to
    activate the app.
    """
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "SameBoy" to activate'],
            capture_output=True, timeout=2, check=False,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        pass


@lru_cache(maxsize=1)
def _spotlight_find_sameboy_app() -> Path | None:
    """Locate SameBoy.app via `mdfind`. Cached for the process lifetime."""
    for query in (
        "kMDItemCFBundleIdentifier == 'com.github.liji32.sameboy'",
        "kMDItemFSName == 'SameBoy.app'",
    ):
        try:
            out = subprocess.run(
                ["mdfind", query],
                capture_output=True, text=True, timeout=2,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            continue
        for line in out.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            app = Path(line)
            if (app / "Contents" / "MacOS" / "SameBoy").exists():
                return app
    return None
