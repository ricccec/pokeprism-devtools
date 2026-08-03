"""Terminal table of per-map metadata for pokeprism.

Usage:  prism-maps [OPTIONS]
Run from anywhere inside the pokeprism checkout. No ROM required.
"""

from .cli import main
from .mapinfo import MapInfo, collect
from .table import render_table

__all__ = ["MapInfo", "collect", "main", "render_table"]
