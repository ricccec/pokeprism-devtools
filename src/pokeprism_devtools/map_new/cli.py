"""The `prism-newmap` command line."""

from __future__ import annotations

import sys

from ..mapfit import mapwire
from ..shared.devtools import make_devtools_dir
from ..shared.paths import RepoNotFound, repo_root
from .template import place_blk, write_template
from .wizard import _Aborted, _gather_spec


_BANNER_WIDTH = 56


def _import_questionary():
    """The prompt library, or an exit telling the user how to get it.

    It is imported here rather than at module scope so the other five console
    entry points do not depend on it: only this one asks questions.
    """
    try:
        import questionary
    except ImportError:
        print(
            "prism-newmap requires `questionary`. Reinstall pokeprism-devtools:\n"
            "    pipx install --force <path-to-pokeprism-devtools>",
            file=sys.stderr,
        )
        sys.exit(2)
    return questionary


def _print_banner() -> None:
    print()
    print("=" * _BANNER_WIDTH)
    print("  prism-newmap — add a new map")
    print("=" * _BANNER_WIDTH)
    print()


def _write_map_files(root, spec, blk_src) -> None:
    """Create the map's two files, before anything is wired to them."""
    print(f"\nWill create maps/{spec.label}.asm (empty template)")
    print(f"Will copy {blk_src} -> {spec.blk}")
    try:
        write_template(root, spec.label)
        place_blk(root, blk_src, spec.label)
    except (FileExistsError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    problems = spec.validate(root)
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        sys.exit(2)


def _save_spec(root, spec):
    """Write the spec where `prism-mapfit add` will look for it."""
    spec_path = make_devtools_dir(root, "specs") / f"{spec.label}.toml"
    spec_path.write_text(spec.to_toml())
    return spec_path


def _print_next_steps(root, spec, spec_path) -> None:
    rel = spec_path.relative_to(root)
    print(f"\nWired {spec.label} ({spec.const}). Spec saved to {rel}")
    if not spec.connections:
        print("Note: no connections were added — if this map borders another, "
              "add `connection ...` lines to both maps by hand in "
              "maps/second_map_headers.asm.")
    print(f"\nNext: prism-mapfit add --spec {rel}  "
          "(add --park for a still-growing map)")


def main() -> None:
    questionary = _import_questionary()

    try:
        root = repo_root()
    except RepoNotFound as e:
        print(f"prism-newmap: {e}", file=sys.stderr)
        sys.exit(2)

    _print_banner()

    try:
        spec, blk_src = _gather_spec(root, questionary)
    except _Aborted:
        print("\nAborted — no files written.")
        sys.exit(1)

    _write_map_files(root, spec, blk_src)

    edits = [editor(root, spec) for editor in mapwire.ALL_ASM_EDITORS]
    print("\nWiring edits:")
    for e in edits:
        print(f"  [{'edit' if e.changed else 'skip'}] {e.path}: {e.detail}")

    if not questionary.confirm("\nWrite these changes?", default=True).ask():
        print(f"Aborted — {spec.script_asm} and {spec.blk} were already "
              "written; the five source files were not touched.")
        sys.exit(1)

    mapwire.apply_edits(root, edits, dry_run=False)
    _print_next_steps(root, spec, _save_spec(root, spec))
