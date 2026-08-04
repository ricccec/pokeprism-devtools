"""One staged change, and the three records a form is built from.

The studio stages *actions*, not edits, and `shared/edits.py` says why: an
:class:`~..shared.edits.Edit` carries the whole file text plus the text it was
derived from, so two edits built against the same starting file and applied in
turn do not merge — the second overwrites the first, and the first silently
never happened. Add two NPCs before saving and the flag allocator hands both
the same slot, because when the second one looked, the first was not written.

An *intent* can be replayed, and replaying it is what makes a stack of changes
safe: each action is built against the tree as the previous ones left it. It
also means the diff you approve comes out of the identical code path that will
run for real — the preview is a rehearsal, not a model of one.

Each action declares its fields, so an IDE builds its own form and its own
autocomplete from that declaration and knows nothing about NPCs or connections.
Here is the base and nothing but the base; every action that does something to
a particular tree lives in that tree's adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..shared.edits import Edit
from .ref import Ref


class ActionError(RuntimeError):
    """The action can't be built from what the form was given. Carries a message
    meant for a human — the wiring layer's errors already read that way."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    #: text | int | lines | fixed. `fixed` is decided by context rather than
    #: typed — you picked the text block you wanted to reword by picking it, and
    #: a box you could edit would let you point new words at a different block.
    kind: str = "text"
    default: str = ""
    choices: str = ""
    #: The answers, written down here rather than named for the session to go and
    #: find. For the one kind of field whose answers are not in the repo at all: an
    #: object's kind is a closed list this studio made up — six things it knows how
    #: to place — and there is nothing in pokeprism to enumerate. A field with these
    #: gets the same combo a `choices` field gets, and the form still doesn't know
    #: what any of the words mean.
    options: tuple[str, ...] = ()
    help: str = ""
    #: For `lines`: which box this text is drawn in, so the preview measures it
    #: against the right width. A sign is a different shape from a speech bubble
    #: and the same sentence fits one and not the other.
    box: str = "speech"
    #: This field decides which *other* fields the form has — an object's kind. The
    #: form re-asks :meth:`Action.fields_for` when it changes. Nothing here says
    #: what it reveals; that is the action's business.
    reveals: bool = False
    #: Field names whose value changes what this one may *offer*. A party belongs
    #: to a class, so the parties on offer change when the class does. The form
    #: refetches the choices; it still doesn't know what a party is.
    depends: tuple[str, ...] = ()


@dataclass
class Result:
    """What an action did once it ran. `notes` are things the wiring layer
    decided the human must know — an orphaned party, a flag left allocated."""
    summary: str
    edits: list[Edit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Action:
    """One staged change. Subclasses declare FIELDS and implement `run`."""

    name = "action"
    title = "Action"
    FIELDS: tuple[Field, ...] = ()
    #: Whether this action can draw a picture of itself while you fill it in —
    #: see :meth:`sketch`. Declared rather than discovered, so the form can put
    #: the panel on screen before the fields have anything in them.
    sketches = False

    #: The thing this action changes, when it changes something already there.
    #: None for everything that adds.
    #:
    #: **Not a form field**, and that is the point: you did not type which warp you
    #: meant, you *pointed* at it, and a box you could edit would let a careless
    #: keystroke aim your changes at a different one. The form carries it across
    #: untouched — see `screens/forms.py` — for the same reason a `fixed` field
    #: exists at all.
    target: Ref | None = None

    def __init__(self, **values: str) -> None:
        self.values = values

    def __str__(self) -> str:
        return self.describe()

    def run(self, root: Path) -> Result:
        raise NotImplementedError

    # -- a form that changes shape -------------------------------------------- #
    @classmethod
    def fields_for(cls, values: dict[str, str]) -> tuple[Field, ...]:
        """The fields this action wants, *given what has been filled in so far*.

        Static for almost everything, which is why the default just hands back
        `FIELDS`. It is not static for an object: a hidden item has no sprite, an
        item ball has a quantity and a TM ball must not, a fruit tree has neither
        and has no event flag either. One form with every field on it would be a
        form on which most of the fields are a mistake — and the engine reads those
        slots differently per kind, so the mistake assembles.

        The form re-asks this whenever a `reveals` field changes. It learns nothing
        about objects by doing so: it learns that the shape moved.
        """
        return cls.FIELDS

    @classmethod
    def follows(cls, root: Path, changed: str, values: dict[str, str]) -> dict[str, str]:
        """What other fields should say, now that `changed` has changed.

        Picking a trainer class fills in the sprite and the palette that class
        usually wears — see `hacks/prism/trainerstats.py`, which *counts* rather than
        guessing, because the sprite for a `SKIER` is `SPRITE_BUENA` and no rule
        was ever going to produce that.

        The form applies these only to fields you have not typed in yourself: a
        suggestion is allowed to fill an empty box and never to overwrite an
        answer. Takes `root` because the answer is measured from the repo, and this
        is the model layer, which is the side of the seam allowed to read it.
        """
        return {}

    def describe(self) -> str:
        return self.title

    def selects(self) -> str | None:
        """The map to be looking at once this has landed, if it isn't this one.

        Only adding a map answers this. Every other action changes the map that
        is already on screen, and moving you somewhere else would be rude; adding
        one that you then have to go and find would be worse.
        """
        return None

    def sketch(self, root: Path) -> Any:
        """The blocks this action would put on the grid, from a half-filled form.

        Only :class:`~.newmap.NewMap` has anything to draw: it is the one action
        whose subject doesn't exist yet, so it is the one action you cannot check
        by looking at the map. Everything else acts *on* a map already on screen.

        Untyped on purpose, and it is the one hole the carve leaves. The only
        caller is the *read* adapter of the same hack that shipped the action
        (`hacks/prism/read.Reader.sketch`), which turns what comes back into a
        neutral `Blocks` before the studio sees it. So the value is one
        adapter handing itself its own record, and naming prism's `BlockData`
        here to say so would be the base importing an adapter to describe a
        journey it is not on.

        Raises :class:`ActionError` for a form that isn't ready, which is not a
        failure — it is what the panel says instead of a picture.
        """
        return None

    # -- reading the form ---------------------------------------------------- #
    def text(self, name: str) -> str:
        return (self.values.get(name) or "").strip()

    def integer(self, name: str, default: int | None = None) -> int:
        """A number out of the form. `default` is what an *empty* box means, which
        is not the same as what a missing one means: a form always sends every
        field it showed, but an action built in code sends only what it cares
        about, and a quantity nobody mentioned is one."""
        raw = self.text(name)
        if not raw and default is not None:
            return default
        try:
            return int(raw, 0)
        except ValueError:
            raise ActionError(f"{name} must be a number, not {raw!r}") from None

    def coords(self, y: str = "y", x: str = "x") -> tuple[int, int]:
        return self.integer(y), self.integer(x)

    def pages(self, name: str) -> list[list[str]]:
        """A text area into dialogue pages: one line per line, a blank line
        starts a new textbox. Empty is an error — every script here points at
        text, and text that doesn't exist assembles into a jump to nowhere."""
        raw = (self.values.get(name) or "").replace("\r\n", "\n")
        pages, current = [], []
        for line in raw.split("\n"):
            if line.strip():
                current.append(line.strip())
            elif current:
                pages.append(current)
                current = []
        if current:
            pages.append(current)
        if not pages:
            raise ActionError(f"{name} can't be empty — the script has to say something")
        return pages
