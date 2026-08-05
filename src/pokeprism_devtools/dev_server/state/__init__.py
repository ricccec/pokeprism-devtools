"""The editors for each section of `state.json`, one file per section.

`dev_server/apply.py` already splits the same state the same way — a writer per
section — and these are the read-and-edit half of it. Each is a mixin on
`DevServer`, the pattern `studio/flow.py` uses on `Studio`: the split is a size,
not a boundary, and every editor still reaches `self.state`, `self.inv` and
`self._save_state()` on the server it is mixed into.
"""

from .bag import BagMenu
from .flags import FlagMenu
from .party import PartyMenu
from .player import PlayerMenu
from .position import PositionMenu
from .presets import PresetMenu
from .tmhms import TmhmMenu

__all__ = ["BagMenu", "FlagMenu", "PartyMenu", "PlayerMenu", "PositionMenu",
           "PresetMenu", "TmhmMenu"]
