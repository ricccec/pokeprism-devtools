"""Create the tools' `.devtools/` corner, and hide it from the tree that owns it.

Every tool here writes into `<hack>/.devtools/` — the map renders, the lint
baseline, the new-map specs, the save backups, the studio's remembered target.
Prism's own `.gitignore` lists `.devtools/`, but the two family trees the studio
also drives — `pokecrystal` and `polishedcrystal` — track upstream, and a line
added to a `.gitignore` we do not own is a permanent local diff that conflicts on
every rebase. Left to themselves those trees report `?? .devtools/` forever.

The fix is to make the directory hide itself. :func:`make_devtools_dir` writes a
`.devtools/.gitignore` holding a single `*` the moment the directory is created.
`*` ignores every file under `.devtools/` *and the `.gitignore` itself* (ask
`git check-ignore` and it names line 1 as the rule that hides the file), so the
whole directory leaves `git status` with nothing tracked and nothing to commit —
in any tree, whether or not its own `.gitignore` knows about us.

Route every `.devtools/`-creating `mkdir` through here so the ignore and the
directory can never drift apart: one code path makes both.
"""

from __future__ import annotations

from pathlib import Path


def make_devtools_dir(root: Path, *sub: str) -> Path:
    """Ensure `<root>/.devtools/<sub...>` exists and hides itself; return it.

    Creates `.devtools/` (and any `sub` beneath it) if absent, and seeds
    `.devtools/.gitignore` with `*` the first time it does — never overwriting an
    existing one, which a person may have edited (to un-ignore
    `.devtools/presets/`, say). Call with no `sub` for the `.devtools/` root
    itself, e.g. to write a file straight into it.
    """
    devtools = root / ".devtools"
    devtools.mkdir(parents=True, exist_ok=True)
    ignore = devtools / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n")
    target = devtools.joinpath(*sub)
    target.mkdir(parents=True, exist_ok=True)
    return target
