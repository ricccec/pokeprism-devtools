"""Rules about trainers seen across the whole repo, not one map at a time.

A trainer class is a costume as much as a party: a `HIKER` is meant to read as a
hiker wherever the player meets one. The engine never enforces that — every
person_event names its own sprite, so nothing stops one `HIKER` from wearing
`SPRITE_HIKER` and the next from wearing `SPRITE_FISHER`. It assembles, it
renders, and the only thing wrong with it is that the same trainer class now
looks like two different people. That is a whole-repo observation — you cannot
see it from inside one map — so the rule counts across every map at once.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from ..shared import trainerstats
from .context import LintContext
from .diagnostics import Diagnostic, Severity


def trainer_sprite_drift(ctx: LintContext) -> list[Diagnostic]:
    """A trainer class drawn with more than one overworld sprite.

    For each class, the sprite it wears most often is taken as the one it is
    *meant* to wear, and every trainer wearing a different one is flagged where
    it stands. INFO, not a defect: the game looks fine, and the odd one out is
    sometimes deliberate — a plot NPC disguised as a grunt, say — which is what
    the per-line ``ignore[trainer-sprite]`` is for.
    """
    worn: dict[str, list[trainerstats.Appearance]] = defaultdict(list)
    for a in trainerstats.appearances(ctx.root):
        worn[a.cls].append(a)

    out = []
    for cls, seen in worn.items():
        tally = Counter(a.sprite for a in seen)
        if len(tally) < 2:
            continue                       # one sprite everywhere — nothing to say
        usual, usual_n = tally.most_common(1)[0]
        for a in seen:
            if a.sprite == usual:
                continue
            out.append(Diagnostic(
                "trainer-sprite", Severity.INFO, f"maps/{a.map}.asm", a.line,
                f"{cls} is drawn as {a.sprite} here, but wears {usual} in "
                f"{usual_n} of its {len(seen)} appearances across the repo — a "
                f"trainer class usually keeps one overworld sprite",
            ))
    return out


ALL = (trainer_sprite_drift,)
