#!/usr/bin/env python3
"""prism-dev — launch pokeprism in a custom initial state.

Default behaviour (TTY, no flags): drop into the interactive TUI in
tui.py. The TUI edits state.json on the fly, watches the .sym for
rebuilds, and manages the SameBoy subprocess.

One-shot behaviour (any of `--no-tui`, `--out`, `--no-launch`,
`--inventory-only`, or non-TTY stdin): read `state.json`, patch a
template `.sav` (recomputing both SRAM checksums), and spawn SameBoy.
Press A on "Continue" in the game's main menu.

Runtime artifacts (inventory.json, state.json, sav-backups/, presets/)
live under `<pokeprism>/.devtools/`. The first run (or any run after a
rebuild) refreshes `.devtools/inventory.json` from the .sym.

Usage:
    prism-dev                          # interactive TUI (default on TTY)
    prism-dev --no-tui                 # one-shot patch + launch
    prism-dev --no-launch              # patch only, don't spawn SameBoy
    prism-dev --inventory-only         # rebuild inventory, print summary
    prism-dev --state PATH             # alternate state.json
    prism-dev --template PATH          # alternate template .sav
    prism-dev --out PATH               # write patched .sav elsewhere
    prism-dev --rebuild-inventory      # force inventory rebuild
    prism-dev --debug                  # use the debug ROM's .sym
    prism-dev --keep-people            # don't reset NPC slots on map change
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from pokeprism_devtools import paths, savefile, symfile

from . import apply, inventory, launcher


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="start-state")
    p.add_argument(
        "--rebuild-inventory",
        action="store_true",
        help="force rebuild of inventory.json",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="use the debug ROM (and its .sym) instead of release",
    )
    p.add_argument(
        "--state",
        type=Path,
        default=None,
        help="state.json describing the desired initial state "
        "(default: <repo>/.devtools/state.json; if missing, falls back to "
        "<repo>/.devtools/presets/default.json, then to a no-op state)",
    )
    p.add_argument(
        "--template",
        type=Path,
        default=None,
        help="path to a .sav to use as template instead of the ROM's adjacent "
        ".sav (which is also the launch target)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the patched save here instead of overwriting the ROM's "
        ".sav (also implies --no-launch)",
    )
    p.add_argument(
        "--no-launch",
        action="store_true",
        help="patch the save but don't spawn SameBoy",
    )
    p.add_argument(
        "--inventory-only",
        action="store_true",
        help="rebuild the inventory if needed, print a summary, and exit",
    )
    p.add_argument(
        "--keep-people",
        action="store_true",
        help="don't reset NPC objects on map change (default: zero NPC slots "
        "and update the player struct to the new coords)",
    )
    p.add_argument(
        "--no-tui",
        action="store_true",
        help="skip the interactive menu; use the one-shot patch+launch flow",
    )
    args = p.parse_args(argv)

    root = paths.repo_root()
    devtools_dir = root / ".devtools"
    devtools_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = devtools_dir / "inventory.json"
    state_path = args.state if args.state is not None else devtools_dir / "state.json"
    presets_dir = devtools_dir / "presets"
    sav_backups_dir = devtools_dir / "sav-backups"

    sym_path_resolved = paths.sym_path(root, debug=args.debug)

    if args.inventory_only:
        inv = inventory.load_or_build(
            root, sym_path_resolved, inventory_path,
            force=args.rebuild_inventory,
        )
        inventory.print_summary(inv)
        return 0

    # Default to TUI when interactive. Any explicit non-interactive intent
    # (--no-tui, --out, --no-launch) or a piped stdin falls through to the
    # one-shot patch+launch flow.
    one_shot = (
        args.no_tui or args.out is not None or args.no_launch
        or not sys.stdin.isatty()
    )
    if not one_shot:
        from . import tui
        return tui.run(
            root=root,
            sym_path=sym_path_resolved,
            debug=args.debug,
            state_path=state_path,
            inventory_path=inventory_path,
            presets_dir=presets_dir,
            sav_backups_dir=sav_backups_dir,
            keep_people=args.keep_people,
            rebuild_inventory=args.rebuild_inventory,
        )

    inv = inventory.load_or_build(
        root, sym_path_resolved, inventory_path,
        force=args.rebuild_inventory,
    )
    state = apply.load_state(state_path, presets_dir)
    if state_path.exists():
        state_source = state_path
    elif (presets_dir / "default.json").exists():
        state_source = presets_dir / "default.json"
    else:
        state_source = "built-in no-op default"
    print(f"State loaded from {state_source}")

    rom_path = paths.rom_path(root, debug=args.debug)
    target_sav = args.out if args.out is not None else rom_path.with_suffix(".sav")
    # Default the template to the ROM's adjacent .sav (the "live" save).
    # That way `--out PATH` alone works as advertised: read the ROM's
    # save, patch, write the copy to PATH. Without this, passing `--out`
    # without `--template` made the template default to the (non-existent)
    # target, producing a confusing "no template" error.
    template_sav = (
        args.template if args.template is not None else rom_path.with_suffix(".sav")
    )

    if not template_sav.exists():
        print(
            f"\nerror: no template save at {template_sav}.\n"
            "Run the ROM in an emulator once, complete the intro, and save "
            "the game in-game to create a starting .sav. Then re-run "
            "start-state.",
            file=sys.stderr,
        )
        return 2

    sav = savefile.SaveFile.load(template_sav)
    if not apply.looks_like_real_save(sav, inv):
        print(
            f"\nerror: template at {template_sav} doesn't look like a valid "
            "save (validity bytes missing). Play the game once to create "
            "a proper save.",
            file=sys.stderr,
        )
        return 2

    # Back up the existing target so we never silently destroy progress.
    if target_sav.exists():
        sav_backups_dir.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = sav_backups_dir / f"{target_sav.stem}-{ts}.sav"
        backup.write_bytes(target_sav.read_bytes())
        print(f"Backed up {target_sav.name} → {_pretty_path(backup, root)}")

    changes = apply.apply_state(
        sav,
        state,
        inv,
        rom_path=rom_path,
        syms=symfile.SymFile.load(sym_path_resolved),
        keep_people=args.keep_people,
    )
    apply.recompute_checksums(sav, inv)

    sav.write(target_sav)
    print(f"Wrote {_pretty_path(target_sav, root)} ({len(changes)} fields changed)")
    for c in changes:
        print(f"  {c}")

    if args.out is not None or args.no_launch:
        print("\nDone. Launch the ROM manually to verify.")
        return 0

    return _launch(rom_path)


def _pretty_path(path: Path, root: Path) -> str:
    """Show path as relative to repo root if possible; otherwise absolute."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _launch(rom_path: Path) -> int:
    """Spawn SameBoy with the ROM. SameBoy auto-loads the adjacent .sav."""
    import subprocess

    cmd, _trackable = launcher.build_cmd(rom_path)
    if cmd is None:
        print(
            f"\nWARNING: SameBoy not found. ROM and patched .sav are ready "
            f"at:\n  {rom_path}\nLaunch manually, or set $SAMEBOY_BIN.",
            file=sys.stderr,
        )
        return 0

    print(f"\nLaunching {cmd[0]} ...")
    try:
        subprocess.Popen(cmd)
    except OSError as e:
        print(f"failed to launch: {e}", file=sys.stderr)
        return 1
    launcher.focus_after_launch()
    return 0


if __name__ == "__main__":
    sys.exit(main())
