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
        "swiftformat": ("swiftformat.strict", ".swiftformat"),
        "swiftlint": ("swiftlint.strict.yml", ".swiftlint.yml"),
        "ktlint": ("ktlint.strict.editorconfig", ".editorconfig"),
        "detekt": ("detekt.strict.yml", "config/detekt/detekt.yml"),
        "mobile-security": ("mobsf.strict.yml", ".mobsf"),
        "markdownlint": ("markdownlint.strict.yaml", ".markdownlint.yaml"),
        "taplo": ("taplo.strict.toml", ".taplo.toml"),
        "yamllint": ("yamllint.strict.yaml", ".yamllint.yaml"),
        "shellcheck": ("shellcheck.strict.rc", ".shellcheckrc"),
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
PYTHON_COMPANION_CONFIGS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        # BasedPyright's source and synchronized forms use the same relative
        # parent name, keeping both inheritance graphs independently valid.
        "pyright-base": ("pyright.strict.json", "pyright.strict.json"),
        # Keep the upstream-Pyright policy warning-free while shipping the
        # stricter active BasedPyright layer beside it.
        "basedpyright": ("basedpyright.strict.json", ".basedpyright-strict.json"),
    }
)
MOBILE_COMPANION_CONFIGS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "mobile-mintfile": ("Mintfile.mobile.strict", "Mintfile.mobile.strict"),
        "mobile-tool-versions": ("mobile-tools.versions.json", "mobile-tools.versions.json"),
    }
)
APPLICATION_CONFIG_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "ruff": "ruff.application.toml",
        "eslint": "eslint.application.mjs",
    }
)
PYTHON_CONFIGS: Final = frozenset({"ruff", "pyright"})
SWIFT_CONFIGS: Final = frozenset({"swiftformat", "swiftlint"})
KOTLIN_CONFIGS: Final = frozenset({"detekt", "ktlint"})
MOBILE_CONFIGS: Final = frozenset({"mobile-security"})
