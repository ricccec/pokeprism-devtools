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
field that refuses an unknown value refuses it in the asm editors, where the
refusal can explain itself — not here, by making it untypable.

The dropdown is mounted on the **screen**, not inside the form, and that is not a
detail: a form scrolls, and a list that lived inside it would be clipped by the
scroll container the moment the field it belongs to was near the bottom — which is
exactly when you need it. Living on its own layer, positioned from the input's
on-screen region, it can hang over whatever is below.

Which is also the trap, and it took two bugs to see the whole of it. A widget on
its own layer can be positioned *anywhere*, including past the bottom of the
terminal, and Textual will do exactly that and simply not draw the rows that are
off the end. Nothing clips, nothing scrolls, nothing complains — the list is just
short. So the last field of a form got a dropdown showing two of its forty answers.
It now opens upwards when there is no room below: see :meth:`Combo._place`.

And the second half, which is why that fix looked right and read wrong: **a layer
is arranged, not exempted.** `_arrange.arrange()` walks the layers one at a time
and applies the container's `align` to *each* of them, and the form is
`align: center middle` — so the dropdown's own layer was centred too, and the
list's natural origin was the middle of the screen rather than its top-left. A
`styles.offset` is measured from there, so every list was drawn a half-screen down
and to the right of the box it belonged to: below the form, and looking for all the
world like the same off-the-bottom bug. What the offset needed was not better
arithmetic but a fixed origin, and Textual has one — `absolute_offset`, the
mechanism its own tooltips are placed with, which is in *screen* coordinates and
therefore immune to whatever the container is doing to its children.
"""

from __future__ import annotations

from textual import events
from textual.geometry import Offset
from textual.suggester import SuggestFromList
from textual.widgets import Input, OptionList

#: How tall the list gets, border included — the same number as the `max-height` in
#: the CSS below, and here as well because :meth:`Combo._place` has to know how tall
#: the list will be *before* it can decide which way to open it.
MAX_HEIGHT = 10
#: The round border costs a row at each end.
_BORDER = 2


class Suggestions(OptionList):
    """The list under a Combo. One per Combo, mounted on the screen."""

    DEFAULT_CSS = f"""
    Suggestions {{
        layer: dropdown;
        display: none;
        max-height: {MAX_HEIGHT};
        border: round $accent;
        background: $surface;
        padding: 0;
        scrollbar-size-vertical: 1;
        /* The backstop under `Combo._place`, and the reason a wrong answer there
           can no longer put the list off the screen entirely: whatever we ask for,
           Textual moves it back inside the container before drawing it. */
        constrain: inside;
    }}
    Suggestions.open {{ display: block; }}
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
        question ("what is there?"), not a filter.

        The whole match is returned, not a truncated head of it. The list has a
        fixed on-screen height (`max-height` in the CSS) and a scrollbar, so a long
        answer scrolls rather than growing — and a cap here was invisible in exactly
        the wrong way: the item field holds 369 constants, so a 40-row cap ended the
        offered list at `CHERI_BERRY` and you could scroll to the bottom and never
        learn a `FULL_RESTORE` existed. Typing a letter still narrows it; it is no
        longer the *only* way to reach past the first screenful."""
        needle = text.strip().lower()
        if not needle:
            return list(self._options)
        starts = [o for o in self._options if o.lower().startswith(needle)]
        within = [o for o in self._options
                  if needle in o.lower() and not o.lower().startswith(needle)]
        return starts + within

    @property
    def _open(self) -> bool:
        return self._list.has_class("open")

    def _refilter(self) -> None:
        rows = self.matches(self.value)
        self._list.clear_options()
        self._list.add_options(rows)
        if rows:
            self._list.highlighted = 0
        self._show(bool(rows), len(rows))

    def _show(self, open_: bool, rows: int = 0) -> None:
        self._list.set_class(open_, "open")
        if open_:
            self._place(rows)

    def _place(self, rows: int) -> None:
        """Directly under the input — or directly over it, when under it is off the
        screen.

        `region` is where this box is on the screen right now, scrolling and all,
        which is why the answer is recomputed on every open rather than remembered.

        **In screen coordinates, and that is the whole trick.** `styles.offset`
        would be measured from wherever the layout had already put the list, and
        the form aligns its children centre-middle — so the offset that reads like
        "just under the box" landed the list a half-screen away from it, under the
        form and off its bottom edge. `absolute_offset` is the position, full stop:
        no layout, no alignment, no container between the number and the screen.
        It is how Textual places its own tooltips, for exactly this reason.

        The *direction* is decided here too. A form is a modal in the middle of the
        screen and its last field is a few rows off the bottom edge, so a list that
        always hung downwards hung off the end of the window — and Textual will
        happily position a widget past the viewport and simply not draw the part
        that isn't there. So: below if it fits, above if it doesn't, and whichever
        way has more room if neither does, with the height cut to that room. A list
        that runs off the top is not an improvement on one that runs off the bottom.
        """
        region = self.region
        wanted = min(rows + _BORDER, MAX_HEIGHT)

        below = self.screen.size.height - region.bottom
        above = region.y
        if wanted <= below or below >= above:
            top, room = region.bottom, below
        else:
            top, room = max(0, region.y - wanted), above

        self._list.absolute_offset = Offset(region.x, top)
        self._list.styles.width = region.width
        self._list.styles.max_height = max(_BORDER + 1, min(wanted, room))
        # `absolute_offset` is a plain attribute, not a style: nothing about setting
        # it tells the compositor to arrange anything. A list that is already open
        # and refiltering — same width, same height, new row count — would otherwise
        # keep the position it had when the box it belongs to was somewhere else.
        self._list.refresh(layout=True)

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
        # A form that rebuilds its fields (an object changing kind) unmounts this
        # box. The list lives on the screen, not in the form, so nothing else would
        # ever take it down and it would hang there over the new fields.
        self._list.remove()

    def on_input_changed(self) -> None:
        if self._open:
            self._refilter()

    def on_blur(self) -> None:
        self._show(False)
