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
pip install git+https://github.com/ricccec/pret-toolkit \
            git+https://github.com/ricccec/crystal-studio-api \
            git+https://github.com/ricccec/pokeprism-devtools
```

Not on PyPI yet. Every dependency in this family is named by URL in the
same command, which is how pip finds the ones PyPI does not have.
Add `git+https://github.com/ricccec/crystal-studio` to the same command to get the IDE.

Requires Python 3.11 or newer. Installing it alongside `crystal-studio` is what
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

## The package

The import name is `pokeprism_devtools`: the adapter and Prism's data model in
`pokeprism_devtools.prism`, and one package per command beside it. It imports
`pret_toolkit` and `crystal_studio_api`. It does **not** import
`crystal_studio`: an adapter must never reach up into the IDE, which is the
whole point of the plugin seam.

## Tests

```bash
pret-test               # the whole suite, against the pinned game trees
pret-test --worktree    # the same, against your own checkouts, edits and all
```

Plain scripts, not pytest: each prints `ok`/`FAIL` lines and exits non-zero.
`pret-test` ships with `pret-toolkit`, so it is on `$PATH` once this repo is
installed; run it from anywhere inside the repo.

Many read a **real Prism tree** rather than a fixture, because what is being checked
is whether the reader agrees with an actual tree.
Each tree is pinned to the one commit the tests were written against, in
`pyproject.toml` under `[tool.pret-test.upstreams]`:

- `pokeprism` — Pokémon Prism v0.95.0254, [ricccec/pokeprism](https://github.com/ricccec/pokeprism) at `aafe54a`
- `pokecrystal` — [pret/pokecrystal](https://github.com/pret/pokecrystal) at `31880ea`

`pret-test` checks out a clean copy of each pinned commit into
`~/.cache/pret-toolkit/` — taken from your own checkout when it has the commit, from
the URL otherwise — so neither your edits nor your branch change the result.
Your checkout is found the way every command here finds one: `$<NAME>_TREE`
(`$POKECRYSTAL_TREE`, say), or a conventional place such as `~/code/<name>`.
`pret-test --fetch` fetches them and prints where they are. The copies hold no
build output, so checks that need a ROM skip until you run `make` in one. A
skipped check is counted and reported rather than passed, and `--strict` fails
the run on one.

`--worktree` is for seeing what your own edits do. A test that fails there
because of an edit in *your* tree is a fact about your checkout: record it in
`.known-red.json`, which is git-ignored and counts only in `--worktree` runs.

## Credits

Pokémon Prism is developed by [RainbowDevs](https://rainbowdevs.com). This
package is an independent tool for working on its disassembly, and is not
affiliated with or endorsed by RainbowDevs.

Not affiliated with or endorsed by Nintendo, Game Freak, Creatures or The
Pokémon Company. Pokémon is a trademark of Nintendo.

## Licence

MIT. See `LICENSE`.
