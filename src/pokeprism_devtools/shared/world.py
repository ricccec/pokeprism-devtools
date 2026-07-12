"""What the repo said, the last time anybody looked.

The studio reads the repo once and remembers it — in a `LintContext`, and in a
dozen `@lru_cache`s that live on their functions and therefore for the life of the
process (`shared/caches.py` is the long version). That is right, and it is fast,
and it is why you can hold down an arrow key.

But the repo is not ours alone. You edit a constant in another window, pull a
branch, run `prism-mapfit` — and the studio goes on believing what it read an hour
ago, with total confidence. The danger is not that a dropdown is out of date. It
is that **a write is checked against the wrong repo**: `scaffold.require()` really
does refuse a sprite that does not exist, but it asks a cache, so a sprite that
*stopped* existing sails through and lands in a map as a dangling reference.

The fix is not more validation. Every writer here already validates, with a
did-you-mean and everything. The fix is to notice that the world moved, so that
the validation is aimed at the world as it *is*:

    world = World.stamp(root)      # 60ms, once
    ...
    if world.drift(root):          # 22ms, whenever you like
        # everything we believe is suspect; read it all again

**Why the whole repo rather than the files one mutation depends on.** Because we
measured it. All 4375 hand-authored source files in pokeprism are 7.5 MB, and a
`stat` of every one of them is 22 milliseconds — less than the lint pass the
session already runs after every write. The alternative is for each mutation to
declare the files it rests upon, which is a list a human maintains, and a list a
human maintains is a list somebody forgets to add the seventh entry to. The
failure would be silent and it would be stale data, which is the failure you
notice last and trust the most. So: watch everything, and stop having the
conversation.

**What is watched, and what is not.** The hand-authored source, and not the
build's output. `make` writes *into* the source tree — `*.2bpp`, `*.lz`,
`tilesets/*_collision.bin` are all generated, all gitignored, and some of them are
read by the tile renderer. Including them would mean every build reported five
thousand changed files. Leaving them out is also *correct* rather than merely
convenient: a build artefact is a function of the source we do watch, and the
worst it can do is make the picture on the grid stale. It can never make a write
wrong.

**Why content and not mtime.** `git checkout` rewrites a file's mtime whether or
not its bytes changed; so does saving in an editor without editing. Drift that
fires on a no-op change is drift you learn to ignore. So the mtime is a *hint*
that says which files are worth hashing, and the hash is what decides.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

#: The extensions a human writes by hand and a reader here parses for meaning.
#: `.link` is `contents/romx.link`, which pins each map's sections to a bank.
SOURCE = (".asm", ".inc", ".blk", ".ablk", ".pal", ".link")

#: Directories that are never source, whatever is in them. `build/` and
#: `.devtools/` are outputs; `.git` is a database and walking it costs more than
#: everything else here put together.
SKIP = frozenset({".git", "build", ".devtools", "__pycache__", "node_modules"})


def _hash(path: Path) -> bytes:
    """Short and fast. This is a change detector, not a signature — nobody is
    trying to forge a map file past us, and 16 bytes over 4375 files collide with
    probability that rounds to never."""
    return hashlib.blake2b(path.read_bytes(), digest_size=16).digest()


@dataclass(frozen=True)
class World:
    """Every hand-authored source file, and what was in it when we looked."""

    #: repo-relative path -> (mtime_ns, size). The cheap half: what a `stat` says.
    stamps: dict[str, tuple[int, int]]
    #: repo-relative path -> hash of the bytes. The half that decides.
    hashes: dict[str, bytes]

    @classmethod
    def stamp(cls, root: Path) -> World:
        """Read the lot. ~60ms on pokeprism, at startup and at every refresh.

        Hashing everything up front is what buys the cheap check later: to know a
        file's *contents* changed you have to know what they were.
        """
        stamps: dict[str, tuple[int, int]] = {}
        hashes: dict[str, bytes] = {}
        for rel, st in _walk(root):
            stamps[rel] = (st.st_mtime_ns, st.st_size)
            hashes[rel] = _hash(root / rel)
        return cls(stamps, hashes)

    def drift(self, root: Path) -> list[str]:
        """Which files have really changed since we looked. ~22ms.

        Stats everything and hashes only the handful whose `(mtime_ns, size)`
        moved — so a `git checkout` that puts back the same bytes is not drift,
        and neither is a save-with-no-edit, and the common answer costs one stat
        per file and nothing else.

        A file that appeared and a file that vanished are both drift: a new map's
        `.blk` is as much a change to the world as an edited constant.
        """
        moved: list[str] = []
        seen: set[str] = set()

        for rel, st in _walk(root):
            seen.add(rel)
            was = self.stamps.get(rel)
            if was is None:                       # new file
                moved.append(rel)
            elif was != (st.st_mtime_ns, st.st_size):
                # The stat moved. That is a suspicion, not a verdict.
                if _hash(root / rel) != self.hashes.get(rel):
                    moved.append(rel)

        moved.extend(rel for rel in self.stamps if rel not in seen)   # deleted
        return sorted(moved)

    def restamp(self, root: Path, paths: Iterable[str]) -> World:
        """The same world, with these files as they now are.

        For our *own* writes. The session applies an edit, and the file it wrote
        would otherwise be reported as drift by the very next sweep — which would
        be true, and useless, and would mean the studio spent its life telling you
        that you had just done something.
        """
        stamps, hashes = dict(self.stamps), dict(self.hashes)
        for rel in paths:
            path = root / rel
            if not path.exists():                 # an undo deleted it again
                stamps.pop(rel, None)
                hashes.pop(rel, None)
                continue
            st = path.stat()
            stamps[rel] = (st.st_mtime_ns, st.st_size)
            hashes[rel] = _hash(path)
        return World(stamps, hashes)


def _walk(root: Path) -> Iterable[tuple[str, os.stat_result]]:
    """Every source file under `root`, repo-relative, with its stat.

    `os.walk` with the skip list pruned *in place* — that pruning is most of the
    speed, because `.git` alone holds more files than the whole of the rest.
    """
    root_str = str(root)
    for dirpath, dirnames, filenames in os.walk(root_str):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for name in filenames:
            if not name.endswith(SOURCE):
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                # Vanished between the listing and the stat — a build, a git
                # operation. The next sweep will see it as deleted, which it is.
                continue
            yield os.path.relpath(full, root_str), st
