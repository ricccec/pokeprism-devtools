"""Prism's write adapter: the studio's write questions, answered for prism.

This is the write half of the adapter whose read half is :mod:`.read` — the
object `hacks.mount` hands `Session` as ``Hack.writes``. The machinery it
fronts already existed and already lived on the prism side of every argument
(`wiring/`, `studio/content`, `studio/edits`, `studio/offers` — each one full
of prism macros and prism constants); what this module adds is the *door*: one
object, constructed only by the mount, through which the session asks every
question about changing the tree. A hack that answers differently ships a
different object, and the session never learns which one it is holding.

The protocol (see `hacks/mount.py` for the whole seam):

    adders(kind) -> (Action subclasses,)     the tab-foot "Add new…" row
    form(name) -> Action subclass | None     "newmap" | "resize" | "reword"
    editor(label, const, ref, said) -> (Action subclass, values, boxes)
    deletion(label, const, ref) -> Action    what `d` would run
    choices(kind, map_consts, values) -> [str]
    follows(action, changed, values) -> {field: value}
    sprite_hint(map_const, sprite) -> str
    warm() / forget()                        the constants caches

A refusal is a :class:`~..mount.Refused` carrying the reason — the session
turns it into its own error, the form shows the sentence. Everything here
raises that rather than a studio exception, because an adapter that imported
the session to refuse it would have the dependency pointing the wrong way.
"""

from __future__ import annotations

from pathlib import Path

from ..mount import Refused
from . import eventheader, spritepack, trainerstats


def _entry_of(header: eventheader.EventHeader, label: str,
              ref) -> eventheader.Entry:
    entry = header.entry_at(ref.handle) if ref.handle else None
    if entry is None:
        raise Refused(
            f"{label} no longer has a {ref.what} at {ref.handle} — the "
            f"map changed under the table. Select it again.")
    return entry


class Writer:
    """One prism tree, open for writing. `ctx` is the linter's context, which
    doubles as the write path's model of the repo — `sprite_hint` reads sprite
    sets and outdoor groups off it rather than parsing them again."""

    def __init__(self, root: Path, ctx) -> None:
        self.root = root
        self.ctx = ctx

    # -- what a form may offer ------------------------------------------------ #
    def adders(self, kind: str) -> tuple:
        from ...studio import edits
        return edits.ADDERS.get(kind, ())

    def form(self, name: str):
        """The app-level forms — the ones not reached by pointing at a row.
        `newmap` is `a`, `resize` is `s`, `reword` is picking a text under `t`.
        None for a name this adapter does not write, which the view renders as
        the key not existing."""
        from ...studio.content import EditText
        from ...studio.newmap import NewMap
        from ...studio.resize import ResizeMap
        return {"newmap": NewMap, "resize": ResizeMap, "reword": EditText}.get(name)

    def choices(self, kind: str, map_consts: tuple[str, ...],
                values: dict[str, str] | None = None) -> list[str]:
        from ...studio import offers
        return offers.for_kind(self.root, kind, map_consts, values)

    def follows(self, action, changed: str,
                values: dict[str, str]) -> dict[str, str]:
        from ...studio import offers
        return offers.follows(self.root, action, changed, values)

    def sprite_hint(self, map_const: str, sprite: str) -> str:
        """The sprite field's hint line: who plays this sprite, and whether they
        can walk here.

        *Who* is counted from every trainer already in the repo, the same way
        `follows` is — see :func:`.trainerstats.classes_for`. A class does not
        say what it wears; only counting what is already there does.

        *Whether they can walk* is measured the way `maplint.rules_sprites`
        measures it, not guessed from the sprite's own type: an outdoor map
        only ever loads its group's `OutdoorSprites` set, and only the sprites
        that land inside VRAM table 1 there ever animate a walk cycle — the
        ~9 the docstring in :mod:`.spritepack` explains. Indoor maps load
        whatever their objects ask for, so nothing here bounds them.
        """
        who = trainerstats.classes_for(self.root, sprite)
        text = f"worn by: {', '.join(who[:6])}" if who else "no trainer wears this sprite yet"

        mapdef = self.ctx.map_defs.get(map_const)
        if mapdef is None or not self.ctx.is_outdoor(map_const):
            return text
        sd = self.ctx.sprites
        group = sd.outdoor_set(mapdef.group)
        if sprite not in group:
            name = sd.set_names.get(mapdef.group, "this group")
            return f"{text} — not in {name}, this map's sprite set"
        walkable = spritepack.walkable(sd, [sd.player_sprite(), *group])
        return f"{text} — {'can walk here' if sprite in walkable else 'stands still here (table 2)'}"

    def warm(self) -> None:
        """Read everything a form will want, before a form asks."""
        from ...studio import offers
        offers.warm(self.root)

    def forget(self) -> None:
        """Something was written: the constants a form offers may have grown."""
        from ...studio import offers
        offers.forget()

    # -- what a selected row can do ------------------------------------------- #
    def _header(self, label: str) -> eventheader.EventHeader:
        try:
            return eventheader.parse_map(self.root / f"maps/{label}.asm")
        except (eventheader.UnparseableHeader, FileNotFoundError) as exc:
            raise Refused(str(exc)) from exc

    def editor(self, label: str, const: str, ref,
               said: list) -> tuple[type, dict[str, str], dict[str, str]]:
        """The form `e` would open on this row, filled in with what is there.

        The mirror of :meth:`deletion`, and like it, it refuses by *explaining* —
        an absent key tells you nothing, and the reason is the interesting part.
        """
        from ...studio import edits, prefill as fill
        from ...wiring import objedit
        if (action := edits.EDITORS.get(ref.what)) is None:
            raise Refused(edits.NOT_YET.get(
                ref.what, f"editing a {ref.what} is not wired up yet."))
        try:
            values, boxes = fill.prefill(self.root, label, const, ref, said)
        except (objedit.EditError, FileNotFoundError) as exc:
            raise Refused(str(exc)) from exc
        return action, values, boxes

    def deletion(self, label: str, const: str, ref):
        """The action `d` would run on this row.

        Raises :class:`~..mount.Refused` for the things that cannot be deleted,
        and says *why* — which beats an absent key, because the reason is the
        interesting part.
        """
        from ...studio import content
        if ref.what == "map":
            raise Refused("deleting a whole map is not something this does.")

        # A connection is not an entry in an event list, so it carries no handle
        # — it is named by its direction, because a map has at most one each way.
        if ref.what == "warp":
            return content.RemoveWarp(const, index=str(ref.handle.index))
        if ref.what == "connection":
            return content.Disconnect(const, direction=ref.key)

        # `entry` is not how the object is found — the handle is, and it came off
        # the row. It is read to *name* the thing on the confirm screen, and
        # re-read from the file rather than remembered, so a Ref that has gone
        # stale says so instead of describing whatever is standing in its place.
        #
        # This is the difference between a description and an identity. Owsauri's
        # game corner runs sixteen slot machines off one script and Saffron Gates
        # has eight guards with one name between them; asking `removal` to find
        # "the one called X" would refuse all twenty-four. You did not describe the
        # thing you want gone — you pointed at it.
        entry = _entry_of(self._header(label), label, ref)
        y, x = entry.coords
        # The handle is spelled out only here, into the form-shaped strings the
        # action takes — the actions are the write half of the same adapter that
        # minted it, so this is the handle going home, not the port reading it.
        return content.Remove(
            const, index=str(ref.handle.index), kind=ref.handle.kind.value,
            label=entry.pointer or "",
            y="" if y is None else str(y), x="" if x is None else str(x))
