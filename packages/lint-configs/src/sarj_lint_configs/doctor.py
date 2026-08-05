"""Compatibility alias for :mod:`sarj_lint_configs.libs.adoption.doctor`."""

import sys

from .libs.adoption import doctor as _implementation
from .libs.adoption.doctor import *  # ruff: ignore[undefined-local-with-import-star] — preserve the typed legacy export surface


sys.modules[__name__] = _implementation
