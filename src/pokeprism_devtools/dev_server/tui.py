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
import subprocess
import sys
import threading
from pathlib import Path
import time

from pokeprism_devtools.shared import paths, savefile, symfile

from . import apply, inventory, launcher


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
        self.sameboy: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._watcher_stop = threading.Event()
        self._watcher_thread: threading.Thread | None = None

    def run(self) -> int:
        import questionary
        from questionary import Choice, Separator

        print()
        print("=" * 56)
        print("  pokeprism prism-dev  —  dev server")
        print("=" * 56)

        self._start_rebuild_watcher()
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
                        Choice("Edit party...",    value="edit_party"),
                        Choice("Edit items",       value="items",  disabled="coming soon"),
                        Choice("Edit flags...",    value="edit_flags"),
                        Separator(),
                        Choice("Quit", value="quit"),
                    ],
                ).ask()

                if action is None or action == "quit":
                    break

                handler = {
                    "launch":       self._patch_and_launch,
                    "edit_player":  self._edit_player,
                    "edit_map":     self._edit_map,
                    "edit_party":   self._edit_party,
                    "edit_flags":   self._edit_flags,
                    "reset_preset": self._reset_preset,
                }[action]
                try:
                    handler()
                except Exception as e:
                    print(f"\nerror: {e}", file=sys.stderr)
        except KeyboardInterrupt:
            print()
        finally:
            self._watcher_stop.set()
            if self._watcher_thread is not None:
                self._watcher_thread.join(timeout=3.0)

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
        party_state = self.state.get("party") or []
        if party_state:
            descs = ", ".join(
                f"{m.get('species', '?')}@L{m.get('level', '?')}"
                for m in party_state
            )
        else:
            descs = "(template)"
        print(f"           party:  {descs}")
        flags_state = self.state.get("flags") or {}
        n_ev = len(flags_state.get("event", []))
        n_en = len(flags_state.get("engine", []))
        print(f"           flags:  {n_ev} event, {n_en} engine")
        print(f"  SameBoy: {sb}")
        print()

    def _refresh_inventory_if_stale(self) -> bool | None:
        try:
            mtime = self.sym_path.stat().st_mtime
        except FileNotFoundError:
            return
        with self._lock:
            if mtime <= self.sym_mtime:
                return
            print("(detected new build — refreshing inventory from .sym)")
            self.inv = inventory.build(self.root, self.sym_path)
            self.inventory_path.write_text(json.dumps(self.inv, indent=2))
            self.sym_mtime = mtime
        return True

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

    def _edit_party(self) -> None:
        import questionary
        from questionary import Choice

        species_names = sorted(self.inv["species_data"].keys())
        move_names = sorted(m["name"] for m in self.inv["moves"])

        while True:
            party = self.state.setdefault("party", [])
            choices: list = []
            for i in range(6):
                if i < len(party):
                    mon = party[i]
                    label = (
                        f"Slot {i+1}: {mon.get('species', '?')} "
                        f"L{mon.get('level', '?')}"
                    )
                    if mon.get("nickname"):
                        label += f"  '{mon['nickname']}'"
                else:
                    label = f"Slot {i+1}: (empty)"
                choices.append(Choice(label, value=("slot", i)))
            if party:
                choices.append(Choice("Clear party", value=("clear", None)))
            choices.append(Choice("← Back", value=("back", None)))

            action = questionary.select("Edit party", choices=choices).ask()
            if action is None or action[0] == "back":
                return
            if action[0] == "clear":
                if questionary.confirm(
                    "Clear all party slots?", default=False
                ).ask():
                    self.state["party"] = []
                    self._save_state()
                continue
            self._edit_party_slot(action[1], species_names, move_names)

    def _edit_party_slot(
        self, idx: int, species_names: list[str], move_names: list[str]
    ) -> None:
        import questionary
        from questionary import Choice

        party = self.state.setdefault("party", [])
        while idx >= len(party):
            # Lazily allocate an empty slot. Species required before save.
            party.append({})
        mon = party[idx]

        while True:
            label_species = mon.get("species", "(unset)")
            label_level = mon.get("level", "(unset)")
            label_nick = mon.get("nickname") or "(default)"
            label_moves = (
                ", ".join(mon["moves"]) if mon.get("moves") else "(from learnset)"
            )

            choice = questionary.select(
                f"Edit slot {idx + 1}",
                choices=[
                    Choice(f"Species  : {label_species}",   value="species"),
                    Choice(f"Level    : {label_level}",     value="level"),
                    Choice(f"Nickname : {label_nick}",      value="nickname"),
                    Choice(f"Moves    : {label_moves}",     value="moves"),
                    Choice("Remove slot",                   value="remove"),
                    Choice("← Back",                        value="back"),
                ],
            ).ask()
            if choice is None or choice == "back":
                # Drop the slot entirely if species was never set.
                if not mon.get("species"):
                    party.pop(idx)
                    self._save_state()
                return

            if choice == "species":
                val = questionary.autocomplete(
                    "Species (tab to autocomplete):",
                    choices=species_names,
                    default=str(mon.get("species", "")),
                    validate=lambda s: s in species_names or f"unknown species: {s}",
                ).ask()
                if val is not None:
                    mon["species"] = val
                    # Stamp a sane default level if unset.
                    mon.setdefault("level", 5)
                    self._save_state()
            elif choice == "level":
                val = questionary.text(
                    "Level (1–100):",
                    default=str(mon.get("level", 5)),
                    validate=_int_in(1, 100),
                ).ask()
                if val is not None:
                    mon["level"] = int(val)
                    self._save_state()
            elif choice == "nickname":
                val = questionary.text(
                    "Nickname (blank = species name, max 10 chars):",
                    default=str(mon.get("nickname") or ""),
                    validate=lambda s: (len(s) <= 10) or "max 10 chars",
                ).ask()
                if val is None:
                    continue
                if val == "":
                    mon.pop("nickname", None)
                else:
                    mon["nickname"] = val
                self._save_state()
            elif choice == "moves":
                self._edit_party_moves(mon, move_names)
            elif choice == "remove":
                party.pop(idx)
                self._save_state()
                return

    def _edit_party_moves(self, mon: dict, move_names: list[str]) -> None:
        import questionary

        current = mon.get("moves") or []
        # Pad to 4 slots so the user can replace one at a time.
        current = (current + [""] * 4)[:4]
        out: list[str] = []
        for i in range(4):
            val = questionary.autocomplete(
                f"Move {i + 1} (blank = empty, '-' = revert to learnset):",
                choices=move_names,
                default=current[i],
                validate=lambda s: (
                    s == "" or s == "-" or s in move_names
                ) or f"unknown move: {s}",
            ).ask()
            if val is None:
                return
            if val == "-":
                mon.pop("moves", None)
                self._save_state()
                return
            if val:
                out.append(val)
        if out:
            mon["moves"] = out
        else:
            mon.pop("moves", None)
        self._save_state()

    def _edit_flags(self) -> None:
        import questionary
        from questionary import Choice

        while True:
            # Flags menu
            flags_state = self.state.setdefault("flags", {})
            n_ev = len(flags_state.get("event", []))
            n_en = len(flags_state.get("engine", []))
            choice = questionary.select(
                "Edit flags",
                choices=[
                    Choice(f"Event flags   ({n_ev} set)", value="event"),
                    Choice(f"Engine flags  ({n_en} set)", value="engine"),
                    Choice("← Back", value="back"),
                ],
            ).ask()
            if choice is None or choice == "back":
                return
            if choice == "event":
                self._edit_flag_group("Event flags", "event_flags", "event")
            else:
                self._edit_flag_group("Engine flags", "engine_flags", "engine")

    def _edit_flag_group(self, label: str, inv_key: str, state_key: str) -> None:
        """Generic add/remove editor for a named flag group (event or engine)."""
        import questionary
        from questionary import Choice, Separator

        flag_names = sorted(f["name"] for f in self.inv.get(inv_key, []))

        while True:
            flags_state = self.state.setdefault("flags", {})
            set_flags: list[str] = flags_state.setdefault(state_key, [])

            choices: list = []
            for name in sorted(set_flags):
                choices.append(Choice(f"  [-] {name}", value=("remove_one", name)))
            if set_flags:
                choices.append(Separator())
            choices.append(Choice("Set flag...", value=("add", None)))
            if set_flags:
                choices.append(Choice(f"Unset flag...  ({len(set_flags)} set)", value=("remove", None)))
                choices.append(Choice(f"Clear all {label.lower()}", value=("clear", None)))
            choices.append(Choice("← Back", value=("back", None)))

            action = questionary.select(
                f"{label} — {len(set_flags)} set", choices=choices
            ).ask()
            if action is None or action[0] == "back":
                return

            if action[0] == "add":
                val = questionary.autocomplete(
                    "Flag name (tab to autocomplete):",
                    choices=flag_names,
                    validate=lambda s: s in flag_names or f"unknown flag: {s}",
                ).ask()
                if val and val not in set_flags:
                    set_flags.append(val)
                    self._save_state()
            elif action[0] == "remove_one":
                name = action[1]
                if name in set_flags:
                    set_flags.remove(name)
                    self._save_state()
            elif action[0] == "remove":
                val = questionary.select(
                    "Unset which flag?",
                    choices=[Choice(n, value=n) for n in sorted(set_flags)]
                    + [Choice("← Cancel", value=None)],
                ).ask()
                if val and val in set_flags:
                    set_flags.remove(val)
                    self._save_state()
            elif action[0] == "clear":
                if questionary.confirm(f"Clear all {label.lower()}?", default=False).ask():
                    flags_state[state_key] = []
                    self._save_state()

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

    def _patch_and_launch(self) -> None:
        rom_path = paths.rom_path(self.root, debug=self.debug)
        self._patch_save(rom_path)
        # Run (or re-run) SameBoy
        self._launch_or_relaunch(rom_path)

    def _patch_save(self, rom_path: Path) -> None:
        target_sav = rom_path.with_suffix(".sav")

        if not target_sav.exists():
            print(
                f"error: no template save at {target_sav}.\n"
                "Run the ROM in an emulator once, complete the intro, and "
                "save in-game first.",
                file=sys.stderr,
            )
            return

        # Validate save file
        sav = savefile.SaveFile.load(target_sav)
        if not apply.looks_like_real_save(sav, self.inv):
            print(
                f"error: template at {target_sav} doesn't look like a valid "
                "save (validity bytes missing).",
                file=sys.stderr,
            )
            return

        # Backup the save file
        self.sav_backups_dir.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.sav_backups_dir / f"{target_sav.stem}-{ts}.sav"
        backup.write_bytes(target_sav.read_bytes())
        print(f"Backed up {target_sav.name} → {self._pretty(backup)}")

        # Patch the save file
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

    def _launch_or_relaunch(self, rom_path: Path, *, silent: bool = False) -> None:
        cmd, trackable = launcher.build_cmd(rom_path)
        if cmd is None:
            print(
                f"\nWARNING: SameBoy not found. Launch {rom_path} manually, "
                "or set $SAMEBOY_BIN to the binary path.",
                file=sys.stderr,
            )
            return

        with self._lock:
            if self._sameboy_running():
                if not silent:
                    print("Terminating old SameBoy...")
                assert self.sameboy is not None
                self.sameboy.terminate()
                try:
                    self.sameboy.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.sameboy.kill()
                    self.sameboy.wait()
                self.sameboy = None

        if not trackable:
            # We only have `open -a SameBoy` to work with — Popen will
            # hold the launcher's PID, not SameBoy's, so Re-launch
            # can't kill the prior instance. Warn once per launch.
            print(
                "warning: SameBoy.app not found via $SAMEBOY_BIN, $PATH, or "
                "Spotlight; using `open -a`. Re-launch will not be able to "
                "terminate the previous instance. Set $SAMEBOY_BIN to the "
                "SameBoy binary path to fix.",
                file=sys.stderr,
            )

        if not silent:
            print(f"Launching {cmd[0]}...")
        try:
            proc = subprocess.Popen(cmd)
        except OSError as e:
            print(f"failed to launch: {e}", file=sys.stderr)
            return
        with self._lock:
            self.sameboy = proc
        # Give it some time to settle, then bring window to the front
        time.sleep(1)
        launcher.focus_after_launch()

    def _start_rebuild_watcher(self) -> None:
        def _watch() -> None:
            while not self._watcher_stop.wait(2.0):
                try:
                    mtime = self.sym_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                with self._lock:
                    if mtime <= self.sym_mtime:
                        continue
                    self.inv = inventory.build(self.root, self.sym_path)
                    self.inventory_path.write_text(json.dumps(self.inv, indent=2))
                    self.sym_mtime = mtime
                if self.auto_relaunch:
                    self._launch_or_relaunch(paths.rom_path(self.root, debug=self.debug), silent=True)

        self._watcher_thread = threading.Thread(
            target=_watch, daemon=True, name="rebuild-watcher"
        )
        self._watcher_thread.start()

    def _sameboy_running(self) -> bool:
        with self._lock:
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
