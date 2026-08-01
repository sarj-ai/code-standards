"""Resolve the installed package version, with a source-tree fallback."""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("sarj-python-lint")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"
