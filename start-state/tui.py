"""Long-lived dev-server TUI for start-state.

Edits `state.json` interactively via a questionary menu. Between menu
cycles it polls the .sym mtime and rebuilds `inventory.json` in-process
if the ROM was rebuilt. Tracks the SameBoy subprocess so Re-launch can
terminate the old instance before spawning a fresh one with the new
state.

The TUI is invoked by `start-state.py` when stdin is a TTY and none of
the non-interactive flags (`--no-tui`, `--out`, `--no-launch`,
`--inventory-only`) are set.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import paths, savefile, symfile  # noqa: E402

import apply  # noqa: E402
import inventory  # noqa: E402

SAMEBOY_PATH = "/Applications/SameBoy.app/Contents/MacOS/sameboy"


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
) -> int:
    """Entrypoint. Returns a process exit code."""
    try:
        import questionary  # noqa: F401
    except ImportError:
        print(
            "TUI requires `questionary`. Install with:\n"
            "    pip install -r tools/requirements.txt\n"
            "Then re-run start-state, or use --no-tui for the one-shot flow.",
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
    )
    return server.run()


class DevServer:
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
    ) -> None:
        self.root = root
        self.sym_path = sym_path
        self.debug = debug
        self.state_path = state_path
        self.inventory_path = inventory_path
        self.presets_dir = presets_dir
        self.sav_backups_dir = sav_backups_dir
        self.keep_people = keep_people

        self.inv = inventory.load_or_build(
            root, sym_path, inventory_path,
            force=rebuild_inventory, log=print,
        )
        self.sym_mtime = sym_path.stat().st_mtime
        self.state = apply.load_state(state_path, presets_dir)
        self.state_source = (
            state_path if state_path.exists() else presets_dir / "default.json"
        )
        self.sameboy: subprocess.Popen | None = None

    def run(self) -> int:
        import questionary
        from questionary import Choice, Separator

        print()
        print("=" * 56)
        print("  pokeprism start-state  —  dev server")
        print("=" * 56)

        try:
            while True:
                self._refresh_inventory_if_stale()
                self._print_status_block()

                running = self._sameboy_running()
                action = questionary.select(
                    "What now?",
                    choices=[
                        Choice(
                            ("Re-launch" if running else "Launch")
                            + "  (patch .sav, spawn SameBoy)",
                            value="launch",
                        ),
                        Choice("Edit player...",          value="edit_player"),
                        Choice("Edit map / position...",  value="edit_map"),
                        Choice("Reset state from preset...", value="reset_preset"),
                        Separator(),
                        Choice("Edit party",       value="party",  disabled="v2 — coming soon"),
                        Choice("Edit items",       value="items",  disabled="v2 — coming soon"),
                        Choice("Edit event flags", value="flags",  disabled="v2 — coming soon"),
                        Separator(),
                        Choice("Quit", value="quit"),
                    ],
                ).ask()

                if action is None or action == "quit":
                    break

                handler = {
                    "launch":       self._launch_or_relaunch,
                    "edit_player":  self._edit_player,
                    "edit_map":     self._edit_map,
                    "reset_preset": self._reset_preset,
                }[action]
                try:
                    handler()
                except Exception as e:
                    print(f"\nerror: {e}", file=sys.stderr)
        except KeyboardInterrupt:
            print()

        if self._sameboy_running():
            print("\nSameBoy is still running — leaving it alone. Close it manually when done.")
        return 0

    def _print_status_block(self) -> None:
        player = self.state.get("player") or {}
        map_ = self.state.get("map") or {}
        sb = "running" if self._sameboy_running() else "not running"
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
        print(f"  SameBoy: {sb}")
        print()

    def _refresh_inventory_if_stale(self) -> None:
        try:
            mtime = self.sym_path.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime > self.sym_mtime:
            print("(detected new build — refreshing inventory from .sym)")
            self.inv = inventory.build(self.root, self.sym_path)
            self.inventory_path.write_text(json.dumps(self.inv, indent=2))
            self.sym_mtime = mtime

    def _save_state(self) -> None:
        # Always autosave to the user's state.json, NEVER over presets/.
        self.state_path.write_text(json.dumps(self.state, indent=2) + "\n")
        self.state_source = self.state_path

    def _edit_player(self) -> None:
        import questionary
        from questionary import Choice

        while True:
            player = self.state.setdefault("player", {})
            choice = questionary.select(
                "Edit player",
                choices=[
                    Choice(f"Name    : {player.get('name', '(unset)')}",   value="name"),
                    Choice(f"Money   : {player.get('money', '(unset)')}", value="money"),
                    Choice(f"Badges  : {player.get('badges', '(unset)')}", value="badges"),
                    Choice("← Back", value="back"),
                ],
            ).ask()
            if choice is None or choice == "back":
                return

            if choice == "name":
                val = questionary.text(
                    "Player name (1–7 chars, GB charset):",
                    default=str(player.get("name", "")),
                    validate=lambda s: 1 <= len(s) <= 7 or "1–7 chars",
                ).ask()
                if val is not None:
                    player["name"] = val
                    self._save_state()
            elif choice == "money":
                val = questionary.text(
                    "Money (0–999999):",
                    default=str(player.get("money", 0)),
                    validate=_int_in(0, 999_999),
                ).ask()
                if val is not None:
                    player["money"] = int(val)
                    self._save_state()
            elif choice == "badges":
                cur = player.get("badges") or [0, 0, 0]
                parts = []
                for i, label in enumerate(("Naljo", "Rijon", "Other")):
                    v = questionary.text(
                        f"{label} badges (0–255 bitmask):",
                        default=str(cur[i]),
                        validate=_int_in(0, 255),
                    ).ask()
                    if v is None:
                        break
                    parts.append(int(v))
                if len(parts) == 3:
                    player["badges"] = parts
                    self._save_state()

    def _edit_map(self) -> None:
        import questionary
        from questionary import Choice

        map_names = sorted(m["name"] for m in self.inv["maps"])

        while True:
            map_ = self.state.setdefault("map", {})
            choice = questionary.select(
                "Edit map / position",
                choices=[
                    Choice(f"Map name : {map_.get('name', '(unset)')}", value="name"),
                    Choice(f"X coord  : {map_.get('x', '(unset)')}",    value="x"),
                    Choice(f"Y coord  : {map_.get('y', '(unset)')}",    value="y"),
                    Choice("← Back", value="back"),
                ],
            ).ask()
            if choice is None or choice == "back":
                return

            if choice == "name":
                val = questionary.autocomplete(
                    "Map name (tab to autocomplete):",
                    choices=map_names,
                    default=str(map_.get("name", "")),
                    validate=lambda s: s in map_names or f"unknown map: {s}",
                ).ask()
                if val is not None:
                    map_["name"] = val
                    self._save_state()
            elif choice in ("x", "y"):
                bound = self._coord_bound(map_, choice)
                val = questionary.text(
                    f"{choice.upper()} coord (0–{bound}):",
                    default=str(map_.get(choice, 0)),
                    validate=_int_in(0, bound),
                ).ask()
                if val is not None:
                    map_[choice] = int(val)
                    self._save_state()

    def _coord_bound(self, map_: dict, axis: str) -> int:
        """Upper bound for a coord. The map's block grid is `width × height`
        blocks; each block is 2 tiles per axis, so walkable coords run
        0..(blocks*2 - 1). When the map name is unset or unknown, fall back
        to 0..255 (a tile coord is one byte)."""
        mdef = next(
            (m for m in self.inv["maps"] if m["name"] == map_.get("name")), None
        )
        if mdef is None:
            return 255
        return (mdef["width"] if axis == "x" else mdef["height"]) * 2 - 1

    def _reset_preset(self) -> None:
        import questionary
        from questionary import Choice

        presets = sorted(self.presets_dir.glob("*.json"))
        if not presets:
            print("(no presets in presets/)")
            return

        choice = questionary.select(
            "Reset state from preset",
            choices=[Choice(p.name, value=p) for p in presets]
            + [Choice("← Cancel", value=None)],
        ).ask()
        if choice is None:
            return

        ok = questionary.confirm(
            f"Overwrite {self._pretty(self.state_path)} with {choice.name}?",
            default=False,
        ).ask()
        if not ok:
            return

        self.state = json.loads(choice.read_text())
        self._save_state()
        print(f"Reset state from {choice.name}")

    def _launch_or_relaunch(self) -> None:
        rom_path = paths.rom_path(self.root, debug=self.debug)
        target_sav = rom_path.with_suffix(".sav")

        if not target_sav.exists():
            print(
                f"error: no template save at {target_sav}.\n"
                "Run the ROM in an emulator once, complete the intro, and "
                "save in-game first.",
                file=sys.stderr,
            )
            return

        sav = savefile.SaveFile.load(target_sav)
        if not apply.looks_like_real_save(sav, self.inv):
            print(
                f"error: template at {target_sav} doesn't look like a valid "
                "save (validity bytes missing).",
                file=sys.stderr,
            )
            return

        self.sav_backups_dir.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.sav_backups_dir / f"{target_sav.stem}-{ts}.sav"
        backup.write_bytes(target_sav.read_bytes())
        print(f"Backed up {target_sav.name} → {self._pretty(backup)}")

        syms = symfile.SymFile.load(self.sym_path)
        changes = apply.apply_state(
            sav, self.state, self.inv,
            rom_path=rom_path, syms=syms, keep_people=self.keep_people,
        )
        apply.recompute_checksums(sav, self.inv)
        sav.write(target_sav)
        print(f"Wrote {self._pretty(target_sav)} ({len(changes)} fields changed)")
        for c in changes:
            print(f"  {c}")

        if self._sameboy_running():
            print("Terminating old SameBoy...")
            assert self.sameboy is not None
            self.sameboy.terminate()
            try:
                self.sameboy.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.sameboy.kill()
                self.sameboy.wait()
            self.sameboy = None

        cmd = self._sameboy_cmd(rom_path)
        if cmd is None:
            print(
                f"\nWARNING: SameBoy not found. Launch {rom_path} manually.",
                file=sys.stderr,
            )
            return
        print(f"Launching {cmd[0]}...")
        try:
            self.sameboy = subprocess.Popen(cmd)
        except OSError as e:
            print(f"failed to launch: {e}", file=sys.stderr)
            self.sameboy = None

    def _sameboy_cmd(self, rom_path: Path) -> list[str] | None:
        if Path(SAMEBOY_PATH).exists():
            return [SAMEBOY_PATH, str(rom_path)]
        if shutil.which("sameboy"):
            return ["sameboy", str(rom_path)]
        if sys.platform == "darwin":
            # Last-ditch. `open -a` is fire-and-forget — the Popen handle
            # won't track the real SameBoy process, so Re-launch will spawn
            # a second window instead of replacing the first. Acceptable
            # fallback for users without SameBoy at the canonical path.
            return ["open", "-a", "SameBoy", str(rom_path)]
        return None

    def _sameboy_running(self) -> bool:
        return self.sameboy is not None and self.sameboy.poll() is None

    def _pretty(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


def _int_in(lo: int, hi: int):
    def _validate(s: str):
        try:
            v = int(s)
        except ValueError:
            return "not an integer"
        if not (lo <= v <= hi):
            return f"must be {lo}..{hi}"
        return True
    return _validate
