"""Compatibility alias for :mod:`sarj_lint_configs.libs.repository.repository`."""

import sys
from typing import TYPE_CHECKING

from .libs.repository import repository as _implementation


if TYPE_CHECKING:
    from .libs.repository.repository import *  # ruff: ignore[undefined-local-with-import-star] -- complete compatibility API.
else:
    sys.modules[__name__] = _implementation
