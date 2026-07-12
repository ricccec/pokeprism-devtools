"""The modal screens: everything that stands between you and a write.

A directory rather than a convention, because the rule these files live under is
worth being able to *see*: **nothing in here reads the repo.** Every byte they
draw arrives from `Session` as plain data, and every change they make leaves
through an `Action` whose fields they render without knowing what any of them
mean. `tests/test_studio_tui.py::TestTheSeam` walks this package and `app.py`,
`tabs.py` and `grid.py` with an AST and fails the build if one of them imports a
parser. The rule is one convenient import away from being a comment.
"""

from .build import Build
from .confirm import Confirm
from .forms import Form, Picker
from .history import History
from .lint import Findings

__all__ = ["Build", "Confirm", "Findings", "Form", "History", "Picker"]
