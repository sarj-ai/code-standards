"""Static bundled-config metadata shared by adoption services and adapters."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final


if TYPE_CHECKING:
    from collections.abc import Mapping


CONFIG_NAMES: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "ruff": ("ruff.strict.toml", ".ruff-strict.toml"),
        "pyright": ("pyright.strict.json", ".pyright-strict.json"),
        "eslint": ("eslint.strict.mjs", "eslint.strict.mjs"),
        "markdownlint": ("markdownlint.strict.yaml", ".markdownlint.yaml"),
        "taplo": ("taplo.strict.toml", ".taplo.toml"),
        "yamllint": ("yamllint.strict.yaml", ".yamllint.yaml"),
    }
)

# These files travel with an existing capability instead of adding another
# manifest switch. React Doctor is an advisory companion to the TypeScript
# gate, so every ESLint consumer receives the same data-only configuration.
TYPESCRIPT_COMPANION_CONFIGS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "react-doctor": ("doctor.config.json", "doctor.config.json"),
    }
)
APPLICATION_CONFIG_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "ruff": "ruff.application.toml",
        "eslint": "eslint.application.mjs",
    }
)
PYTHON_CONFIGS: Final = frozenset({"ruff", "pyright"})
