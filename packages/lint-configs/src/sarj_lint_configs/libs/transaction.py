"""Compatibility alias for :mod:`sarj_lint_configs.libs.adoption.transaction`."""

import sys

from .adoption import transaction as _implementation
from .adoption.transaction import *  # ruff: ignore[undefined-local-with-import-star] — preserve the typed legacy export surface


sys.modules[__name__] = _implementation
