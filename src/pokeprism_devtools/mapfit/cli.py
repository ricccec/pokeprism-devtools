"""The `prism-mapfit` command line."""

from __future__ import annotations

import argparse
import sys

from ..hacks.prism.mapspec import BLOBS
from ..shared import paths
from . import mapwire
from .commands import cmd_add, cmd_consolidate, cmd_plan


def _bank(raw: str) -> int:
    """A bank number, decimal or $/0x hex."""
    text = raw.strip().lower().replace("$", "0x")
    try:
        return int(text, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a bank number") from None

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="prism-mapfit",
        description="Find ROM banks for a new map and wire it in.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--spec", required=True, metavar="FILE", help="map spec .toml")
    common.add_argument("--script-size", type=int, metavar="N",
                        help="script/event section size in bytes (skip the measurement build)")
    common.add_argument("--margin", type=int, default=16, metavar="N",
                        help="bytes of slack to reserve per bank (default: 16)")
    common.add_argument("--map", metavar="PATH", help="override the baseline .map file")
    for blob in BLOBS:
        common.add_argument(
            f"--{blob}-into", metavar="SECTION",
            help=f"append the {blob} into this existing SECTION, inheriting its "
                 f"bank (no romx.link pin)")
        common.add_argument(
            f"--{blob}-bank", metavar="BANK", type=_bank,
            help=f"give the {blob} its own SECTION pinned to this bank "
                 f"(e.g. 0x4d), instead of letting the packer choose")

    pp = sub.add_parser("plan", parents=[common], help="show the bank placement, write nothing")
    pp.add_argument("--park", action="store_true",
                    help="worst-fit into the biggest chunk (for a still-growing map)")
    pp.set_defaults(func=cmd_plan)

    pa = sub.add_parser("add", parents=[common], help="wire the map in and build")
    pa.add_argument("--park", action="store_true",
                    help="worst-fit into the biggest free chunk (empty high bank) so a "
                         "still-growing map has maximum headroom; off = tight best-fit")
    pa.add_argument("--dry-run", action="store_true", help="print edits without writing")
    pa.add_argument("--no-build", action="store_true", help="wire + pin but skip builds")
    pa.set_defaults(func=cmd_add)

    pc = sub.add_parser("consolidate",
                        help="tightly re-pack several already-built maps, freeing parked banks")
    pc.add_argument("--spec", required=True, action="append", metavar="FILE",
                    help="map spec .toml (repeat for each map to consolidate)")
    pc.add_argument("--blobs", metavar="KINDS", default=None,
                    help="comma list of blob kinds to move: script,blk,secondary "
                         "(default: all). e.g. --blobs blk to relocate only block data")
    pc.add_argument("--margin", type=int, default=16, metavar="N",
                    help="bytes of slack to reserve per bank (default: 16)")
    pc.add_argument("--map", metavar="PATH", help="override the baseline .map file")
    pc.add_argument("--dry-run", action="store_true", help="print the plan without writing")
    pc.add_argument("--no-build", action="store_true", help="re-pin but skip the verify build")
    pc.set_defaults(func=cmd_consolidate)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (paths.RepoNotFound, FileNotFoundError, ValueError, mapwire.WiringError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
