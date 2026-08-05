"""Compatibility alias for :mod:`sarj_lint_configs.libs.adoption.upgrade`."""

import sys

from .libs.adoption import upgrade as _implementation
from .libs.adoption.upgrade import *  # ruff: ignore[undefined-local-with-import-star] — preserve the typed legacy export surface


sys.modules[__name__] = _implementation
