"""Compatibility alias for :mod:`sarj_lint_configs.libs.repository.comment_corpus`."""

import sys
from typing import TYPE_CHECKING

from .libs.repository import comment_corpus as _implementation


if TYPE_CHECKING:
    from .libs.repository.comment_corpus import *  # ruff: ignore[undefined-local-with-import-star] -- complete compatibility API.
else:
    sys.modules[__name__] = _implementation
