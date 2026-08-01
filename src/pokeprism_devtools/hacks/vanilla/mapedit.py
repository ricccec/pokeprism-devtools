"""Editing a family map's own header — the mirror of `hacks/prism/mapedit.py`.

Prism keeps a map's header in one `map_header`/`map_header_2` pair; the family
**splits it across two files**, and this module writes both, argument by
argument, under the same rule prism's does — *an argument you did not change
comes back exactly as it was written* (`wiring/macroline`, which both trees now
reach). The two lines:

    data/maps/maps.asm        map            Label, <the tree's own arguments>
    data/maps/attributes.asm  map_attributes Label, CONST, border

The `map` argument list **forks between the two family trees** — vanilla ends in
a fishing group, polished carries a location sign and no fishing group — but that
fork already exists as data: it is the `header_fields`/`header_args` the new-map
form declares (`newmap.VANILLA_FIELDS`/`POLISHED_FIELDS`), and the mount hands
this module the same `FamilyNewMap` dialect it hands `form("newmap")`. So one
module serves both trees; only the dialect it is called with differs.

**What is not editable is the interesting part**, and it is prism's list unchanged
(see `hacks/prism/mapedit.py` for the full argument):

* *the label and the map id* (`map_attributes`'s CONST, argument 0) are read-only:
  a rename touches every reference and a renumber drops every `.sav` onto the
  wrong map. The const rides along as a `kind="fixed"` row, shown and never written.
* *the group, the height and the width* are not in these two lines at all — they
  live in `constants/map_constants.asm`, and the size is `wiring/mapresize.py`'s
  own operation with its own refusals.
* *the connections* need no refusal here, unlike prism's conn_flags: the family's
  `MAP_CONNECTIONS_*` is computed by the `map_attributes` macro from the
  `connection` lines beneath it, so it is never a typed argument. The border-block
  splice is anchored on the `map_attributes Label,` line and leaves those
  `connection` lines untouched.
"""

from __future__ import annotations

import difflib

from pathlib import Path

from ...shared.constants import read_set
from ...studio.actions import Action, ActionError, Field, Result
from ...wiring.editvocab import Change, EditError, same
from ...wiring.macroline import find_macro_args, splice_macro_args

#: The two files the header is split across — the same in both family trees.
MAPS = "data/maps/maps.asm"
ATTRS = "data/maps/attributes.asm"
#: Where the border block sits in `map_attributes`'s arguments, after the label:
#: the map const (read-only), then the border block.
BORDER = 1


def values(root: Path, label: str, dialect) -> dict[str, str]:
    """The header as it stands — what the form opens with.

    Read straight from source rather than through the read adapter, because
    `panels.Attributes` drops polished's `sign` argument and the form needs every
    argument the writer will splice. Keyed by the dialect's `header_args`, so the
    prefill names line up with the fields and the splice indices exactly.
    """
    header = _args_of(root, MAPS, "map", label)
    if header is None:
        raise EditError(f"{label} has no map line in {MAPS}")
    if len(header) < len(dialect.header_args):
        raise EditError(
            f"{label}'s map line has {len(header)} arguments; this tree's macro "
            f"takes {len(dialect.header_args)} ({', '.join(dialect.header_args)})")
    attr = _args_of(root, ATTRS, "map_attributes", label)
    if attr is None or len(attr) <= BORDER:
        raise EditError(f"{label} has no map_attributes line in {ATTRS}")

    out = {"label": label, "const": attr[0], "border_block": attr[BORDER]}
    out.update(zip(dialect.header_args, header))
    return out


def edit_map(root: Path, label: str, dialect, set_of, new: dict[str, str]) -> Change:
    """Rewrite this map's two header lines with the values the form came back with.

    Only the arguments that actually moved are written, and only constants that
    moved are validated — you are not required to fix a music constant somebody
    wrote years ago just because you wanted to change the tileset (see
    :func:`_unknown`, the same rule prism keeps).
    """
    was = values(root, label, dialect)
    if problems := _unknown(root, dialect, set_of, was, new):
        raise EditError("; ".join(problems))

    args = dialect.header_args
    edits = [
        splice_macro_args(root, MAPS, "map", label,
                          {i: new[f] for i, f in enumerate(args) if f in new},
                          f"{label}: map header"),
        splice_macro_args(root, ATTRS, "map_attributes", label,
                          {BORDER: new["border_block"]} if "border_block" in new
                          else {}, f"{label}: border block"),
    ]
    # Named one by one, because a header is a list of unrelated facts and "the map
    # header changed" tells you nothing about which of them you are agreeing to.
    moved = [f"{k} -> {new[k]}" for k in (*args, "border_block")
             if k in new and not same(was[k], new[k])]
    return Change(
        f"{label}: {', '.join(moved) if moved else 'nothing changed'}",
        edits,
        [] if any(e.changed for e in edits) else ["unchanged — nothing to write"],
    )


def _unknown(root: Path, dialect, set_of, was: dict[str, str],
             new: dict[str, str]) -> list[str]:
    """Every constant this would write must exist — **that it is now writing**.

    Only the fields that actually moved, and driven by the field declarations
    themselves: an `options` field (environment, phone) is held to its own list,
    a `choices` field (tileset, landmark, music, palette, fishgroup, sign) to the
    set this dialect reads for that kind — which is what makes the landmark-prefix
    fork right without a branch, since polished's `set_of` points the landmark
    kind at the unprefixed file. The border block is free text (a block id like
    `$5`), so it is not checked. Same refusal shape as prism's `_unknown`.
    """
    out: list[str] = []
    for field in dialect.header_fields:
        value = new.get(field.name, "")
        if not value or same(value, was.get(field.name, "")):
            continue
        if field.options:
            if value not in field.options:
                out.append(f"{field.name} must be one of "
                           f"{', '.join(field.options)}")
        elif (cs := set_of.get(field.choices)) is not None:
            known = read_set(root, cs)
            if value not in known:
                near = difflib.get_close_matches(value, known, n=2)
                hint = f" Did you mean {' or '.join(near)}?" if near else ""
                out.append(f"{value} is not a {field.name} in this repo "
                           f"({len(known)} exist).{hint}")
    return out


def _args_of(root: Path, rel: str, macro: str, label: str) -> list[str] | None:
    """This map's `macro` arguments in `rel`, or None if the file has no such line.

    The read half of `wiring/macroline`, so the index a field is read at is the
    index :func:`edit_map` splices it back at.
    """
    path = root / rel
    if not path.exists():
        return None
    return find_macro_args(path.read_text(encoding="utf-8"), macro, label)


# --------------------------------------------------------------------------- #
# the form                                                                     #
# --------------------------------------------------------------------------- #

#: The two rows that name the map without letting you retype it, and the one
#: editable field that lives in the second file. The `map` arguments in between
#: are the dialect's own — `editmap_for` splices them in.
_LABEL = Field("label", "Map", kind="fixed")
_CONST = Field("const", "Constant", kind="fixed")
_BORDER = Field("border_block", "Border block",
                help="the block drawn outside the map's edge")


class FamilyEditMap(Action):
    """`e` on the Attributes tab, for a vanilla or polished map. Stamped with its
    tree's `map` arguments by :func:`editmap_for`, the same way `newmap_for`
    stamps the new-map form — a form is built as `action(map_const, **values)`,
    so the dialect is a class attribute rather than a third argument."""

    name = "editmap"
    title = "Edit the map header"
    #: The tree's answers, stamped by :func:`editmap_for`.
    dialect = None
    set_of: dict = {}

    def __init__(self, map_const: str = "", **values: str) -> None:
        super().__init__(**values)
        self.map = map_const

    def describe(self) -> str:
        return f"edit {self.text('label')}'s header"

    def run(self, root: Path) -> Result:
        new = {f.name: self.text(f.name) for f in self.dialect.header_fields}
        new["border_block"] = self.text("border_block")
        try:
            c = edit_map(root, self.text("label"), self.dialect, self.set_of, new)
        except EditError as e:
            raise ActionError(str(e)) from e
        return Result(c.summary, c.changes, c.notes)


def editmap_for(dialect, set_of: dict, tag: str) -> type[FamilyEditMap]:
    """This form, bound to one tree.

    `dialect.header_fields` is the tree's own `map` macro, one field per argument
    in the order the macro takes them — the adapter is the only thing entitled to
    know them, exactly as `newmap_for` argues. `set_of` is the dialect's choice
    sets, so the run-time validation reads the right (prefixed or unprefixed)
    landmark file.
    """
    return type(f"{tag}EditMap", (FamilyEditMap,),
                {"dialect": dialect, "set_of": set_of,
                 "__doc__": FamilyEditMap.__doc__,
                 "FIELDS": (_LABEL, _CONST) + dialect.header_fields + (_BORDER,)})
