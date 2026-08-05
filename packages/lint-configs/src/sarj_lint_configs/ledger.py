"""Compatibility alias for :mod:`sarj_lint_configs.libs.repository.ledger`."""

import sys
from typing import TYPE_CHECKING

from .libs.repository import ledger as _implementation


if TYPE_CHECKING:
    from .libs.repository.ledger import *  # ruff: ignore[undefined-local-with-import-star] -- complete compatibility API.
else:
    sys.modules[__name__] = _implementation
