"""sarj-python-lint — custom Python lint rules."""

from sarj_python_lint._ratchet_cli import main as run_ratchet
from sarj_python_lint._version import __version__


__all__ = ["__version__", "run_ratchet"]
