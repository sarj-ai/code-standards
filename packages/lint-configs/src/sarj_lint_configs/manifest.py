"""Compatibility alias for :mod:`sarj_lint_configs.libs.adoption.manifest`."""

import sys

from .libs.adoption import manifest as _implementation
from .libs.adoption.manifest import *  # ruff: ignore[undefined-local-with-import-star] — preserve the typed legacy export surface


sys.modules[__name__] = _implementation
