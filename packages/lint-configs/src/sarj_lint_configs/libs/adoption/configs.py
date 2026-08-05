"""Static bundled-config metadata shared by adoption services and adapters."""

from typing import Final


CONFIG_NAMES: Final[dict[str, tuple[str, str]]] = {
    "ruff": ("ruff.strict.toml", ".ruff-strict.toml"),
    "pyright": ("pyright.strict.json", ".pyright-strict.json"),
    "eslint": ("eslint.strict.mjs", "eslint.strict.mjs"),
    "markdownlint": ("markdownlint.strict.yaml", ".markdownlint.yaml"),
    "taplo": ("taplo.strict.toml", ".taplo.toml"),
    "yamllint": ("yamllint.strict.yaml", ".yamllint.yaml"),
}
APPLICATION_CONFIG_NAMES: Final[dict[str, str]] = {
    "ruff": "ruff.application.toml",
    "eslint": "eslint.application.mjs",
}
PYTHON_CONFIGS: Final = frozenset({"ruff", "pyright"})
