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
form ask for its fields again — that is how one object form is six forms, and it
is why a TM ball has no quantity box to get wrong. A field that changes lets the
*action* fill in others (a trainer class knows what it wears), and the form
applies that only where you haven't typed. Not one of those rules mentions a
an object, a TM or a trainer.

The dialogue box is the exception worth explaining. It is still schema-driven —
it appears because a field said `kind="lines"` — but it carries a second panel
that measures what you type in *tiles*, against the box the text will really be
drawn in. `#` is four tiles, not one; `<PLAYER>` is seven at its longest; and the
speech bubble is eighteen columns wide. Finding that out from the linter after
you've saved is finding it out too late, so the count updates on the keystroke.

The map preview is the same idea, and it is why the new-map form is worth having
at all. An action that says `sketches = True` gets a **Preview map** button, and
pressing it draws the map you have described — the `.blk` you are pointing at, at
the height and width you typed, in the tileset you named — on the studio's own
grid, before a byte is written. This file still doesn't know what a `.blk` is. It
knows that some actions can show you what they mean, and that showing beats telling.

It draws it on the *main* grid, and the form gets out of the way while you look.
That is a change from the panel this form used to carry, and the reason is size: a
route is forty blocks across, a modal that also holds nineteen fields can spare it
ten rows, and a map you can see the top-left corner of cannot answer the question
you drew it to answer. The form is handed back exactly as you left it — see
:class:`~..model.Draft`, which carries your answers out and back — so looking costs
you nothing but the keystroke.
"""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, OptionList, Static, TextArea

from .speech import Dialogue

from ...contract import Action, ActionError, Field
from ..combo import Combo
from ...contract import Ref
from ..session import Draft, Preview, Session

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


class Form(ModalScreen["Preview | Draft | None"]):
    """One action's fields, and nothing else.

    Submitting writes nothing. It builds the action and *previews* it, which is
    where an action that cannot be built at all — a sprite that doesn't exist, a
    party index past the end of the group — refuses. It refuses here, having
    touched not one byte of the repo, and the message the asm editor wrote for
    a human is shown under the form with everything you typed still in it.

    Three things the form does without knowing what any of them mean:

    *A field with `choices` becomes a combo* — a box with the known answers under
    it. It asks the session for the list.

    *A field that `reveals` rebuilds the form.* Change an object's kind and the
    fields change with it, because the action is asked again what fields it wants
    now. The form learns that the shape moved, not what moved it.

    *A field that changed can fill in others.* Pick a trainer class and the sprite
    and palette fill themselves in — but only if you have not typed in them
    yourself. A suggestion may fill an empty box; it may not overwrite an answer.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Preview"),
        # Only ever on a form that can draw itself, and the footer says so only
        # there — see `check_action`. Reachable by tab as well, but a form with
        # nineteen fields is one you should not have to tab to the end of.
        Binding("ctrl+d", "draw", "Preview map"),
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
    #form-error { padding: 0 1; color: $error; height: auto; }
    #form-buttons { height: 3; align: right middle; padding: 0 1; }
    .field-label { color: $text-muted; }
    .field-help { color: $text-disabled; }
    .field-fixed { color: $accent; text-style: bold; }
    Dialogue { height: 10; border: solid $panel; }
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

    def compose(self) -> ComposeResult:
        self._shown = self._action.fields_for(dict(self._values))
        with Vertical(id="form"):
            yield Static(self._action.title, id="form-title")
            with VerticalScroll(id="form-body"):
                for f in self._shown:
                    yield from self._widgets(f)
            yield Static(id="form-error")
            with Horizontal(id="form-buttons"):
                yield Button("Cancel", id="cancel")
                if self._action.sketches:
                    yield Button("Preview map", id="draw")
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
        if f.name == "sprite" and any(x.name == "cls" for x in self._shown):
            # Only a trainer's sprite has a class next to it to be a suggestion
            # *about*. Kept out of `Field.help`, which is fixed at declaration —
            # this line depends on the sprite you are looking at and the map
            # you opened the form from, and both can change after the form is
            # already on screen.
            out.append(Static(id="sprite-hint", classes="field-help"))
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
        """What the combo under this field offers: the answers the field carries,
        else the ones the session can enumerate, else no combo at all."""
        if f.options:
            return list(f.options)
        return self._session.choices(f.choices, self.values()) if f.choices else []

    def values(self) -> dict[str, str]:
        """The form as it stands.

        What is in the boxes — plus what was typed into fields that have since left
        (an object that is now a tree still remembers the item you named before you
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
        self._retile()
        self._update_hint()

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

        if name in ("sprite", "cls"):
            self._update_hint()

        # `Input.Changed` fires for programmatic writes too — a field prefilled
        # from the object it edits posts one the moment it's built, same as if you
        # had typed it. Only a change to the *focused* box is a change you made,
        # and only that kind may mark a field as typed-in or fill in the rest of
        # the form: an edit form's prefilled sprite must not be overwritten by the
        # class's usual one the instant the class field mounts with its own
        # existing value.
        if self.focused is not event.input:
            return
        self._typed_in.add(name)

        self._follow(name)
        self._refresh_choices(name)
        if field.reveals:
            await self._reshape(name)

    def _update_hint(self) -> None:
        """Refresh the sprite field's hint line, if this form has one.

        Runs on every change to `sprite` or `cls` — including the mount-time
        one a prefilled edit form fires on its own, which is exactly when this
        should say something: opening a trainer you did not just create is the
        moment the hint has an actual sprite to talk about.
        """
        found = self.query("#sprite-hint")
        if not found:
            return
        text = self._session.sprite_hint(self._map, self.values().get("sprite", ""))
        found.first(Static).update(text)

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
        # about to leave: change an object from an item ball to a tree and back, and
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
    @on(Button.Pressed, "#draw")
    def action_draw(self) -> None:
        """Show me what I have described, on the real grid, full size.

        Every field on this form is a way for the answer to be *not yet* — a height
        you have typed one digit of, a `.blk` you have not pointed at. None of those
        is an error, but none of them is a picture either, so what the action says
        about why it cannot draw goes where a refusal goes, and you carry on typing.

        Closing the form to draw is the trade, and the whole of it is given back:
        the values leave with the :class:`Draft` and come back in the form the app
        reopens. Nothing has been written.
        """
        if not self._action.sketches:
            return
        values = self.values()
        try:
            view = self._session.sketch(self._action(self._map, **values))
        except ActionError as err:
            self._refuse(str(err))
            return
        if view is None:
            self._refuse("there is nothing to draw yet")
            return
        self.dismiss(Draft(values=values, view=view))

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        # A form that cannot draw itself should not advertise a key that draws it.
        if action == "draw":
            return True if self._action.sketches else None
        return True

    def _retile(self) -> None:
        """Measure every dialogue box in the form, on every keystroke.

        Cheap enough to do it this way: the metrics are cached on the session and
        measuring a line is a walk over its tokens. What it buys is the whole
        reason the text rules exist — you see `#mon Center` cost 19 tiles against
        an 18-column box while you are still able to shorten it.

        The answer goes back into the box it came from, not into a panel that
        repeats the words underneath. See `screens/speech.py`.

        On a tree that declares no text metrics there is nothing to measure
        with, so the gutter is simply absent — the words are still yours to
        type, the tile counts were never a promise this tree made.
        """
        if not self._session.measures:
            return
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
            self._refuse(str(err))
            return
        self.dismiss(preview)

    def _refuse(self, why: str) -> None:
        """Under the form, with everything you typed still in it."""
        self.error = why
        self.query_one("#form-error", Static).update(Text(why, style="bold red"))

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def _next_field(self) -> None:
        self.focus_next()


