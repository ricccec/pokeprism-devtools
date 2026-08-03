"""The `prism-newmap` command line."""

from __future__ import annotations

import sys

from ..mapfit import mapwire
from ..shared.devtools import make_devtools_dir
from ..shared.paths import RepoNotFound, repo_root
from .template import place_blk, write_template
from .wizard import _Aborted, _gather_spec


def main() -> None:
    try:
        import questionary
    except ImportError:
        print(
            "prism-newmap requires `questionary`. Reinstall pokeprism-devtools:\n"
            "    pipx install --force <path-to-pokeprism-devtools>",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        root = repo_root()
    except RepoNotFound as e:
        print(f"prism-newmap: {e}", file=sys.stderr)
        sys.exit(2)

    print()
    print("=" * 56)
    print("  prism-newmap — add a new map")
    print("=" * 56)
    print()

    try:
        spec, blk_src = _gather_spec(root, questionary)
    except _Aborted:
        print("\nAborted — no files written.")
        sys.exit(1)

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

    edits = [editor(root, spec) for editor in mapwire.ALL_ASM_EDITORS]
    print("\nWiring edits:")
    for e in edits:
        print(f"  [{'edit' if e.changed else 'skip'}] {e.path}: {e.detail}")

    if not questionary.confirm("\nWrite these changes?", default=True).ask():
        print(f"Aborted — {spec.script_asm} and {spec.blk} were already "
              "written; the five source files were not touched.")
        sys.exit(1)

    mapwire.apply_edits(root, edits, dry_run=False)

    spec_dir = make_devtools_dir(root, "specs")
    spec_path = spec_dir / f"{spec.label}.toml"
    spec_path.write_text(spec.to_toml())

    print(f"\nWired {spec.label} ({spec.const}). Spec saved to "
          f"{spec_path.relative_to(root)}")
    if not spec.connections:
        print("Note: no connections were added — if this map borders another, "
              "add `connection ...` lines to both maps by hand in "
              "maps/second_map_headers.asm.")
    print(f"\nNext: prism-mapfit add --spec {spec_path.relative_to(root)}  "
          "(add --park for a still-growing map)")
