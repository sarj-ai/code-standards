"""Compatibility alias for :mod:`sarj_lint_configs.libs.repository.rule_maintenance`."""

import sys
from typing import TYPE_CHECKING

from .libs.repository import rule_maintenance as _implementation


if TYPE_CHECKING:
    from .libs.repository.rule_maintenance import *  # ruff: ignore[undefined-local-with-import-star] -- complete compatibility API.
else:
    sys.modules[__name__] = _implementation
