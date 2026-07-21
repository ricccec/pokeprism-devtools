"""The family's write adapter: what `hacks.mount` hands `Session` as
``Hack.writes`` for a vanilla or polished tree.

The parsing and splicing this stands on lives next door in :mod:`.eventblock`,
and the split is the same one prism makes between `eventheader` and `write`: a
file that knows the shape of a ``def_*`` list, and an adapter that knows what
the studio is allowed to ask of it. What is left here is the seam's own
vocabulary — the records the mount declares (:data:`WARPS`, :data:`CHOICES`,
and polished's forks of both), the :class:`Writer` that answers the protocol in
`hacks/mount.py`'s docstring, and the two deletions it hands back.
"""

from __future__ import annotations

from pathlib import Path

from ...shared.constants import ConstSet, read_set
from ...studio import actions, panels
from ...studio.actions import Action, ActionError, Result
from ...wiring import warpdel
from ...wiring.warpdel import BlindTable, DeadDoor, WarpGrammar, WarpMacro
from ..mount import Refused
from . import newmap
from .eventblock import EventBlock, UnparseableEvents, parse_map

#: How the family spells a warp reference, for :mod:`...wiring.warpdel`. The
#: survey that produced this record is the reason Phase 5 was a port and not a
#: copy: prism's two macros are three here, and neither tree has prism's
#: `dummy_warp`.
#:
#: * ``warp_event x, y, MAP, n`` — the coordinates turn and the seats move, which
#:   is the whole reason the grammar is data.
#: * ``warpmod n, MAP`` — the one macro the family spells exactly as prism does.
#: * ``elevfloor FLOOR, n, MAP`` — an elevator's floor list. Prism has no such
#:   macro; both family trees use it (14 rows in vanilla, 17 in polished), and
#:   missing it would have left every elevator quietly off by one.
#:
#: The dead door took the longest to find, because the family has no
#: `dummy_warp` and the obvious conclusion — that it therefore cannot spell one
#: — is wrong. Both trees ``DEF GROUP_NONE`` and ``DEF MAP_NONE`` to 0, and
#: ``map_id NONE`` emits ``db 0, 0``, so ``warp_event x, y, NONE, -1`` assembles
#: to the very five bytes prism's ``dummy_warp y, x`` does. It is the same door
#: to nowhere, spelled in the family's own declared constants rather than in a
#: macro prism invented — and, as :class:`~...wiring.warpdel.DeadDoor` records,
#: "nowhere" is a weaker promise than either dialect's comments claim.
WARPS = WarpGrammar(
    macros=(WarpMacro("warp_event", at=3, at_map=2, door=True),
            WarpMacro("warpmod", at=0, at_map=1),
            WarpMacro("elevfloor", at=1, at_map=2)),
    dead_door=DeadDoor("warp_event", keeps=(0, 1), extra=("NONE", "-1")),
)

#: Polished's, which forks the macro set as it forks everything else: it adds
#: `digmod` (Dig's exit, two uses), and it keeps hidden-grotto return warps in
#: `data/` as bare numbers whose map is named nowhere on the line — a table this
#: scan cannot see and will not guess at, so it is declared and warned about.
POLISHED_WARPS = WarpGrammar(
    macros=WARPS.macros + (WarpMacro("digmod", at=0, at_map=1),),
    dead_door=WARPS.dead_door,
    blind=(BlindTable(
        "data/events/hidden_grottoes/grottoes.asm",
        "each row's warp belongs to the map its HIDDENGROTTO_* constant is "
        "named after, and a naming convention is not a reference"),),
)

#: What a family form may offer, by the field vocabulary `studio/actions.py`
#: names. The keys are field *kinds*, not answers: naming one here says this
#: dialect can enumerate that sort of thing, and a kind absent from this map
#: answers `[]`, which the form renders as a plain text box.
#:
#: Both trees keep all six in the same six files — the survey checked rather
#: than assumed, since Phase 5's `elevfloor` was exactly this question answered
#: wrong. The event flags are the one set that is a *suggestion* rather than a
#: bound: see `studio/offers.py` on why holding you to the list would mean the
#: only NPCs you could gate are the gated ones.
CHOICES = {
    actions.SPRITES: ConstSet("constants/sprite_constants.asm", "SPRITE_"),
    actions.MOVEMENTS: ConstSet("constants/map_object_constants.asm",
                                "SPRITEMOVEDATA_"),
    #: `PAL_NPC_*`, and the prefix is the whole finding. Prism's objects wear
    #: `PAL_OW_RED`; both family trees define a `PAL_OW_*` set *and never put
    #: one on an object_event* — all 1,466 vanilla and 2,161 polished object
    #: lines name a `PAL_NPC_*`. Offering the `PAL_OW_` set would have been a
    #: palette field that suggested only constants the maps never use.
    actions.PALETTES: ConstSet("constants/sprite_data_constants.asm", "PAL_NPC_"),
    actions.ITEMS: ConstSet("constants/item_constants.asm"),
    actions.FLAGS: ConstSet("constants/event_flags.asm", "EVENT_"),
    #: The family's signpost kinds. Prism calls these `SIGNPOST_*` and the
    #: studio's field is still named `facings` after them; the family says
    #: `BGEVENT_*` and neither tree has ever heard of the other's spelling.
    actions.FACINGS: ConstSet("constants/script_constants.asm", "BGEVENT_"),
    #: The map header's own vocabulary — tileset, landmark, music, palette,
    #: fishing group — lives next door in `.newmap`, which is the thing that
    #: asks for it.
    **newmap.HEADER_SETS,
}

#: Polished's, forking in exactly one entry — and that entry is why `ConstSet`
#: carries a `macro` field at all. Vanilla writes `const PAL_NPC_RED`; polished
#: writes `ow_npc_pal_const RED`, one macro that defines both the `PAL_OW_` and
#: the `PAL_NPC_` name and lets rgbasm paste the prefix on, so neither appears
#: in the source. Reading polished with vanilla's record does not fail loudly —
#: it returns **one** palette, `PAL_NPC_DEFAULT`, the only member written out
#: longhand. A near-empty list is indistinguishable from "this field is free
#: text", so the palette box would have quietly stopped suggesting anything on
#: exactly one tree out of three. Measured, not assumed.
POLISHED_CHOICES = {
    **CHOICES,
    actions.PALETTES: ConstSet("constants/sprite_data_constants.asm", "PAL_NPC_",
                               macro="ow_npc_pal_const"),
    **newmap.POLISHED_HEADER_SETS,
}

# --------------------------------------------------------------------------- #
# the write adapter                                                           #
# --------------------------------------------------------------------------- #

class Writer:
    """The family's write adapter — what `hacks.mount` hands `Session` as
    ``Hack.writes`` for a vanilla or polished tree. Polished mounts this very
    class with its head anchor, the same way its read adapter imports
    vanilla's parsers: the fork relation is real, so the code states it.

    **Deletion is the write that crosses today**, now including warps. Removing
    an entry is the operation the seam's whole identity story was built for — a
    handle resolved by handing it back, the const list kept in step — and for
    everything but a warp its blast radius is a single file. A warp's is the
    repo, and it crosses through :data:`WARPS`: the rule and the scan live in
    `wiring/warpdel`, this dialect's spelling of them is a record, and the one
    thing the dialect cannot do (spell a door to nowhere) is a refusal that
    names the doors rather than a silence.

    **Editing crosses for all four lists, adding for three of them.** An
    editor rewrites one line in place, which moves nothing and renumbers
    nothing, so it is safe wherever the line already parses; an adder appends
    one, which is safe exactly when the line it appends needs no script block
    written beside it. Trainers and props need one, so they have no adder and
    the tab's Add row says nothing rather than producing a map that will not
    assemble. See `.actions` for the slot orders, which fork between the two
    trees in four columns and swap the movement radius between two of them.

    What is left is a declared hole rather than a capability the session could
    misread: of the three app-level forms `form()` answers only `resize` — new
    map is unwritten and rewording is the text project — and `follows` and
    `sprite_hint` are argued absences, not stubs. The protocol is
    `hacks/mount.py`'s docstring.
    """

    def __init__(self, root: Path, anchor: str = "_MapEvents",
                 grammar: WarpGrammar = WARPS,
                 set_of: dict[str, ConstSet] | None = None,
                 forms: tuple[dict, dict] | None = None,
                 resize=None, adds=None) -> None:
        self.root = root
        self.anchor = anchor
        #: The fifth fork: how this tree answers a resize. Declared and not
        #: derived from the anchor, because the anchor says where a map file
        #: opens and says nothing about how its blocks are indexed — and the
        #: two trees spell that label differently. See `.resize`.
        self._resize = resize
        #: The sixth fork: how this tree adds a map. Separate from `_resize`
        #: even though both are "how this tree handles a map's shape", because
        #: they diverge on the question that matters — a resized map keeps the
        #: section it is already in, and a new one has to be put somewhere.
        self._newmap = adds
        #: The fourth fork the mount declares: which dialect's actions these
        #: are, already stamped with its anchor and its `object_event` slot
        #: order. Resolved lazily rather than defaulted in the signature so
        #: that mounting a tree does not build both dialects' form tables to
        #: use one of them — the same reason `.resize.polished` is a function.
        self._forms = forms
        #: Which warp macros this tree writes — the family's, or polished's
        #: larger set. Declared by the mount beside the anchor, for the same
        #: reason: both are forks the code states rather than sniffs.
        self.grammar = grammar
        #: Where this tree keeps each constant set a form may offer. The third
        #: fork the mount declares, and the third one a survey found rather
        #: than a rule predicted — see :data:`POLISHED_CHOICES`.
        self.set_of = CHOICES if set_of is None else set_of

    # -- what a form may offer ----------------------------------------------- #
    @property
    def _actions(self) -> tuple[dict, dict]:
        from . import actions as fa
        if self._forms is None:
            self._forms = (fa.VANILLA_ADDERS, fa.VANILLA_EDITORS)
        return self._forms

    def adders(self, kind: str) -> tuple:
        """What the tab-foot "Add new…" row opens.

        All four lists are here, plus the item ball — the first adder that
        writes the block its entry line points at rather than requiring one to
        already exist. Trainers are still absent and the absence is still
        measured rather than pending: a `trainer` block names two texts, and an
        adder that guessed at their shape would produce a map that assembles
        and then misbehaves, which is worse than a tab whose Add row says
        nothing.
        """
        return self._actions[0].get(kind, ())

    def form(self, name: str):
        """`resize` and `newmap` cross; `reword` is the text project.

        The plan had resize standing on `newmap`, and the survey said it does
        not: a resized map keeps whatever section it was already in, so resize
        never asks the placement question that makes `newmap` hard. They are
        two capabilities and the cheap one arrived first.

        Each dialect is the one the mount declared, defaulting to vanilla's,
        and each is resolved lazily for the reason `_forms` gives below.
        """
        if name == "resize":
            from ...studio.resize import resize_for
            from .resize import VANILLA
            return resize_for(self._resize or VANILLA, "Family")
        if name == "newmap":
            from ...studio.mapadd import newmap_for
            d = self._newmap or newmap.VANILLA
            return newmap_for(d, "Family", d.header_fields, d.asks)
        return None

    def choices(self, kind: str, map_consts: tuple[str, ...],
                values: dict[str, str] | None = None) -> list[str]:
        """The constants a family field of this kind will accept.

        An unknown kind is `[]` — free text, not an error — and that is the
        honest answer for most of the vocabulary here rather than a stub. This
        tree has no trainer classes the studio can roster (`PARTIES`,
        `CLASSES`), and its TMs are pasted together by `add_tm` at assembly
        time and appear nowhere in the source (`TMHMS`), which is the same trap
        prism's `studio/offers.py` documents. The map-header enums
        (`TILESETS`, `LANDMARKS`, `MUSIC`, `TIMES`, `FISHGROUPS`, `SIGNS`) are
        read now, because the new-map form asks — and the landmarks are a fork
        rather than a shared entry: vanilla writes `LANDMARK_OLIVINE_CITY`,
        polished writes `OLIVINE_CITY`, and the prefix that filters one file
        empties the other.

        The two section kinds are the odd ones out and answer through the
        placement record rather than a `ConstSet`: their answers are not
        constants in a file but `SECTION` names. An empty list from them means
        *this tree mints* rather than "nothing found" — a case the form never
        reaches, since it drops the field for a minted blob, but answering it
        the same way here keeps the two statements of it from disagreeing.
        """
        if kind == actions.MAPS:
            return list(map_consts)
        if (offered := newmap.offers(
                self.root, self._newmap or newmap.VANILLA, kind)) is not None:
            return offered
        if (cs := self.set_of.get(kind)) is None:
            return []
        return list(read_set(self.root, cs))

    def follows(self, action, changed: str,
                values: dict[str, str]) -> dict[str, str]:
        """Nothing follows from anything here, and that is a measurement.

        Prism's one rule fills the sprite and palette a trainer class usually
        wears, and it does that by *counting* every trainer in the repo — see
        `hacks/prism/trainerstats.py`, which exists because no rule was ever
        going to produce `SPRITE_BUENA` for a `SKIER`. The family's forms have
        no class field to hang that off, so there is nothing to suggest, and an
        invented suggestion would be worse than an empty one.
        """
        return {}

    def sprite_hint(self, map_const: str, sprite: str) -> str:
        """No hint, honestly.

        Prism answers this with two facts, and the family can supply neither.
        *Who wears this sprite* is counted off prism's trainer tables. *Whether
        they can walk here* is `maplint`'s VRAM-table measurement, and the
        linter is written against prism — `Hack.ctx` is None for these trees,
        which is the same absence the Diagnostics pane already renders. A hint
        assembled from half the facts would read as authoritative, so the field
        gets no hint line at all rather than a misleading one.
        """
        return ""

    def warm(self) -> None:
        """Read the constant sets off the UI thread, so the first form to open
        does not pay for 2,254 event flags while you look at an empty box."""
        for cs in self.set_of.values():
            read_set(self.root, cs)

    def forget(self) -> None:
        """Something was written: a new flag is a new name the next form must
        offer. `read_set` is an `lru_cache` on a module function, so
        `shared/caches.py` finds it too — this is belt and braces, and the belt
        is the one that gets tested."""
        read_set.cache_clear()

    def editor(self, label: str, const: str, ref, said: list):
        """The form `e` would open on this row, filled in with what is there.

        Keyed by the **list** the entry lives in rather than by `ref.what`.
        The six tables above the seam are a reading of the block each entry
        points at — an `object_event` is an NPC or a fruit tree depending on a
        macro in another block entirely — but what an editor rewrites is a
        line, and a line belongs to exactly one of four lists. So resolving the
        handle *is* choosing the form, and the row's kind never comes into it.

        `said` goes unused: rewording is the text project, and a family text
        block is not a field on any of these forms.
        """
        if ref.what == "map":
            raise Refused(
                "the map's own attributes live in three files this adapter "
                "only reads — editing them is not wired for this dialect yet.")
        if ref.what == "connection":
            raise Refused(
                "editing a connection means rewriting the neighbour's side "
                "too — not wired for this dialect yet.")

        from . import actions as fa
        block = parse_map(self.root / f"maps/{label}.asm", self.anchor)
        kind, index = _resolve(block, label, ref)
        action = self._actions[1][kind]
        return action, fa.prefill(block, kind, index, action.shape), {}

    # -- what a selected row can do ------------------------------------------- #
    def deletion(self, label: str, const: str, ref):
        """The action `d` would run on this row — or the reason there isn't one."""
        from ..mount import Refused
        if ref.what == "map":
            raise Refused("deleting a whole map is not something this does.")
        if ref.what == "connection":
            raise Refused(
                "removing a connection means rewriting the neighbour's side "
                "too — not wired for this dialect yet.")

        block = parse_map(self.root / f"maps/{label}.asm", self.anchor)
        kind, index = _resolve(block, label, ref)
        if ref.what == "warp":
            return RemoveWarp(label, const, self.anchor, self.grammar,
                              index=str(index))

        entry = block.lists[kind].entries[index]
        y, x = _shown_coords(entry.args)
        return Remove(label, self.anchor,
                      what=ref.what, kind=kind, index=str(index),
                      name=ref.handle if isinstance(ref.handle, str) else "",
                      y=y, x=x)


def _resolve(block: EventBlock, label: str, ref) -> tuple[str, int]:
    """The (list, position) a handle names, freshly resolved. A named object's
    handle is its const — resolution *is* the name lookup, which is what makes
    it survive the list reordering underneath it — and a stale handle of
    either shape refuses with the reason rather than pointing at whatever is
    standing in its place now."""
    handle = ref.handle
    if isinstance(handle, str):
        index = block.index_of(handle)
        if index is None:
            raise Refused(
                f"{label} no longer declares {handle} — the map changed under "
                "the table. Select it again.")
        return "object", index
    kind, index = handle
    if block.entry_at(kind, index) is None:
        raise Refused(
            f"{label} no longer has a {ref.what} at {handle} — the map "
            "changed under the table. Select it again.")
    return kind, index


def _shown_coords(args: list[str]) -> tuple[str, str]:
    """The (y, x) to *say* on the confirm screen — the macro writes (x, y),
    the turn the read adapter makes at the seam, made here for the same
    sentence. "" where the source wrote an expression."""
    x = args[0] if args and args[0].isdigit() else ""
    y = args[1] if len(args) > 1 and args[1].isdigit() else ""
    return y, x


def delete_warp(root: Path, label: str, map_const: str, index: int,
                anchor: str = "_MapEvents",
                grammar: WarpGrammar = WARPS) -> warpdel.Deletion:
    """Take warp #(index+1) out of `label`, and fix the whole repo behind it.

    The mirror of prism's :func:`..prism.write.delete_warp` over the family's
    own parser: this half is the dialect's — find the map file, splice the entry
    out of its ``def_warp_events`` list — and :mod:`...wiring.warpdel` does the
    half that is every tree's, from the grammar handed to it. Neither function
    is a copy of the other; the rule they share lives in one place and each
    tree's spelling of it is a record.
    """
    path = root / f"maps/{label}.asm"
    try:
        block = parse_map(path, anchor)
    except (UnparseableEvents, panels.Unreadable) as exc:
        raise warpdel.WarpDelError(
            f"{map_const}'s event block can't be read, so its warps can't be "
            f"counted: {exc}") from exc

    warps = block.lists["warp"].entries
    if not 0 <= index < len(warps):
        raise warpdel.WarpDelError(
            f"{map_const} has {len(warps)} warp{'s' if len(warps) != 1 else ''}, "
            f"so there is no warp #{index + 1} to delete")

    y, x = _shown_coords(warps[index].args)
    block.remove_entry("warp", index)
    return warpdel.delete_warp(root, map_const, index, grammar,
                               own_rel=f"maps/{label}.asm",
                               spliced=block.to_text(),
                               where=f"({y}, {x})" if y else "")


class RemoveWarp(Action):
    """A warp is the one deletion whose blast radius is not one map file.

    Its destination is a *position* in the destination map's warp list, so
    every door in the repo that counted its way past this one has to be pulled
    back a step — and in this dialect three different macros do that counting.
    The preview shows every file that touches, which for a busy map is a dozen;
    that is not the preview being noisy, it is the true cost of the operation.

    Unlike prism's, this one can refuse *after* you have pointed at it: a door
    that led here has nowhere to go in a dialect with no `dummy_warp`, and the
    refusal names the doors so they can be repointed first.
    """
    name = "remove warp"
    title = "Remove a warp"

    def __init__(self, label: str, map_const: str, anchor: str,
                 grammar: WarpGrammar, **values: str) -> None:
        super().__init__(**values)
        self.label = label
        self.map = map_const
        self.anchor = anchor
        self.grammar = grammar

    def describe(self) -> str:
        return f"remove warp #{self.integer('index') + 1} from {self.map}"

    def run(self, root: Path) -> Result:
        try:
            d = delete_warp(root, self.label, self.map, self.integer("index"),
                            self.anchor, self.grammar)
        except warpdel.WarpDelError as e:
            raise ActionError(str(e)) from e
        return Result(d.summary, d.changes, d.warnings)


class Remove(Action):
    """Take one entry out of a map — the family's other write today.

    `name`/`kind`+`index` say **which** entry, and the rest only says what to
    call it on the confirm screen. A named object is found by its const at
    run time, not by the position it had when you pointed at it: the name is
    the identity the dialect itself uses, so it is the identity this trusts.

    The script block the entry pointed at is left alone, and the notes say
    so: with no linter on this dialect, an orphaned block is yours to notice.
    """
    name = "remove"
    title = "Remove an entry"

    def __init__(self, label: str, anchor: str, **values: str) -> None:
        super().__init__(**values)
        self.label = label
        self.anchor = anchor

    def describe(self) -> str:
        what = self.text("name") or (
            f"{self.text('what')} at ({self.text('y')}, {self.text('x')})"
            if self.text("y") else f"{self.text('what')} #{self.integer('index') + 1}")
        return f"remove {what} from {self.label}"

    def run(self, root: Path) -> Result:
        block = parse_map(root / f"maps/{self.label}.asm", self.anchor)
        if name := self.text("name"):
            index = block.index_of(name)
            if index is None:
                raise ActionError(
                    f"{self.label} no longer declares {name} — nothing was removed.")
            kind = "object"
        else:
            kind, index = self.text("kind"), self.integer("index")
            if block.entry_at(kind, index) is None:
                raise ActionError(
                    f"{self.label} no longer has a {self.text('what')} there — "
                    "nothing was removed.")
        entry = block.lists[kind].entries[index]
        pointer = next((a for a in entry.args if a and a[0].isupper()
                        and not a.isupper()), "")
        removed = block.remove_entry(kind, index)
        notes = []
        if removed:
            notes.append(f"removed const {removed} with it — scripts that "
                         f"named it no longer assemble until they let go")
        if pointer:
            notes.append(f"{pointer} and its text stay in the file — "
                         "no linter reads this dialect, so an orphan is "
                         "yours to notice")
        return Result(self.describe(), [block.to_edit(root, self.describe())], notes)
