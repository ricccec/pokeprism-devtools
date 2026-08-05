"""Long-lived dev-server TUI for prism-dev.

Edits `state.json` interactively via a questionary menu. Between menu
cycles it polls the .sym mtime and rebuilds `inventory.json` in-process
if the ROM was rebuilt. Tracks the SameBoy subprocess so Re-launch can
terminate the old instance before spawning a fresh one with the new
state.

The TUI is invoked by `prism-dev.py` when stdin is a TTY and none of
the non-interactive flags (`--no-tui`, `--out`, `--no-launch`,
`--inventory-only`) are set.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import threading
from pathlib import Path

from pokeprism_devtools.shared import paths

from . import apply, inventory, playtest
from .state import (BagMenu, FlagMenu, PartyMenu, PlayerMenu, PositionMenu,
                    PresetMenu, TmhmMenu)

#: How often the background watcher asks whether the ROM was rebuilt. A `stat`
#: of one file, so the cost is nil; the thing it is watching for is a `make` in
#: another window, which you want reflected before your next keystroke rather
#: than at the next menu cycle.
SYM_POLL_SECONDS = 2.0


def run(
    *,
    root: Path,
    sym_path: Path,
    debug: bool,
    state_path: Path,
    inventory_path: Path,
    presets_dir: Path,
    sav_backups_dir: Path,
    keep_people: bool,
    rebuild_inventory: bool = False,
    auto_relaunch: bool = False,
) -> int:
    """Entrypoint. Returns a process exit code."""
    try:
        import questionary  # noqa: F401
    except ImportError:
        print(
            "TUI requires `questionary`. Reinstall pokeprism-devtools:\n"
            "    pipx install --force <path-to-pokeprism-devtools>\n"
            "Then re-run prism-dev, or use --no-tui for the one-shot flow.",
            file=sys.stderr,
        )
        return 2

    server = DevServer(
        root=root,
        sym_path=sym_path,
        debug=debug,
        state_path=state_path,
        inventory_path=inventory_path,
        presets_dir=presets_dir,
        sav_backups_dir=sav_backups_dir,
        keep_people=keep_people,
        rebuild_inventory=rebuild_inventory,
        auto_relaunch=auto_relaunch,
    )
    return server.run()


class DevServer(
    PlayerMenu, PositionMenu, PartyMenu, BagMenu, FlagMenu, TmhmMenu,
    PresetMenu,
):

    def __init__(
        self,
        *,
        root: Path,
        sym_path: Path,
        debug: bool,
        state_path: Path,
        inventory_path: Path,
        presets_dir: Path,
        sav_backups_dir: Path,
        keep_people: bool,
        rebuild_inventory: bool,
        auto_relaunch: bool,
    ) -> None:
        self.root = root
        self.sym_path = sym_path
        self.debug = debug
        self.state_path = state_path
        self.inventory_path = inventory_path
        self.presets_dir = presets_dir
        self.sav_backups_dir = sav_backups_dir
        self.keep_people = keep_people
        self.auto_relaunch = auto_relaunch

        self.inv = inventory.load_or_build(
            root, sym_path, inventory_path,
            force=rebuild_inventory, log=print,
        )
        self.sym_mtime = sym_path.stat().st_mtime
        self.state = apply.load_state(state_path, presets_dir)
        self.state_source = (
            state_path if state_path.exists() else presets_dir / "default.json"
        )
        # The emulator owns its own process and its own lock; self._lock below
        # guards the inventory and the state, which the rebuild watcher touches.
        self.emulator = playtest.Emulator()
        self._lock = threading.RLock()
        self._watcher_stop = threading.Event()
        self._watcher_thread: threading.Thread | None = None

    def run(self) -> int:
        import questionary

        print()
        print("=" * 56)
        print("  pokeprism prism-dev  —  dev server")
        print("=" * 56)

        self._start_rebuild_watcher()
        try:
            while True:
                self._refresh_inventory_if_stale()
                self._print_status_block()

                action = questionary.select(
                    "What now?",
                    choices=_build_menu_rows(running=self.emulator.running),
                ).ask()
                if action is None or action == "quit":
                    break

                # An editor that raises must not end the session: this server
                # is long-lived, and a traceback would take the .sym watcher
                # and the emulator's handle down with it.
                try:
                    self._handlers()[action]()
                except Exception as e:
                    print(f"\nerror: {e}", file=sys.stderr)
        except KeyboardInterrupt:
            print()
        finally:
            self._watcher_stop.set()
            if self._watcher_thread is not None:
                self._watcher_thread.join(timeout=3.0)

        if self.emulator.running:
            print("\nSameBoy is still running — leaving it alone. Close it manually when done.")
        return 0

    def _handlers(self) -> dict:
        """What each menu entry runs. Keyed by the value `_build_menu_rows` offers, so
        an entry that stops being reachable is a `KeyError` here rather than a
        row that quietly does nothing."""
        return {
            "launch":       self._patch_and_launch,
            "edit_player":  self._edit_player,
            "edit_map":     self._edit_map,
            "edit_party":   self._edit_party,
            "edit_items":   self._edit_items,
            "edit_flags":   self._edit_flags,
            "edit_tmhms":   self._edit_tmhms,
            "reset_preset": self._reset_preset,
        }

    def _print_status_block(self) -> None:
        player = self.state.get("player") or {}
        map_ = self.state.get("map") or {}
        sb = "running" if self.emulator.running else "not running"
        sym_when = dt.datetime.fromtimestamp(self.sym_mtime).strftime("%Y-%m-%d %H:%M:%S")
        rom = paths.rom_path(self.root, debug=self.debug)

        print()
        print(f"  Build:   {rom.name}    sym mtime: {sym_when}")
        print(f"  State:   {self._pretty(self.state_source)}")
        print(
            f"           player: name={player.get('name', '?')!r:>10s}  "
            f"money={player.get('money', '?')}  badges={player.get('badges', '?')}"
        )
        print(
            f"           map:    {map_.get('name', '?')}  "
            f"at ({map_.get('x', '?')}, {map_.get('y', '?')})"
        )
        party_state = self.state.get("party") or []
        if party_state:
            descs = ", ".join(
                f"{m.get('species', '?')}@L{m.get('level', '?')}"
                for m in party_state
            )
        else:
            descs = "(template)"
        print(f"           party:  {descs}")
        items_state = self.state.get("items")
        if items_state:
            counts = ", ".join(
                f"{len(items_state.get(k, []))} {lbl}"
                for k, lbl in (("items", "items"), ("balls", "balls"), ("key_items", "key"))
                if k in items_state
            )
        else:
            counts = "(template)"
        print(f"           items:  {counts}")
        flags_state = self.state.get("flags") or {}
        n_ev = len(flags_state.get("event", []))
        n_en = len(flags_state.get("engine", []))
        print(f"           flags:  {n_ev} event, {n_en} engine")
        tmhms_state = self.state.get("tmhms")
        if tmhms_state is not None:
            total = len(self.inv.get("tmhms", []))
            tmhms_desc = f"{len(tmhms_state)}/{total} owned"
        else:
            tmhms_desc = "(template)"
        print(f"           tmhms:  {tmhms_desc}")
        print(f"  SameBoy: {sb}")
        print()

    def _refresh_inventory_if_stale(self, *, announce: bool = True) -> bool | None:
        """Rebuild `inventory.json` if the ROM has been rebuilt since we read it.
        True if it was, None if there was nothing to do.

        `announce=False` for the watcher thread, which runs while a questionary
        prompt owns the terminal and would print across it. A missing `.sym` is
        `make clean`, not a new build.
        """
        try:
            mtime = self.sym_path.stat().st_mtime
        except FileNotFoundError:
            return
        with self._lock:
            if mtime <= self.sym_mtime:
                return
            if announce:
                print("(detected new build — refreshing inventory from .sym)")
            self.inv = inventory.build(self.root, self.sym_path)
            self.inventory_path.write_text(json.dumps(self.inv, indent=2))
            self.sym_mtime = mtime
        return True

    def _save_state(self) -> None:
        # Always autosave to the user's state.json, NEVER over presets/.
        self.state_path.write_text(json.dumps(self.state, indent=2) + "\n")
        self.state_source = self.state_path

    def _patch_and_launch(self) -> None:
        rom_path = paths.rom_path(self.root, debug=self.debug)
        self._patch_save(rom_path)
        # Run (or re-run) SameBoy
        self._launch_or_relaunch(rom_path)

    def _patch_save(self, rom_path: Path) -> None:
        try:
            report = playtest.patch_save(
                rom_path,
                sym_path=self.sym_path,
                inv=self.inv,
                state=self.state,
                backups_dir=self.sav_backups_dir,
                keep_people=self.keep_people,
            )
        except playtest.PlaytestError as e:
            print(f"error: {e}", file=sys.stderr)
            return

        if report.backup is not None:
            print(f"Backed up {report.target.name} → {self._pretty(report.backup)}")
        print(f"Wrote {self._pretty(report.target)} "
              f"({len(report.changes)} fields changed)")
        for c in report.changes:
            print(f"  {c}")

    def _launch_or_relaunch(self, rom_path: Path, *, silent: bool = False) -> None:
        report = self.emulator.launch(rom_path)
        if report.replaced and not silent:
            print("Terminated old SameBoy.")
        for w in report.warnings:
            print(f"warning: {w}", file=sys.stderr)
        if report.launched and not silent:
            print(f"Launching {report.command}...")

    def _start_rebuild_watcher(self) -> None:
        """Watch the `.sym` in the background, so a rebuild is picked up while
        you are sitting in a menu rather than at the next menu cycle."""
        def _watch() -> None:
            while not self._watcher_stop.wait(SYM_POLL_SECONDS):
                if self._refresh_inventory_if_stale(announce=False) \
                        and self.auto_relaunch:
                    self._launch_or_relaunch(
                        paths.rom_path(self.root, debug=self.debug), silent=True)

        self._watcher_thread = threading.Thread(
            target=_watch, daemon=True, name="rebuild-watcher"
        )
        self._watcher_thread.start()

    def _pretty(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


def _build_menu_rows(*, running: bool) -> list:
    """The top menu. Grouped by how often you reach for a thing rather than by
    what it does — launching and the two you retune between launches first, the
    four bulk editors below the rule.

    The first row is the only one that is not a constant: it says Re-launch once
    SameBoy is up, because that press terminates the old instance.
    """
    from questionary import Choice, Separator

    return [
        Choice(("Re-launch" if running else "Launch")
               + "  (patch .sav, spawn SameBoy)", value="launch"),
        Choice("Edit player...",          value="edit_player"),
        Choice("Edit map / position...",  value="edit_map"),
        Choice("Reset state from preset...", value="reset_preset"),
        Separator(),
        Choice("Edit party...",    value="edit_party"),
        Choice("Edit items...",    value="edit_items"),
        Choice("Edit flags...",    value="edit_flags"),
        Choice("Edit TM/HMs...",   value="edit_tmhms"),
        Separator(),
        Choice("Quit", value="quit"),
    ]
