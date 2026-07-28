"""The few answers the studio remembers about a tree from one run to the next.

Kept in the tree, not in the studio, because that is what the answers are *about*.
Which ROM you build is a fact about your pokecrystal checkout, and it stays true
across every studio you point at it; a single file in the tool's own config would
have to key it by path anyway, and would then be wrong the moment the checkout
moved. `.devtools/` is already the tools' corner of a hack repo — the map renders,
the lint baseline, the save backups, the new-map specs all live there — so this
goes in beside them.

**A preference is not data.** Nothing the studio shows, writes or refuses depends
on this file: every read here answers with the caller's default when the file is
missing, unreadable, or holds something other than what it should. A corrupt
`studio.json` costs you a prefilled field, and that is the whole of it. That is
why the reader swallows what it swallows — it is not hiding an error, it is
answering a question ("what did you say last time?") whose honest answer is
"nothing" when there is no file to say otherwise.

Writing is the other way round and does *not* swallow: a tree that cannot be
written is a tree that will silently never remember anything, and a field that
quietly refuses to keep what you type is the kind of thing you blame yourself for.
So :func:`save_pref` raises, and the caller — which is on a screen, with somewhere
to put a sentence — says so.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..shared.devtools import make_devtools_dir

#: Where it lives, relative to the hack repo's root.
PREFS = ".devtools/studio.json"

#: The build screen's ROM target — `make`'s argument, and the one the boot then
#: looks for on disk. Named here rather than spelled at the call site so the file
#: has one place that says what its keys are.
BUILD_TARGET = "build.target"


def read_prefs(root: Path) -> dict[str, str]:
    """Everything this tree remembers. `{}` if it remembers nothing, including
    when the file exists and is nonsense — see the module docstring.

    Values that are not strings are dropped rather than returned, because the
    callers are prefilling text fields: a `null` that arrived as a value would
    otherwise reach a widget as the four characters `None`.
    """
    try:
        loaded = json.loads((root / PREFS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {k: v for k, v in loaded.items() if isinstance(v, str)}


def save_pref(root: Path, key: str, value: str) -> None:
    """Remember one answer, leaving the others alone.

    Read-modify-write rather than write-what-we-hold: the studio only ever knows
    about the preferences it happens to use, and a whole-file write would drop a
    key some other screen had put there — including one written by a newer
    version of this tool than the one running.

    Raises `OSError` if the tree will not take it.
    """
    path = make_devtools_dir(root) / Path(PREFS).name
    path.write_text(json.dumps(read_prefs(root) | {key: value},
                               indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
