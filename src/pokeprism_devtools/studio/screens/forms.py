"""Picking one of a list, and filling one in. The confirmation is next door.

Nothing in here knows what an NPC is. A form is built by asking an action which
fields it wants and putting a box on screen for each one; a box that names a
`choices` kind gets its list by asking the session, which is the only thing
allowed to know that sprites live in `constants/sprite_constants.asm`. Add an
action with a new field tomorrow and this file renders it without being touched —
that is the whole point of the declaration, and the moment a `if field.name ==
"sprite"` appears here, the seam has leaked and `session.py`'s promise is broken.

The three things a field can do to the rest of the form are all declared, for the
same reason. A field with `choices` gets a combo. A field that `reveals` makes the
form ask for its fields again — that is how one pickup form is four forms, and it
is why a TM ball has no quantity box to get wrong. A field that changes lets the
*action* fill in others (a trainer class knows what it wears), and the form
applies that only where you haven't typed. Not one of those rules mentions a
pickup, a TM or a trainer.

The dialogue box is the exception worth explaining. It is still schema-driven —
it appears because a field said `kind="lines"` — but it carries a second panel
that measures what you type in *tiles*, against the box the text will really be
drawn in. `#` is four tiles, not one; `<PLAYER>` is seven at its longest; and the
speech bubble is eighteen columns wide. Finding that out from the linter after
you've saved is finding it out too late, so the count updates on the keystroke.

The map sketch is the same idea, and it is why the new-map form is worth having
at all. An action that says `sketches = True` gets a grid under its fields, and on
every keystroke it is asked to draw itself. It is drawn by the very widget that
draws the real map, from the very colours — so the `.blk` you are pointing at,
at the height and width you have typed so far, in the tileset you have named,
appears before a byte is written. This file still doesn't know what a `.blk` is.
It knows that some actions can show you what they mean, and that showing beats
telling.
"""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, OptionList, Static, TextArea

from .speech import Dialogue

from ..actions import Action, ActionError, Field
from ..combo import Combo
from ..grid import ZOOMS, MapGrid
from ..panels import Ref
from ..session import Preview, Session

#: Fields the grid can answer for you. The cursor is *on* the tile; making you
#: read its coordinates off the status bar and type them back in would be a way
#: of introducing a typo into the one number that is already known.
CURSOR_FIELDS = {"y": 0, "x": 1}


class Picker(ModalScreen[int | None]):
    """A list of things, one of which you want. Dismisses with its index.

    It filters, because the list it most often shows is every text block in a
    map, and a talkative town has forty of them. Typing narrows; the index it
    dismisses with is always the caller's, never the filtered list's — get that
    backwards and picking the third line of a filtered list rewords whatever
    happened to be third before you typed.
    """

    BINDINGS = [Binding("escape", "dismiss_none", "Cancel")]

    CSS = """
    Picker { align: center middle; }
    #picker { width: 82; height: auto; max-height: 80%;
              border: round $accent; background: $surface; }
    #picker-title { padding: 0 1; background: $accent; color: $text; }
    #picker-filter { border: none; height: 3; background: $surface; }
    #picker-list { height: auto; max-height: 24; border: none; }
    """

    def __init__(self, title: str, rows: list[str] | list[Text],
                 *, filterable: bool = False) -> None:
        super().__init__()
        self._title = title
        self._rows = rows
        self._filterable = filterable
        #: The caller's index for each row currently on screen.
        self._shown = list(range(len(rows)))

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Static(self._title, id="picker-title")
            if self._filterable:
                yield Input(placeholder="filter", id="picker-filter")
            yield OptionList(*self._rows, id="picker-list")

    def on_mount(self) -> None:
        self.query_one("#picker-list", OptionList).focus()

    @on(Input.Changed, "#picker-filter")
    def _filtered(self, event: Input.Changed) -> None:
        needle = event.value.strip().lower()
        options = self.query_one("#picker-list", OptionList)
        options.clear_options()

        self._shown = [i for i, row in enumerate(self._rows)
                       if needle in _plain(row).lower()]
        options.add_options([self._rows[i] for i in self._shown])
        if self._shown:
            options.highlighted = 0

    @on(Input.Submitted, "#picker-filter")
    def _to_the_list(self) -> None:
        self.query_one("#picker-list", OptionList).focus()

    @on(OptionList.OptionSelected, "#picker-list")
    def _chose(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._shown[event.option_index])

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


def _plain(row: str | Text) -> str:
    return row if isinstance(row, str) else row.plain


class Form(ModalScreen["Preview | None"]):
    """One action's fields, and nothing else.

    Submitting writes nothing. It builds the action and *previews* it, which is
    where an action that cannot be built at all — a sprite that doesn't exist, a
    party index past the end of the group — refuses. It refuses here, having
    touched not one byte of the repo, and the message the wiring layer wrote for
    a human is shown under the form with everything you typed still in it.

    Three things the form does without knowing what any of them mean:

    *A field with `choices` becomes a combo* — a box with the known answers under
    it. It asks the session for the list.

    *A field that `reveals` rebuilds the form.* Change a pickup's kind and the
    fields change with it, because the action is asked again what fields it wants
    now. The form learns that the shape moved, not what moved it.

    *A field that changed can fill in others.* Pick a trainer class and the sprite
    and palette fill themselves in — but only if you have not typed in them
    yourself. A suggestion may fill an empty box; it may not overwrite an answer.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Preview"),
    ]

    CSS = """
    /* The combo's dropdown lives on the screen rather than in the scrolling body,
       so that a field near the bottom of a long form can still show its list over
       whatever is beneath it instead of being clipped by the scroll box. */
    Form { align: center middle; layers: base dropdown; }
    #form { width: 78; height: auto; max-height: 90%;
            border: round $accent; background: $surface; }
    #form-title { padding: 0 1; background: $accent; color: $text; }
    #form-body { height: auto; max-height: 24; padding: 1 1 0 1; }
    /* A form with a picture in it is a tall one — the new map's has nineteen
       fields. The modal takes the height it is given, and of the two things
       competing for it the *map* wins: you fill the fields in one at a time and
       can scroll them, but a map you can only see the top of is not a map you
       can check. Without this the picture would also push Apply off the bottom
       of a short terminal. */
    #form.tall { height: 90%; }
    #form.tall #form-body { height: auto; max-height: 10; }
    #form.tall #sketch { height: 1fr; }
    #form-error { padding: 0 1; color: $error; height: auto; }
    #form-buttons { height: 3; align: right middle; padding: 0 1; }
    .field-label { color: $text-muted; }
    .field-help { color: $text-disabled; }
    .field-fixed { color: $accent; text-style: bold; }
    Dialogue { height: 10; border: solid $panel; }
    #sketch { height: 10; margin: 0 1; border: solid $panel; }
    #sketch-why { padding: 0 1; color: $warning; height: auto; }
    """

    def __init__(self, action: type[Action], session: Session, map_const: str,
                 cursor: tuple[int, int] | None = None,
                 values: dict[str, str] | None = None,
                 boxes: dict[str, str] | None = None,
                 target: Ref | None = None) -> None:
        super().__init__()
        self._action = action
        self._session = session
        self._map = map_const
        self._cursor = cursor
        #: The object being edited, when this form is editing one. Carried, never
        #: shown: it is not something you typed, it is the row you were standing
        #: on. See :attr:`Action.target`.
        self._target = target
        #: What to open the form with, when the caller already knows — the prose
        #: of the text block you picked, the label it hangs off. Still by field
        #: name: the form is filling in boxes, not editing dialogue.
        self._values = values or {}
        #: Which box a `lines` field is really drawn in, when it isn't the one the
        #: field declares. An existing block knows its own.
        self._box_of = boxes or {}
        #: The fields whose value came from *you*, rather than from a default or
        #: from another field filling them in. Nothing may overwrite one of these:
        #: a form that undoes your typing because you later changed a menu is a
        #: form you cannot trust with the thing you typed.
        self._typed_in: set[str] = set()
        #: The fields on screen, which for a form that changes shape is not the
        #: same thing as the fields the action declares.
        self._shown: tuple[Field, ...] = ()
        #: Why the last submit was refused, if it was.
        self.error = ""
        #: Why the sketch can't be drawn yet, if it can't.
        self.unsketchable = ""

    def compose(self) -> ComposeResult:
        self._shown = self._action.fields_for(dict(self._values))
        with Vertical(id="form", classes="tall" if self._action.sketches else ""):
            yield Static(self._action.title, id="form-title")
            with VerticalScroll(id="form-body"):
                for f in self._shown:
                    yield from self._widgets(f)
            if self._action.sketches:
                yield MapGrid(id="sketch")
                yield Static(id="sketch-why")
            yield Static(id="form-error")
            with Horizontal(id="form-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Preview", variant="primary", id="ok")

    def _widgets(self, f: Field) -> list[Widget]:
        if f.kind == "fixed":
            # Decided by context, not typed. Shown, because you should be able to
            # see *which* block you are about to reword — but not editable, or a
            # careless keystroke would aim your new words at a different one.
            return [Label(f"{f.label}: {self._prefill(f)}", classes="field-fixed")]

        out: list[Widget] = [Label(f.label, classes="field-label")]
        if f.help:
            out.append(Label(f.help, classes="field-help"))
        if f.kind == "lines":
            # Not a bare TextArea: a Dialogue draws what each line costs in tiles
            # in its own right margin, so the count is on the line it is about.
            out.append(Dialogue(self._prefill(f), id=f"field-{f.name}"))
        elif options := self._options(f):
            out.append(Combo(options, value=self._prefill(f), id=f"field-{f.name}",
                             placeholder=f.choices))
        else:
            out.append(Input(value=self._prefill(f), id=f"field-{f.name}"))
        return out

    def _prefill(self, f: Field) -> str:
        """What the caller knows, then what the cursor knows, then the default."""
        if f.name in self._values:
            return self._values[f.name]
        if self._cursor and f.name in CURSOR_FIELDS and f.kind == "int":
            return str(self._cursor[CURSOR_FIELDS[f.name]])
        return f.default

    def _box(self, f: Field) -> str:
        return self._box_of.get(f.name, f.box)

    def _options(self, f: Field) -> list[str]:
        return self._session.choices(f.choices, self.values()) if f.choices else []

    def values(self) -> dict[str, str]:
        """The form as it stands.

        What is in the boxes — plus what was typed into fields that have since left
        (a pickup that is now a tree still remembers the item you named before you
        changed your mind), plus, for a field whose box is not on screen *yet*, what
        it is about to be filled with.

        That last one is not a detail. This is called from `compose`, to decide
        whether a field's list has anything in it — and the party list depends on
        the class, whose box does not exist at that moment. Read only the mounted
        widgets and the class reads as blank, the parties come back empty, and the
        party field is built as a plain box with no list behind it: correct-looking,
        and inert until you happened to retype the class.
        """
        out = dict(self._values)
        for f in self._shown:
            widget = self._widget(f.name)
            if isinstance(widget, Dialogue):
                out[f.name] = widget.text
            elif isinstance(widget, Input):
                out[f.name] = widget.value
            else:
                out[f.name] = self._prefill(f)      # not mounted, or `fixed`
        return out

    def _widget(self, name: str) -> Widget | None:
        found = self.query(f"#field-{name}")
        return found.first() if found else None

    def on_mount(self) -> None:
        self._focus_first()
        if self._action.sketches:
            # A preview is for looking at, not for walking around. Its cursor and
            # its scrollbars would only be somewhere for the tab key to get lost.
            self.query_one("#sketch", MapGrid).can_focus = False
        self._retile()
        self._resketch()

    def _focus_first(self) -> None:
        # The first thing you can type in — which for "Edit dialogue" is the text
        # area, since its only other field is fixed.
        for widget in self.query("#form-body Input, #form-body TextArea"):
            widget.focus()
            return

    # -- the tile counter ------------------------------------------------------ #
    @on(TextArea.Changed)
    def _typed(self) -> None:
        self._retile()

    # -- one field changing the rest -------------------------------------------- #
    @on(Input.Changed)
    async def _edited(self, event: Input.Changed) -> None:
        name = (event.input.id or "").removeprefix("field-")
        field = next((f for f in self._shown if f.name == name), None)
        if field is None:
            return

        # Typed in by hand, so nothing may fill it in from now on. `Input.Changed`
        # fires for programmatic writes too, hence the check: only a change to the
        # *focused* box is a change you made.
        if self.focused is event.input:
            self._typed_in.add(name)

        self._follow(name)
        self._refresh_choices(name)
        if field.reveals:
            await self._reshape(name)
        self._resketch()

    def _follow(self, changed: str) -> None:
        """Let the action fill in the fields this one implies — a trainer class
        knows what it usually wears. Never over an answer you gave yourself."""
        for name, value in self._session.follows(
                self._action, changed, self.values()).items():
            if name in self._typed_in:
                continue
            widget = self._widget(name)
            if isinstance(widget, Input):
                widget.value = value

    def _refresh_choices(self, changed: str) -> None:
        """Re-offer the lists that depended on the field that just changed. Which
        parties exist depends on the class, and offering the old class's parties
        after you have changed it is offering the wrong team."""
        for f in self._shown:
            if changed in f.depends:
                widget = self._widget(f.name)
                if isinstance(widget, Combo):
                    widget.set_options(self._options(f))

    async def _reshape(self, changed: str) -> None:
        """Rebuild the body, because a `reveals` field says the form is now a
        different form. Nothing happens if the fields turn out to be the same
        ones — a rebuild you cannot see is still a rebuild that takes the cursor
        out of the box you are typing in.
        """
        was = self.values()
        fields = self._action.fields_for(was)
        if [f.name for f in fields] == [f.name for f in self._shown]:
            return

        # Everything typed so far is carried across, including into fields that are
        # about to leave: change a pickup from an item ball to a tree and back, and
        # the item is still there.
        self._values = was
        self._shown = fields
        body = self.query_one("#form-body", VerticalScroll)
        await body.remove_children()
        for f in fields:
            await body.mount_all(self._widgets(f))
        self._retile()
        # Back to the field you were on — it is the one that caused all this, and
        # a rebuild that dumped you at the top of the form would punish you for
        # using it.
        if (widget := self._widget(changed)) is not None:
            widget.focus()

    # -- the map, before it exists ---------------------------------------------- #

    @on(MapGrid.Moved)
    def _sketch_moved(self, event: MapGrid.Moved) -> None:
        # The sketch is a MapGrid, so it announces its cursor like any other. It
        # is a picture, though, and the app behind it has a real map with a real
        # cursor on it: let this reach the status bar and drawing the sketch would
        # move the coordinates the *next* form gets prefilled with.
        event.stop()

    def _resketch(self) -> None:
        """Draw the action, from the form as it stands. Or say why not.

        Every field is a way for this to be unanswerable, and none of them is an
        error: a form you have typed four characters into is *supposed* to be
        unanswerable. So the refusal goes where the picture would have gone, in
        the wording the action chose, and you carry on typing.
        """
        if not self._action.sketches:
            return
        grid = self.query_one("#sketch", MapGrid)
        try:
            view = self._session.sketch(self._action(self._map, **self.values()))
        except ActionError as err:
            self.unsketchable = str(err)
            grid.view = None
            grid.refresh()
        else:
            self.unsketchable = ""
            if view is not None:
                grid.show(view)
                grid.zoom = _fit(view.size, grid.size)
        self.query_one("#sketch-why", Static).update(self.unsketchable)

    def _retile(self) -> None:
        """Measure every dialogue box in the form, on every keystroke.

        Cheap enough to do it this way: the metrics are cached on the session and
        measuring a line is a walk over its tokens. What it buys is the whole
        reason the text rules exist — you see `#mon Center` cost 19 tiles against
        an 18-column box while you are still able to shorten it.

        The answer goes back into the box it came from, not into a panel that
        repeats the words underneath. See `screens/speech.py`.
        """
        for f in self._shown:
            if f.kind != "lines":
                continue
            box = self.query_one(f"#field-{f.name}", Dialogue)
            box.measured(self._session.measure(box.text, self._box(f)))

    # -- leaving ----------------------------------------------------------------- #
    @on(Button.Pressed, "#ok")
    def action_submit(self) -> None:
        """Build the action and preview it. Every action's first argument is the
        map it acts on; everything after that is the form, by name — plus, for a
        form that is editing something, *which* something, which came from the row
        you picked and never from a box."""
        action = self._action(self._map, **self.values())
        action.target = self._target
        try:
            preview = self._session.preview(action)
        except ActionError as err:
            self.error = str(err)
            self.query_one("#form-error", Static).update(
                Text(self.error, style="bold red"))
            return
        self.dismiss(preview)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def _next_field(self) -> None:
        self.focus_next()


def _fit(size: tuple[int, int], panel: Size) -> int:
    """The biggest zoom that shows the whole map at once, or the smallest there is.

    A cell is two tiles tall and one wide — see `grid._HALF` — so a map fits when
    `cols × zoom` cells across and `rows × zoom / 2` down are both inside the
    panel. A gym is four blocks square and should not be a postage stamp; a route
    is forty and will not fit however hard you squint, so it scrolls. Falling back
    to zoom 1 rather than refusing is the point: a partial picture of the wrong
    tileset is still a picture of the wrong tileset.
    """
    rows, cols = size
    if not (panel.width and panel.height):
        return ZOOMS[0]            # not laid out yet; the next keystroke re-fits
    return next((z for z in reversed(ZOOMS)
                 if cols * z <= panel.width and rows * z // 2 <= panel.height),
                ZOOMS[0])


