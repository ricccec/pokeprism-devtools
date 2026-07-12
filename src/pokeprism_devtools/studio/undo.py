"""Taking a change back, and knowing when you can't.

Split out of `session.py` on size, but it earns its own file: undo is the one part
of the studio whose correctness is not visible from its own code. Everything else
either works or throws. An undo that is subtly wrong *puts a file back*, and the
file it puts back is plausible.

Two rules, and the second is the one people get wrong.

**Undone whole, or not at all.** Every file a mutation wrote is checked against
exactly what we wrote there, and the checking loop finishes before the restoring
loop begins. So a mutation that wrote `A.asm` and `B.asm`, with `B.asm` since edited
by hand, leaves `A.asm` alone too. One file that moved guards the whole change,
because half a paired warp is worse than either warp.

**Content, never order.** An undo is legal if the bytes are still ours — not if
nothing has happened since. That is why the studio needs no "checkpoint" in its
history, and why pressing `r` cannot invalidate an undo: a mutation whose file you
have since edited by hand refuses of its own accord, and says which file and why.
Ordering rules would have been an approximation of this, and a worse one.
"""

from __future__ import annotations

from pathlib import Path

from .model import Applied, Mutation


def read(path: Path, binary: bool) -> str | bytes | None:
    """What is in a file, in the units the edit that wrote it speaks. None if it
    isn't there — which is a state an undo has to be able to restore."""
    if not path.exists():
        return None
    return path.read_bytes() if binary else path.read_text()


def mutations(root: Path, history: list[Applied]) -> list[Mutation]:
    """Everything written this session, oldest first, and whether each can still be
    taken back.

    Two things can stop an undo, and both are worth stating rather than greying out
    a button. A **later mutation touched the same file**, so putting this one's text
    back would wipe that one out — the fix is to undo the later one first, and this
    says which. Or the **file has changed since we wrote it**, which means somebody
    else did, in their editor or in another tool, and restoring our idea of "before"
    would throw their work away. Neither is an error. Both are reasons.
    """
    out = []
    for i, applied in enumerate(history):
        later = {p for a in history[i + 1:] for p in a.paths}
        clash = sorted(set(applied.paths) & later)
        moved = [rel for rel, written in applied.wrote.items()
                 if read(root / rel, isinstance(written, bytes)) != written]

        if clash:
            blocked = (f"{clash[0]} was written again by a later change — "
                       f"undo that one first")
        elif moved:
            blocked = (f"{moved[0]} has changed since this was applied, so "
                       f"undoing would discard whatever changed it")
        else:
            blocked = ""

        out.append(Mutation(index=i, summary=applied.summary,
                            files=applied.touched(), notes=applied.notes,
                            blocked=blocked, introduced=applied.introduced))
    return out


def restore(root: Path, applied: Applied) -> None:
    """Put back what one mutation replaced. The caller has already established, via
    :func:`mutations`, that it may."""
    for rel, before in applied.undo_to.items():
        path = root / rel
        if before is None:
            path.unlink(missing_ok=True)
        elif isinstance(before, bytes):
            path.write_bytes(before)
        else:
            path.write_text(before)
