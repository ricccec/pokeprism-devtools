#!/usr/bin/env python3
"""start-state — launch pokeprism in a custom initial state.

Default behaviour (TTY, no flags): drop into the interactive TUI in
`tui.py`. The TUI edits state.json on the fly, watches the .sym for
rebuilds, and manages the SameBoy subprocess.

One-shot behaviour (any of `--no-tui`, `--out`, `--no-launch`,
`--inventory-only`, or non-TTY stdin): read `state.json`, patch a
template `.sav` (recomputing both SRAM checksums), and spawn SameBoy.
Press A on "Continue" in the game's main menu.

The first run (or any run after a rebuild) refreshes `inventory.json`
next to this script — a catalog of every map, pokemon, item, move, and
event flag plus the .sav file offsets needed to patch.

Usage:
    start-state.py                       # interactive TUI (default on TTY)
    start-state.py --no-tui              # one-shot patch + launch
    start-state.py --no-launch           # patch only, don't spawn SameBoy
    start-state.py --inventory-only      # rebuild inventory, print summary
    start-state.py --state PATH          # alternate state.json
    start-state.py --template PATH       # alternate template .sav
    start-state.py --out PATH            # write patched .sav elsewhere
    start-state.py --rebuild-inventory   # force inventory rebuild
    start-state.py --debug               # use the debug ROM's .sym
    start-state.py --keep-people         # don't reset NPC slots on map change
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib import paths, savefile, symfile  # noqa: E402

import apply  # noqa: E402
import inventory  # noqa: E402
import launcher  # noqa: E402

INVENTORY_PATH = Path(__file__).parent / "inventory.json"
STATE_PATH = Path(__file__).parent / "state.json"
PRESETS_DIR = Path(__file__).parent / "presets"
SAV_BACKUPS_DIR = Path(__file__).parent / "sav-backups"


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
        default=STATE_PATH,
        help="state.json describing the desired initial state "
        "(default: tools/start-state/state.json; if missing, uses "
        "presets/default.json)",
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
    sym_path_resolved = paths.sym_path(root, debug=args.debug)

    if args.inventory_only:
        inv = inventory.load_or_build(
            root, sym_path_resolved, INVENTORY_PATH,
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
        import tui
        return tui.run(
            root=root,
            sym_path=sym_path_resolved,
            debug=args.debug,
            state_path=args.state,
            inventory_path=INVENTORY_PATH,
            presets_dir=PRESETS_DIR,
            sav_backups_dir=SAV_BACKUPS_DIR,
            keep_people=args.keep_people,
            rebuild_inventory=args.rebuild_inventory,
        )

    inv = inventory.load_or_build(
        root, sym_path_resolved, INVENTORY_PATH,
        force=args.rebuild_inventory,
    )
    state = apply.load_state(args.state, PRESETS_DIR)
    print(f"State loaded from {args.state if args.state.exists() else 'presets/default.json'}")

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
        SAV_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = SAV_BACKUPS_DIR / f"{target_sav.stem}-{ts}.sav"
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
