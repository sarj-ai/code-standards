from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


try:
    __version__ = version("sarj-standards")
except PackageNotFoundError:  # running from an uninstalled source tree
    __version__ = "0.0.0.dev0"

CONFIGS_DIR: Path = Path(__file__).resolve().parent / "configs"

RUFF_STRICT: Path = CONFIGS_DIR / "ruff.strict.toml"
RUFF_APPLICATION: Path = CONFIGS_DIR / "ruff.application.toml"
PYRIGHT_STRICT: Path = CONFIGS_DIR / "pyright.strict.json"
ESLINT_STRICT: Path = CONFIGS_DIR / "eslint.strict.mjs"
ESLINT_APPLICATION: Path = CONFIGS_DIR / "eslint.application.mjs"
MARKDOWNLINT_STRICT: Path = CONFIGS_DIR / "markdownlint.strict.yaml"
ESLINT_PEERS: Path = CONFIGS_DIR / "eslint.peers.json"
TAPLO_STRICT: Path = CONFIGS_DIR / "taplo.strict.toml"
YAMLLINT_STRICT: Path = CONFIGS_DIR / "yamllint.strict.yaml"
