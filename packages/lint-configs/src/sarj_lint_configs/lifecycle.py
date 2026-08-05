"""Compatibility alias for :mod:`sarj_lint_configs.libs.adoption.lifecycle`."""

import sys

from .libs.adoption import lifecycle as _implementation
from .libs.adoption.lifecycle import *  # ruff: ignore[undefined-local-with-import-star] — preserve the typed legacy export surface


sys.modules[__name__] = _implementation
