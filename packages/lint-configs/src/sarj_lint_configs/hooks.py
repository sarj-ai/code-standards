"""Compatibility alias for :mod:`sarj_lint_configs.libs.repository.hooks`."""

import sys
from typing import TYPE_CHECKING

from .libs.repository import hooks as _implementation


if TYPE_CHECKING:
    from .libs.repository.hooks import *  # ruff: ignore[undefined-local-with-import-star] -- complete compatibility API.
else:
    sys.modules[__name__] = _implementation
