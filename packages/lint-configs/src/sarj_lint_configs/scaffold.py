"""Compatibility alias for :mod:`sarj_lint_configs.libs.adoption.scaffold`."""

import sys

from .libs.adoption import scaffold as _implementation
from .libs.adoption.scaffold import *  # ruff: ignore[undefined-local-with-import-star] — preserve the typed legacy export surface


sys.modules[__name__] = _implementation
