"""Which hack is this tree. **The mount point.**

This is the one module allowed to know that hacks exist at all — and it knows
them only as a registry of names it asks in turn, never by branching on one.
What a hack must *answer* once mounted is the `contract/` package, which knows
no names; how a
hack recognises its own tree is `hacks/<name>/claim.py`, which knows only its
own. This module owns the space between: discover the registered adapters, ask
each whether it claims this tree, and turn the answers into one mounted
:class:`~..contract.Hack` or one :class:`UnknownTree` that says why none did.

Recognition is inverted on purpose. An earlier mount recognised every tree
itself — a prism-layout check, then a family-anchor probe that knew both
vanilla's `_MapEvents` tail and polished's `_MapScriptHeader` head. That probe
was shared knowledge no third-party adapter could join or correct, a third
category between "a hack" and "hack-agnostic". Now each hack answers for itself:
`claims(root)` returns the built adapter, nothing, or a :class:`NearMiss` with a
reason, and this loop only counts the claims and collects the reasons.

Registration is entry points (`[project.entry-points."pokeprism_devtools.hacks"]`
in `pyproject.toml`), so the three in-tree hacks register through the identical
path a `pip install`ed third-party adapter would — the only way to learn whether
the plugin seam works before someone depends on it. `--hack-path` (`hack_path`
here) loads one more from a file, for an author iterating on a tree who would
rather not reinstall between runs.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..contract import Hack

_GROUP = "pokeprism_devtools.hacks"


class UnknownTree(RuntimeError):
    """No registered adapter claimed this tree. The message gathers what each
    one *looked for*, because "unknown" is not actionable and "no map file ends
    with _MapEvents, and no maps/second_map_headers.asm either" is."""


@dataclass(frozen=True)
class NearMiss:
    """A hack's "almost": it looked at this tree, did not claim it, and this is
    why. Owned by the hack that produced it — the reason is that hack's own words
    about its own layout — and collected here only to build an
    :class:`UnknownTree` when nothing claims. `hack` names the speaker, so two
    near-misses read as two voices rather than one committee-authored sentence."""
    hack: str
    reason: str


def mount(root: Path, hack_path: Path | None = None) -> Hack:
    """The adapter that claims this tree, or :class:`UnknownTree`, loudly.

    Loud on purpose, and measured: before this gate existed, five of the eight
    prism parsers failed *silently* on a pokecrystal checkout (`None`, `[]`,
    `{}`), so the studio opened on one and reported an empty repo with a
    straight face. An error that names the tree beats a session that swears the
    repo has no maps in it.

    Every registered adapter is asked, not just the first to match: two hacks
    claiming one tree is a bug in one of them, and saying so beats letting
    whichever sorted first win in silence. Each is asked inside its own
    `try`/`except`, because the moment an adapter this repo did not write can run
    here it can also raise — and one broken adapter should degrade to a
    near-miss, not take discovery down with it.
    """
    claimed: list[Hack] = []
    missed: list[NearMiss] = []
    for name, load in _get_registered_hacks(hack_path):
        try:
            answer = load()(root)
        except Exception as exc:  # a third-party adapter is now in the loop
            missed.append(NearMiss(
                name, f"could not answer: {type(exc).__name__}: {exc}"))
            continue
        if isinstance(answer, Hack):
            claimed.append(answer)
        elif isinstance(answer, NearMiss):
            missed.append(answer)

    if len(claimed) == 1:
        return claimed[0]
    if len(claimed) > 1:
        names = ", ".join(sorted(h.name for h in claimed))
        raise UnknownTree(
            f"{root} is claimed by more than one adapter ({names}). Two hacks "
            "recognising one tree is a bug in one of them, so discovery stops "
            "here rather than mount whichever happened to sort first.")
    raise UnknownTree(_explain_no_claim(root, missed))


def _explain_no_claim(root: Path, missed: list[NearMiss]) -> str:
    """The message when nothing claimed: every near-miss, by hack, sorted for a
    stable read. Empty only when no adapter is registered at all, which is its
    own kind of broken and says so instead of blaming the tree."""
    if not missed:
        return (f"no adapter is registered under the {_GROUP!r} entry-point "
                f"group, so nothing could even look at {root} — the install is "
                "incomplete (reinstall the package).")
    reasons = "; ".join(f"{m.hack} {m.reason}"
                        for m in sorted(missed, key=lambda m: m.hack))
    return f"{root} is a tree no adapter claims: {reasons}."


def _get_registered_hacks(
        hack_path: Path | None) -> list[tuple[str, Callable[[], Callable]]]:
    """Each registered adapter as `(name, load)`, sorted by name for stable
    messages. `load()` imports the adapter and returns its `claims` — deferred,
    so enumerating the registry imports no reader, writer or linter, only the
    predicate that gets asked. A `--hack-path` override replaces the entry point
    of the same name, which is how an author iterates on `prism` without
    reinstalling over the installed one."""
    reg: dict[str, Callable[[], Callable]] = {}
    for ep in importlib.metadata.entry_points(group=_GROUP):
        reg[ep.name] = lambda ep=ep: getattr(ep.load(), "claims")
    if hack_path is not None:
        name, load = _load_hack_from_path(Path(hack_path))
        reg[name] = load
    return sorted(reg.items())


def _load_hack_from_path(path: Path) -> tuple[str, Callable[[], Callable]]:
    """A `--hack-path` adapter, loaded from a file rather than the registry: the
    `claim.py` inside a directory, or the file itself, named for its package so
    an override of `prism` replaces prism. Loaded this way it has no package to
    hang a relative import on, so the module must reach the contract by its
    installed name (`pokeprism_devtools.contract`) — the package a third-party
    adapter depends on anyway."""
    claim = path / "claim.py" if path.is_dir() else path
    name = claim.parent.name if claim.name == "claim.py" else claim.stem

    def load() -> Callable:
        spec = importlib.util.spec_from_file_location(f"_hack_path_{name}", claim)
        if spec is None or spec.loader is None:
            raise ImportError(f"{claim} is not an importable Python module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "claims")

    return name, load
