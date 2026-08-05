"""Compatibility alias for :mod:`sarj_lint_configs.libs.linting.textlint`."""

import sys
from typing import TYPE_CHECKING

from .libs.linting import textlint as _implementation


if TYPE_CHECKING:
    from .libs.linting.textlint import *  # ruff: ignore[undefined-local-with-import-star] -- complete compatibility API.
else:
    sys.modules[__name__] = _implementation
