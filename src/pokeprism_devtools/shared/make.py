"""Run a `make` target and stream it — the build plumbing every tree shares.

Nothing here is any one hack's. `rgbds` and `make` are the toolchain of the whole
pokecrystal family, so "run `make -j<n> <target>` and show the lines that matter"
reads the same whether the target is `prism` or `pokecrystal.gbc`. Each hack's
:class:`~..hacks.seam.Plays` decides *which* target and *what* a built ROM then
means; the running of it lands here, once, so a second play adapter does not carry
a second copy of a subprocess loop to drift away from the first.

Deliberately free of the seam's :class:`~..hacks.seam.PlayError`: this layer is
below `hacks/`, so it must not import it. A caller that wants a target validated
or a job count checked does that above, in its own adapter, where the seam's word
is in scope; here a build that fails is just ``False``.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

#: A line of `make` output worth stopping on when a build is run *quiet*. The
#: studio's version of the pipe a person reaches for by hand —
#: `make ... 2>&1 | grep -E ': (error|fatal):|^make: \*\*\*'` — kept here, out of
#: any view, so it can be tested without a compiler.
#:
#: The reason quiet exists at all: a full build is a few thousand lines of
#: `rgbasm`/`rgblink` chatter, and streaming every one of them into a Textual
#: `RichLog` — a widget write, marshalled across a thread boundary, per line — is
#: itself minutes of work the compiler never asked for. The lines that carry the
#: *answer*, though, are a handful: the errors, and the `make: ***` that follows
#: them. Keep those, drop the rest, and the log stays the thing you read when it
#: breaks without being the thing that makes it slow.
_PROBLEM = re.compile(r": (error|fatal|warning):|^make(\[\d+\])?: \*\*\*")


def is_build_problem(line: str) -> bool:
    """Whether this line of build output is one a quiet build still shows."""
    return _PROBLEM.search(line) is not None


def run_make(root: Path, target: str, log: Callable[[str], None], *,
             jobs: int) -> bool:
    """`make -j<jobs> <target>` in `root`, streamed a line at a time through
    `log`. True if `make` exited 0.

    Streamed rather than captured because it takes minutes, and a progress bar
    that cannot fail is worse than the compiler's own output: when the map you
    just added doesn't link, the reason is in these lines, and it names your map.

    `jobs` is trusted to be at least one — the adapter that calls this validates
    it against the seam's vocabulary before we get here, because "fewer than one
    job" is a refusal to explain, not a thing to clamp silently.
    """
    cmd = ["make", f"-j{jobs}", target]
    log(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, cwd=root,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    assert proc.stdout is not None
    with proc.stdout:
        for line in proc.stdout:
            log(line.rstrip("\n"))
    return proc.wait() == 0
