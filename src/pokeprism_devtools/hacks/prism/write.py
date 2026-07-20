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

from ...wiring import warpdel
from ...wiring.warpdel import DeadDoor, WarpGrammar, WarpMacro
from ..mount import Refused
from . import eventheader, mapsource, spritepack, trainerstats

#: How prism spells a warp reference. Two macros and no more: nothing else in
#: `macros/` takes a warp id and `data/` does not mention warps at all, so a scan
#: of these two is exhaustive — a claim that holds for prism and, as the family
#: adapter's own record records, for nobody else.
#:
#: `dummy_warp y, x` emits `db -1, 0, 0`, and it is tempting to read that as
#: "group 0, map 0, nowhere". It is not: `CopyWarpData` (home/map.asm:172) sees
#: the -1 and takes the warp, the group *and* the map from `wBackupWarpNumber`,
#: so those two zeroes are never read. A dead door lands on stale state rather
#: than nowhere — see :class:`~...wiring.warpdel.DeadDoor`. The spelling is kept
#: because it is what prism ships and what its maps already contain; the
#: family's `warp_event x, y, NONE, -1` assembles to the very same bytes.
WARPS = WarpGrammar(
    macros=(WarpMacro("warp_def", at=2, at_map=3, door=True),
            WarpMacro("warpmod", at=0, at_map=1)),
    dead_door=DeadDoor("dummy_warp", keeps=(0, 1)),
)


def delete_warp(root: Path, map_const: str, index: int) -> warpdel.Deletion:
    """Take warp #(index+1) out of `map_const`, and fix the whole repo behind it.

    The half that is prism's — find the map file, parse its event header, count
    its warps, splice the entry out — and then :mod:`..wiring.warpdel` with
    prism's :data:`WARPS` grammar for the half that is every tree's. The family
    adapter has the mirror of this function over its own parser, which is the
    whole point of the grammar being data.
    """
    label = {c: l for l, c in mapsource.header_pairs(root)}.get(map_const)
    if label is None:
        raise warpdel.WarpDelError(f"{map_const} is not a wired map")

    path = root / "maps" / f"{label}.asm"
    try:
        header = eventheader.parse_map(path)
    except (eventheader.UnparseableHeader, FileNotFoundError) as exc:
        raise warpdel.WarpDelError(
            f"{map_const}'s event header can't be read, so its warps can't be "
            f"counted: {exc}") from exc

    warps = header.warps
    if not 0 <= index < len(warps):
        raise warpdel.WarpDelError(
            f"{map_const} has {len(warps)} warp{'s' if len(warps) != 1 else ''}, "
            f"so there is no warp #{index + 1} to delete")

    y, x = warps[index].coords
    header.remove_entry(eventheader.ListKind.WARPS, index)
    return warpdel.delete_warp(root, map_const, index, WARPS,
                               own_rel=f"maps/{label}.asm",
                               spliced=header.to_text(), where=f"({y}, {x})")


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
        from ...studio.resize import resize_for
        from .resize import DIALECT
        return {"newmap": NewMap, "resize": resize_for(DIALECT, "Prism"),
                "reword": EditText}.get(name)

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
