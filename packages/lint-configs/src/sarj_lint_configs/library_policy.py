"""Compatibility alias for :mod:`sarj_lint_configs.libs.linting.library_policy`."""

import sys
from typing import TYPE_CHECKING

from .libs.linting import library_policy as _implementation


if TYPE_CHECKING:
    from .libs.linting.library_policy import *  # ruff: ignore[undefined-local-with-import-star] -- complete compatibility API.
else:
    sys.modules[__name__] = _implementation
