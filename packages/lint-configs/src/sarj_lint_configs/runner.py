"""Compatibility alias for :mod:`sarj_lint_configs.libs.linting.runner`."""

import sys
from typing import TYPE_CHECKING

from .libs.linting import runner as _implementation


if TYPE_CHECKING:
    from .libs.linting.runner import *  # ruff: ignore[undefined-local-with-import-star] -- compatibility facade mirrors the complete historical API.
else:
    sys.modules[__name__] = _implementation
