"""Compatibility alias for :mod:`sarj_lint_configs.libs.adoption.packagemanager`."""

import sys

from .libs.adoption import packagemanager as _implementation
from .libs.adoption.packagemanager import *  # ruff: ignore[undefined-local-with-import-star] — preserve the typed legacy export surface


sys.modules[__name__] = _implementation
