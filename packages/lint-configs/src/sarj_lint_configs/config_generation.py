"""Compatibility alias for :mod:`sarj_lint_configs.libs.repository.config_generation`."""

import sys
from typing import TYPE_CHECKING

from .libs.repository import config_generation as _implementation


if TYPE_CHECKING:
    from .libs.repository.config_generation import *  # ruff: ignore[undefined-local-with-import-star] -- complete compatibility API.
else:
    sys.modules[__name__] = _implementation
