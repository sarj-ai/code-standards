"""Resolve the installed package version, falling back for source trees."""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("sarj-sql-lint")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"
