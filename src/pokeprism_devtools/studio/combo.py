"""A text box that also knows the answers: type to filter, arrow to walk, enter to take.

There are 341 sprites in this repo. Inline autocomplete — the ghost text an
`Input` suggester draws ahead of the cursor — only helps if you already know how
the name *starts*, and half the time you don't: you want the lass sprite and it
is `SPRITE_LASS`, but you want the black belt and it is `SPRITE_BLACK_BELT` while
the class is `BLACKBELT_T`. What you need is to type "belt" and be shown what
there is.

So this is an `Input` with a list under it. It matches anywhere in the name, not
just at the front, and it puts what starts with your text above what merely
contains it — "TM" should offer `TM_HAIL` before `HM_CUT`'s neighbours.

**The text stays free**, which is why Textual's `Select` cannot do this job. A
`Select` insists its value be one of its options; but the event-flag field must
accept `EVENT_CASTRO_FOREST_SAGE`, a name that does not exist yet and will be
created *because* you typed it. The list is an offer, never a constraint. Every
field that refuses an unknown value refuses it in the wiring layer, where the
refusal can explain itself — not here, by making it untypable.

The dropdown is mounted on the **screen**, not inside the form, and that is not a
detail: a form scrolls, and a list that lived inside it would be clipped by the
scroll container the moment the field it belongs to was near the bottom — which is
exactly when you need it. Living on its own layer, positioned from the input's
on-screen region, it can hang over whatever is below.
"""

from __future__ import annotations

from textual import events
from textual.suggester import SuggestFromList
from textual.widgets import Input, OptionList

#: How many rows to offer. The list is not a browser: past a screenful, the answer
#: is to type another letter, and a dropdown taller than the form is a dropdown
#: that hides the form.
LIMIT = 40


class Suggestions(OptionList):
    """The list under a Combo. One per Combo, mounted on the screen."""

    DEFAULT_CSS = """
    Suggestions {
        layer: dropdown;
        display: none;
        max-height: 10;
        border: round $accent;
        background: $surface;
        padding: 0;
        scrollbar-size-vertical: 1;
    }
    Suggestions.open { display: block; }
    """

    def __init__(self, combo: Combo) -> None:
        super().__init__()
        # It is a list you *read*; the keys that walk it are handled by the Combo,
        # so focus never leaves the box you are typing in — and so a click on a row
        # doesn't blur the input out from under you.
        self.can_focus = False
        self._combo = combo

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """A click on a row. Handled here rather than on the Combo because this
        list is mounted on the *screen*, so its messages bubble to the screen and
        never pass the Combo at all."""
        event.stop()
        self._combo.take()


class Combo(Input):
    """An Input over a list of known values. The list suggests; it does not insist."""

    def __init__(self, options: list[str], **kwargs) -> None:
        # The ghost text stays, because the two do different jobs: the list shows
        # you what exists, the ghost completes what you have already committed to.
        super().__init__(suggester=SuggestFromList(options, case_sensitive=False),
                         **kwargs)
        self._options = options
        self._list = Suggestions(self)

    # -- the list --------------------------------------------------------------- #
    def set_options(self, options: list[str]) -> None:
        """Offer a different set — a party list changes when the class does."""
        self._options = options
        self.suggester = SuggestFromList(options, case_sensitive=False)
        if self._open:
            self._refilter()

    def matches(self, text: str) -> list[str]:
        """What is on offer for this text: what starts with it, then what merely
        contains it. Empty text offers everything, because an empty box is a
        question ("what is there?"), not a filter."""
        needle = text.strip().lower()
        if not needle:
            return self._options[:LIMIT]
        starts = [o for o in self._options if o.lower().startswith(needle)]
        within = [o for o in self._options
                  if needle in o.lower() and not o.lower().startswith(needle)]
        return (starts + within)[:LIMIT]

    @property
    def _open(self) -> bool:
        return self._list.has_class("open")

    def _refilter(self) -> None:
        rows = self.matches(self.value)
        self._list.clear_options()
        self._list.add_options(rows)
        if rows:
            self._list.highlighted = 0
        self._show(bool(rows))

    def _show(self, open_: bool) -> None:
        self._list.set_class(open_, "open")
        if open_:
            self._place()

    def _place(self) -> None:
        """Under the input, as wide as the input, in screen coordinates.

        The dropdown is alone on its layer, so its natural position is the screen's
        top-left and the offset *is* the position. `region` is where this input is
        on the screen right now — including any scrolling the form has done — which
        is why this is recomputed on every open rather than remembered.
        """
        region = self.region
        self._list.styles.width = region.width
        self._list.styles.offset = (region.x, region.y + region.height)

    # -- the keys --------------------------------------------------------------- #
    def on_key(self, event: events.Key) -> None:
        if event.key == "down":
            event.stop()
            event.prevent_default()
            if not self._open:
                self._refilter()
            else:
                self._list.action_cursor_down()
        elif event.key == "up" and self._open:
            event.stop()
            event.prevent_default()
            self._list.action_cursor_up()
        elif event.key == "enter" and self._open:
            # Enter takes the highlighted row. Without stopping the event the form
            # would also read it as "next field", and you would land two fields on
            # from the one you were choosing a value for.
            event.stop()
            event.prevent_default()
            self.take()
        elif event.key == "escape" and self._open:
            # Only when open: with the list shut, escape belongs to the form, and a
            # combo that swallowed it would make the form uncloseable from a field.
            event.stop()
            event.prevent_default()
            self._show(False)

    def take(self) -> None:
        """Put the highlighted row in the box, and shut the list."""
        index = self._list.highlighted
        if index is None:
            return
        self.value = str(self._list.get_option_at_index(index).prompt)
        self.cursor_position = len(self.value)
        self._show(False)

    # -- the life of the dropdown ----------------------------------------------- #
    def on_mount(self) -> None:
        self.screen.mount(self._list)

    def on_unmount(self) -> None:
        # A form that rebuilds its fields (a pickup changing kind) unmounts this
        # box. The list lives on the screen, not in the form, so nothing else would
        # ever take it down and it would hang there over the new fields.
        self._list.remove()

    def on_input_changed(self) -> None:
        if self._open:
            self._refilter()

    def on_blur(self) -> None:
        self._show(False)
