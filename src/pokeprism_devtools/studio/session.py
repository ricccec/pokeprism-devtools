"""The studio's model. No Textual in here — the TUI is a view over this.

**The view reads no files.** Every byte the studio shows comes out of
:meth:`Session.load`, which hands back plain data: block ids, resolved colours,
where the markers go, and the tables already reduced to columns and rows. The TUI
opens nothing and parses nothing — it draws what it is given. That is what keeps
the knowledge of what a `person_event` is (and of the `+4` its macro adds behind
your back) on this side of the line, where exactly one module has to be right
about it. `docs/adapter-plan.md` is the longer version of why that line is where
it is.

Everything the app does to the repo goes through :meth:`Session.apply`, one action
at a time. That is not an accident of implementation, it is the whole design, and
`shared/edits.py` explains why: an :class:`Edit` carries the entire file text plus
the `base` it was derived from, so two edits built against the same starting file
and applied in sequence do **not** merge — the second overwrites the first, and
the first silently never happened. Stage two NPCs before saving and the flag
allocator hands both the same ``const skip`` slot, because when the second one
looked, the first hadn't been written yet.

So: **build → preview → apply → build the next.** Three things fall out of it.

*Failure is free.* Every scaffold builds its complete set of edits before
anything is written, so an action that raises leaves the tree byte-identical.
There is no half-applied state to recover from and no sandbox tree to recover it
in.

*The preview is exact.* It is not a simulation — it is the very edits that will
land, diffed against the very text they were computed from.

*Undo is honest.* Each edit already records the text it replaced, so undo is that
text, written back. It refuses if the file has moved since, because a file that
changed under us is one whose old contents we have no business restoring.
"""

from __future__ import annotations

from pathlib import Path

from functools import cached_property

from .. import maplint
from ..maplint.context import LintContext
from ..maplint.diagnostics import Diagnostic
from ..shared import (blocksrc, consts, coords, dialogue, eventheader, spritesets,
                      swatches, textbox, trainerparty, wilddata)
from ..shared.edits import StaleEdit, apply_edits
from ..wiring import connections, scaffold
from . import actions, newmap, panels
from .actions import Action
# The shapes of the answers — see `model.py`. Re-exported, because whatever wants
# a `MapData` wants it *from the session*: the session is the only thing that can
# hand it one, and the split between the two files is a size, not a boundary.
from .model import (Applied, MapData, MapGeometry, MapRef, Measured, Preview,
                    TextPreview, TextRef)

__all__ = ["Applied", "MapData", "MapGeometry", "MapRef", "Measured", "Preview",
           "Session", "SessionError", "TextPreview", "TextRef"]


class SessionError(RuntimeError):
    pass


class Session:
    """One repo, open for editing."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.ctx = LintContext(root)
        self.history: list[Applied] = []
        self._found: list[Diagnostic] | None = None

    # -- maps ---------------------------------------------------------------- #
    @property
    def maps(self) -> list[MapRef]:
        """Every wired map, by label. Includes the few that don't parse — they
        still have a grid and a name, and hiding them is how you fail to notice
        that a map is broken."""
        return sorted(
            (MapRef(const, label) for label, const in self.ctx.label_to_const.items()),
            key=lambda m: m.label,
        )

    def parses(self, const: str) -> bool:
        return self.ctx.header(const) is not None

    def load(self, label: str) -> MapData:
        """Everything about one map, from source. Slow enough to want a thread —
        four files — so it takes no locks and touches no state.

        A map whose event header doesn't parse still comes back **with its
        geometry**, and the parse error in `tables["error"]`. Hiding a broken map
        from the person looking for the break is the worst thing this could do.
        """
        root = self.root
        const = self.ctx.label_to_const.get(label, label)
        tables: dict[str, panels.Table] = {}

        header = None
        try:
            header = eventheader.parse_map(root / f"maps/{label}.asm")
        except (eventheader.UnparseableHeader, FileNotFoundError) as exc:
            tables["error"] = ([str(exc)], [])

        try:
            bd = blocksrc.load(root, label)
        except blocksrc.BlockSourceError as exc:
            return MapData(label, const, None, str(exc), tables)

        geometry = MapGeometry(
            label=label, blocks=bd.blocks, height=bd.height, width=bd.width,
            swatches=swatches.for_map(root, bd.tileset_id, bd.permission),
            marks=coords.markers(header) if header else {},
        )

        if header is not None:
            tables["Objects"] = panels.objects(header)
            tables["Warps"] = panels.warps(header)
            tables["Signposts"] = panels.bg_events(header)
            tables["Triggers"] = panels.coord_events(header)
        tables["Connections"] = panels.connections(
            self.ctx.connections_by_map.get(const, []))
        tables["Wild"] = panels.wild(self._wild(const))

        return MapData(label, const, geometry, None, tables)

    def _wild(self, const: str) -> dict[str, wilddata.WildBlock]:
        """The map's encounters. A map with none is the common case, not an error
        — most maps are indoors."""
        found: dict[str, wilddata.WildBlock] = {}
        for kind in (wilddata.GRASS, wilddata.WATER):
            try:
                table = wilddata.table_for(self.root, const, kind)
            except wilddata.WildDataError:
                continue
            for block in table.blocks:
                if block.map_const == const:
                    found[kind] = block
        return found

    def sketch(self, action: Action) -> MapGeometry | None:
        """A picture of what an action would put on the grid, before it exists.

        Only the new-map action has anything to show — see :meth:`Action.sketch`.
        The form calls this on every keystroke and either draws the result or
        prints why it can't, which is how a `.blk` of the wrong size stops being
        an arithmetic complaint and becomes a map of the wrong shape.

        Raises :class:`~.actions.ActionError` for a form that isn't ready yet.
        That is the normal state of a form you are typing into, not a failure.
        """
        bd = action.sketch(self.root)
        if bd is None:
            return None
        return MapGeometry(
            label=bd.name, blocks=bd.blocks, height=bd.height, width=bd.width,
            swatches=swatches.for_map(self.root, bd.tileset_id, bd.permission),
            marks={},                    # nothing stands on it yet
        )

    # -- what a form may offer ------------------------------------------------ #
    def choices(self, kind: str) -> list[str]:
        """The constants a field of this kind will accept.

        The form calls this and turns the answer into autocomplete. It is the
        other half of "the view reads no files": a field says *what sort* of
        thing it wants, and the model — which knows where sprite constants live
        and that a trainer class with a NULL group cannot be battled — says which
        ones exist. An unknown kind is empty, i.e. free text, not an error: a new
        action with a new kind should degrade to a plain box, not crash the form.
        """
        return list(self._choices.get(kind, ()))

    @cached_property
    def _choices(self) -> dict[str, tuple[str, ...]]:
        root = self.root
        backed = [cls for cls, group in trainerparty.class_groups(root).items() if group]
        return {
            actions.MAPS: tuple(m.const for m in self.maps),
            actions.SPRITES: tuple(sorted(spritesets.sprite_ids(root))),
            actions.MOVEMENTS: tuple(sorted(spritesets.movedata_ids(root))),
            actions.PALETTES: tuple(sorted(
                consts.with_prefix(root, consts.SPRITES, "PAL_OW_"))),
            actions.ITEMS: tuple(sorted(consts.names(root, consts.ITEMS))),
            # Only classes with a party group behind them: offering a class the
            # engine will crash on is worse than offering nothing.
            actions.CLASSES: tuple(sorted(backed)),
            actions.DIRECTIONS: tuple(sorted(connections.OPPOSITE)),
            actions.FACINGS: tuple(f.removeprefix("SIGNPOST_").lower()
                                   for f in scaffold.FACINGS),
            # The map header's enums, from the same table the new-map action
            # checks them against — so the form cannot suggest a constant that
            # the action would then refuse.
            actions.PERMISSIONS: newmap.PERMS,
            **{kind: tuple(sorted(consts.with_prefix(root, rel, prefix)))
               for kind, (rel, prefix) in (
                   (actions.TILESETS, newmap.ENUMS["tileset"]),
                   (actions.LANDMARKS, newmap.ENUMS["landmark"]),
                   (actions.MUSIC, newmap.ENUMS["music"]),
                   (actions.TIMES, newmap.ENUMS["palette"]),
                   (actions.FISHGROUPS, newmap.ENUMS["fishgroup"]),
               )},
        }

    # -- text already in the game --------------------------------------------- #
    def texts(self, label: str) -> list[TextRef]:
        """Every text block in one map, as prose you could hand to a person.

        The macros are deliberately not here. `plain` shows the words; `reword`
        puts the macros back from the block itself, positionally — so a `cont`
        that scrolls the box is still a `cont` after you fix a typo in it.
        """
        path = self.root / f"maps/{label}.asm"
        sign = self._boxes["sign"]
        return [
            TextRef(label=b.label, owner=b.owner, lineno=b.lineno,
                    prose=dialogue.plain(b),
                    box="sign" if b.box.name == sign.name else "speech")
            for b in dialogue.parse(self.root, path)
        ]

    # -- text, as it will look ------------------------------------------------ #
    def measure(self, text: str, box: str = "speech") -> TextPreview:
        """Dialogue-in-progress against the box it lands in.

        Same prose model the form submits: one line per screen line, a blank line
        starts a new box. Only *width* is checked, and that is not a shortcut —
        the third row of a box and every row after it are `cont`, which scrolls,
        so a speech can be any length. What it cannot be is wide.
        """
        b = self._boxes[box]
        lines = [self._measure_line(line, b.cols)
                 for line in text.replace("\r\n", "\n").split("\n")]
        return TextPreview(b.name, b.cols, lines)

    def _measure_line(self, line: str, cols: int) -> Measured:
        det, bnd, unb, unknown = self.ctx.textbox_metrics.tiles(self.root, line)
        return Measured(
            text=line, tiles=det, bounded=bnd, unbounded=unb, unknown=unknown,
            over=max(0, det - cols),
            over_at_worst=max(0, det + bnd - cols),
        )

    @cached_property
    def _boxes(self) -> dict[str, textbox.Box]:
        return textbox.boxes(self.root)

    # -- diagnostics --------------------------------------------------------- #
    def lint(self) -> list[Diagnostic]:
        """Every finding in the repo. Cached until something is written.

        Deliberately the whole repo, not the selected map: `only=` filters the
        output rather than scoping the work, and a warm pass is 64ms anyway.
        Linting everything also means a change here shows up in the map it breaks
        *over there* — which is the entire reason a cross-file linter exists.
        """
        if self._found is None:
            self._found = maplint.run(self.ctx)
        return self._found

    def diagnostics(self, const: str) -> list[Diagnostic]:
        """The findings *about* one map — those in its file, plus those in the
        shared second_map_headers.asm that name it, since a map's connections
        live there rather than in the map."""
        return [d for d in self.lint() if maplint.mentions(d, self.ctx, const)]

    # -- changing things ----------------------------------------------------- #
    def preview(self, action: Action) -> Preview:
        """Build the edits without writing them. Raises ActionError if the action
        can't be built at all — which is a clean no-op, not a partial failure."""
        return Preview(action, action.run(self.root))

    def apply(self, preview: Preview) -> Applied:
        """Write the previewed edits, then bring the linter back in step.

        Applies exactly the edits that were shown. `apply_edits` refuses any whose
        file has changed since they were computed, so a stale preview raises
        rather than quietly discarding somebody else's work.
        """
        changed = [e for e in preview.edits if e.changed and (e.new_text or e.binary)]
        if not changed:
            raise SessionError(f"{preview.summary}: nothing to change")

        applied = Applied(preview.summary, [e.path for e in changed],
                          notes=list(preview.notes),
                          select=preview.action.selects())
        for e in changed:
            path = self.root / e.path
            applied.undo_to[e.path] = _read(path, e.binary)
            applied.wrote[e.path] = e.data if e.binary else e.new_text  # type: ignore[assignment]

        try:
            apply_edits(self.root, changed, dry_run=False)
        except StaleEdit as exc:
            raise SessionError(str(exc)) from exc

        self._invalidate(applied.paths)
        self.history.append(applied)
        return applied

    def act(self, action: Action) -> Applied:
        """preview + apply, for callers that don't want to look first."""
        return self.apply(self.preview(action))

    # -- taking it back ------------------------------------------------------- #
    @property
    def can_undo(self) -> bool:
        return bool(self.history)

    def undo(self) -> Applied:
        """Put back what the last action replaced.

        Refuses if any file it would restore no longer holds what we wrote. That
        means somebody edited it in the meantime — in their editor, in another
        tool — and restoring our idea of "before" would throw their work away.
        """
        if not self.history:
            raise SessionError("nothing to undo")
        last = self.history[-1]

        for rel, written in last.wrote.items():
            path = self.root / rel
            if _read(path, isinstance(written, bytes)) != written:
                raise SessionError(
                    f"{rel} has changed since '{last.summary}' was applied, so "
                    f"undoing it would discard whatever changed it. Left alone."
                )

        for rel, before in last.undo_to.items():
            path = self.root / rel
            if before is None:
                path.unlink(missing_ok=True)
            elif isinstance(before, bytes):
                path.write_bytes(before)
            else:
                path.write_text(before)

        self.history.pop()
        self._invalidate(last.paths)
        return last

    # -- keeping the linter honest -------------------------------------------- #
    def _invalidate(self, paths: list[str]) -> None:
        self.ctx.invalidate(paths)
        self._found = None
        # A new map is a new entry in every list of maps, including the one the
        # forms autocomplete from.
        self.__dict__.pop("_choices", None)


def _read(path: Path, binary: bool) -> str | bytes | None:
    """What is in a file, in the units the edit that wrote it speaks. None if it
    isn't there — which is a state undo has to be able to restore."""
    if not path.exists():
        return None
    return path.read_bytes() if binary else path.read_text()
