"""Rules about event flags — the bits the save file remembers you by.

All three are built on :mod:`..shared.flagrefs`, which indexes *every* reference
in the repo. That matters more than it sounds. A flag can be named in four
places, and the obvious one is the least common:

    person_event's last argument      406 refs   gates the object's appearance
    trainer macro's first argument     297 refs   set when you beat him
    setevent / checkevent / …          682 refs   scripts
    engine tables, item records         ~200 refs

The rules these replace read only a map's event-header entry lines — so they saw
the first group and nothing else. A trainer's flag is *not* in his person_event
(that argument says -1), and a hidden item's is inside the record its signpost
points at. Both were invisible.
"""

from __future__ import annotations

from ..shared import flagrefs
from .context import LintContext
from .diagnostics import Diagnostic, Severity

#: References that make an object in the world *the* thing a flag records. Two of
#: these on one flag means two objects share one bit of save state.
_OBJECT = ("trainer", "item record", "person_event")


def flag_unknown(ctx: LintContext) -> list[Diagnostic]:
    """Every `EVENT_*` named anywhere must exist in constants/event_flags.asm.

    An undefined symbol usually fails the link — but flags are read through `dw`
    expressions inside macros, where a typo can resolve to a *different* flag, or
    to 0, and assemble perfectly.
    """
    known = ctx.flags.by_name
    out = []
    for flag, refs in sorted(ctx.flag_refs.refs.items()):
        if flag in known:
            continue
        ref = refs[0]
        out.append(Diagnostic(
            "flag-unknown", Severity.ERROR, ref.path, ref.line,
            f"{flag} is not defined in constants/event_flags.asm "
            f"({len(refs)} reference{'s' if len(refs) > 1 else ''})",
        ))
    return out


def flag_unused(ctx: LintContext) -> list[Diagnostic]:
    """A flag that is declared and then never named by anything.

    Harmless — it costs one bit of save state and nothing else — but it is a
    slot that could have gone back to the `const skip` reserve, and more often
    than not it is the residue of content that was deleted while its flag was
    left behind. `prism-maplint` cannot free it for you: flag values are
    save-file bit positions, so it must be rewritten to `const skip` rather than
    removed (see wiring/removal.py).
    """
    out = []
    for flag in ctx.flags.flags:
        if ctx.flag_refs.is_referenced(flag.name):
            continue
        out.append(Diagnostic(
            "flag-unused", Severity.INFO, "constants/event_flags.asm", flag.lineno + 1,
            f"{flag.name} (= {flag.value}) is referenced by nothing in the repo",
        ))
    return out


def flag_multi_owner(ctx: LintContext) -> list[Diagnostic]:
    """Two objects keyed to the same flag — one bit of save state between them.

    The flag on a trainer, an item ball or a hidden item is not a condition; it
    *is* the record of that object having been dealt with. Two objects sharing
    one means dealing with either marks both: beat one twin and the other counts
    as beaten, pick up one Poké Ball and the other vanishes.

    That is sometimes exactly the intent, which is why this is `info` and not an
    error — pokeprism's twins share a flag deliberately, and so do the two PP Ups
    in the contest and non-contest versions of Provincial Park. But it is also
    precisely what a copy-pasted flag looks like, and nothing else in the build
    will ever mention it.
    """
    out = []
    for flag, refs in sorted(ctx.flag_refs.refs.items()):
        owners = [r for r in flagrefs.owners(refs)
                  if r.how.startswith(_OBJECT) and r.path.startswith("maps/")]
        if len(owners) < 2:
            continue

        first, *rest = owners
        where = ", ".join(f"{r.path}:{r.line}" for r in rest)
        scope = ("in the same map" if len({r.path for r in owners}) == 1
                 else "across maps")
        out.append(Diagnostic(
            "flag-multi-owner", Severity.INFO, first.path, first.line,
            f"{flag} is the save-state record for {len(owners)} objects {scope} "
            f"(also {where}) — dealing with one marks them all",
        ))
    return out


def flag_shared(ctx: LintContext) -> list[Diagnostic]:
    """The same appearance flag gating objects in different maps.

    Distinct from `flag-multi-owner`: this is about objects that *read* a flag to
    decide whether to appear, and sharing that is normal — one NPC who follows
    the story between maps, a gym leader who vanishes everywhere at once. It is
    `info` because it is also what a copy-pasted flag looks like.

    (This is the relationship between CastroForest's second Sage and the two
    guards in JaeruGate: beating him is what opens that gate.)
    """
    out = []
    for flag, refs in sorted(ctx.flag_refs.refs.items()):
        gates = [r for r in flagrefs.readers(refs)
                 if r.how.startswith("person_event") and r.path.startswith("maps/")]
        maps_using = {r.path for r in gates}
        if len(maps_using) < 2:
            continue

        first = gates[0]
        others = ", ".join(sorted(maps_using - {first.path}))
        out.append(Diagnostic(
            "flag-shared", Severity.INFO, first.path, first.line,
            f"{flag} also gates objects in {others}",
        ))
    return out


def flag_never_set(ctx: LintContext) -> list[Diagnostic]:
    """An object gated by a flag that nothing in the repo ever sets.

    The gate is not a simple "show if set". engine/objects.asm strips bit 15 of
    the flag word, tests the flag, then XORs the result with that bit — so the
    polarity is part of the flag argument:

        …, EVENT_FOO             the object is visible **until** FOO is set
        …, EVENT_FOO | $8000     the object is invisible **until** FOO is set

    Which makes "nothing sets it" mean two different things, and only one of them
    is loud:

    * inverted, never set — the object **can never appear**. Unreachable content.
    * plain, never set — the object never goes away. The flag does nothing, which
      is usually a story beat that was never wired up.

    Deliberately conservative about what counts as a set: any mention this parser
    can't classify (engine code loading the flag into `de` for EventFlagAction,
    which sets or tests depending on a mode byte) is treated as a possible set.
    Reporting a live NPC as unreachable would be much worse than staying quiet.
    """
    out = []
    known = ctx.flags.by_name          # rebuilt on every access — hoist it
    for flag, refs in sorted(ctx.flag_refs.refs.items()):
        if flag not in known or flagrefs.maybe_set(refs):
            continue

        for ref in refs:
            if not ref.how.startswith("person_event") or ref.role != flagrefs.READER:
                continue
            if not ref.path.startswith("maps/"):
                continue

            if ref.inverted:
                out.append(Diagnostic(
                    "flag-never-set", Severity.WARNING, ref.path, ref.line,
                    f"this object only appears once {flag} is set (the `| $8000` "
                    f"inverts the gate), and nothing in the repo ever sets it — so "
                    f"it can never appear",
                ))
            else:
                out.append(Diagnostic(
                    "flag-never-set", Severity.INFO, ref.path, ref.line,
                    f"this object disappears once {flag} is set, and nothing in the "
                    f"repo ever sets it — so it never disappears and the flag is "
                    f"inert",
                ))
    return out


ALL = (flag_unknown, flag_unused, flag_multi_owner, flag_shared, flag_never_set)
