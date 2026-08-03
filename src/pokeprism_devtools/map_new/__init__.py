"""prism-newmap — interactive TUI to author and wire a brand-new map.

`prism-mapfit` "assumes the map content already exists... it does not author
maps" (see docs/devtools.md). This tool fills that gap for a map that doesn't
exist yet: it interactively gathers a `MapSpec` (see `hacks.prism.mapspec`), writes
an empty `maps/<Label>.asm` script/event-header stub, places the supplied
`.blk`/`.ablk` at `maps/blk/<Label>.<ext>`, wires the five asm source files
via `mapfit.mapwire.ALL_ASM_EDITORS`, and saves the resulting spec to
`.devtools/specs/<Label>.toml` so `prism-mapfit add` can pick it up for bank
placement and a verify build.

Out of scope (see docs/devtools.md): creating a brand-new map group,
`connection` lines to neighboring maps, and bank placement/build — all left
to `prism-mapfit`.
"""

from .cli import main
from .template import TEMPLATE, place_blk, write_template

__all__ = ["TEMPLATE", "main", "place_blk", "write_template"]
