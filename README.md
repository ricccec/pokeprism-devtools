# pokeprism-devtools

Adds [Pokémon Prism](https://www.pokemonprism.com/) support to
[Crystal Studio](https://github.com/ricccec/crystal-studio), plus Prism's own
command-line tools.

Prism's disassembly is not a pokecrystal fork in the places that matter — its map
format, its event-flag scheme, its text engine and its sprite handling all differ.
This package is the adapter that teaches the studio to read and write that tree,
and nine commands that work on it directly.

## Install

```bash
pip install pokeprism-devtools
```

Requires Python 3.10 or newer. Installing it alongside `crystal-studio` is what
makes the IDE recognise a Prism checkout; the adapter registers itself through
the `crystal_studio.plugins` entry-point group, with no configuration.

## The commands

```bash
prism-maps                 # list the maps, with their headers
prism-map      MAP         # one map: header, connections, objects, events
prism-mapview  MAP         # render it as blocks
prism-gfx      FILE        # view a graphics file
prism-newmap               # scaffold a new map, wired into the tree
prism-mapfit   MAP         # does it still fit its bank
prism-metatiles            # the tileset's metatile definitions
prism-maplint              # lint the maps, with Prism's own rules
prism-dev                  # build, patch a save, and boot
```

`docs/devtools.md` is the reference. Three further commands — `pret-sym`,
`pret-usage` and `crystal-studio` — arrive with the two packages this one depends
on, and are documented there.

## The namespace

The import name is `pretkit`, a [PEP 420][pep420] namespace package shared with
`pret-toolkit`, `crystal-studio-plugin-api` and `crystal-studio`. This package
imports the toolkit and the plugin API. It does **not** import `crystal-studio`:
an adapter must never reach up into the IDE, which is the whole point of the
plugin seam, and a test in the integration repo asserts it across distributions.

[pep420]: https://peps.python.org/pep-0420/

## Tests

```bash
python scripts/run-tests.py
```

Plain scripts, not pytest: each prints `ok`/`FAIL` lines and exits non-zero.

Many read a **real Prism checkout** rather than a fixture. Point the suite at
yours with `POKEPRISM_TREE`, or check it out somewhere conventional
(`~/code/pokeprism`, `~/src/pokeprism`, or one grouping directory below either).
Without it those checks are reported as skipped rather than passed, and the
runner counts them so a green run cannot hide an empty one.

A test that fails because of an edit in *your* game tree is a fact about your
checkout, not about this repository: record it in `.known-red.json`, which is
git-ignored. `KNOWN_RED` in the runner is for failures true in every clone, and
is empty.

## Licence

MIT. See `LICENSE`.
