"""Thin module entry point with a compatibility alias to the CLI adapter."""

from importlib import import_module
import sys
from typing import TYPE_CHECKING

from ._meta import CONFIGS_DIR
from .cli.main import cmd_doctor as _cmd_doctor
from .cli.main import main


if TYPE_CHECKING:
    from types import ModuleType


cmd_doctor = _cmd_doctor
__all__ = ["CONFIGS_DIR", "cmd_doctor", "main"]


_cli: ModuleType = import_module(".cli.main", __package__)

if __name__ == "__main__":
    raise SystemExit(main())

# Preserve the historical ``sarj_lint_configs.__main__`` module surface so
# monkeypatches and imports keep targeting the real CLI module during migration.
sys.modules[__name__] = _cli
