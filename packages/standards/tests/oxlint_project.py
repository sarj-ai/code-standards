# Real Oxlint projects for the Standards Oxlint tests.
#
# Fixtures link each package of the TypeScript package's locked
# ``node_modules`` and install the built ``@sarj`` Oxlint plugin from ``dist`` as
# ``@sarj/eslint-plugin``, the specifier the managed config uses.

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING, Final

import pytest

from sarj_standards.libs.adoption.lifecycle import Command
from sarj_standards.libs.linting import oxlint
from sarj_standards.libs.linting.external import DEFAULT_EXECUTOR


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_standards.libs.diagnostics import ToolReport


TYPESCRIPT: Final = Path(__file__).resolve().parents[2] / "typescript"
MODULES: Final = TYPESCRIPT / "node_modules"
OXLINT: Final = MODULES / ".bin" / "oxlint"
PLUGIN: Final = TYPESCRIPT / "dist" / "index.js"
STRICT: Final = """
export function createConfig() {
  return {
    plugins: ["eslint", "typescript", "unicorn", "react", "nextjs"],
    jsPlugins: [
      { name: "@sarj", specifier: "@sarj/eslint-plugin" },
      { name: "unicorn-js", specifier: "eslint-plugin-unicorn" },
    ],
    categories: { correctness: "off" },
    options: { reportUnusedDisableDirectives: "error" },
    rules: {
      "no-debugger": "error",
      "no-console": "error",
      "typescript/no-explicit-any": "error",
      "typescript/no-floating-promises": "error",
      "unicorn-js/no-useless-undefined": "error",
      "@sarj/no-vague-suppression-description": "error",
      "@sarj/directive-require-description": ["error", { ignore: [] }],
    },
  };
}
"""
CONSUMER: Final = 'import { createConfig } from "./oxlint.strict.ts";\nexport default { extends: [createConfig()] };\n'


def require_oxlint() -> None:
    if (
        shutil.which("node") is None
        or not OXLINT.is_file()
        or not (MODULES / ".bin" / "tsrs-lint").is_file()
        or not PLUGIN.is_file()
    ):
        pytest.skip("requires the TypeScript package's built plugin and locked Oxlint toolchain")


def project(root: Path, files: Mapping[str, str], *, config: str = CONSUMER, git: bool = False) -> Path:
    require_oxlint()
    root.mkdir(parents=True, exist_ok=True)
    modules = root / "node_modules"
    modules.mkdir()
    for entry in MODULES.iterdir():
        if entry.name != "@sarj":
            (modules / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
    plugin = modules / "@sarj" / "eslint-plugin"
    plugin.mkdir(parents=True)
    (plugin / "package.json").write_text(
        '{"name":"@sarj/eslint-plugin","type":"module","main":"./index.mjs","exports":"./index.mjs"}\n',
        encoding="utf-8",
    )
    (root / "package.json").write_text('{"type":"module","private":true}\n', encoding="utf-8")
    (root / "tsconfig.json").write_text(
        '{"compilerOptions":{"strict":true,"module":"nodenext","moduleResolution":"nodenext","noEmit":true,'
        '"skipLibCheck":true,"allowImportingTsExtensions":true},"include":["**/*.ts"]}\n',
        encoding="utf-8",
    )
    (plugin / "index.mjs").write_text(
        f"export {{ default }} from {json.dumps(PLUGIN.as_uri())};\n",
        encoding="utf-8",
    )
    (root / "oxlint.strict.ts").write_text(STRICT, encoding="utf-8")
    (root / "oxlint.config.ts").write_text(config, encoding="utf-8")
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if git:
        for argv in (("init", "-q"), ("add", "--", *files)):
            subprocess.run(("git", "-C", str(root), *argv), check=True, capture_output=True)
    return root


def local(command: Command) -> Command:
    argv = tuple(command.argv)
    return Command(command.label, (str(OXLINT), *argv[argv.index("oxlint") + 1 :]), command.cwd)


def environment() -> dict[str, str]:
    return {key: os.environ[key] for key in ("HOME", "PATH") if key in os.environ}  # ruff: ignore[banned-api] -- fixtures pass only the analysis-safe variables.


def commands(root: Path, *paths: str, fix: bool = False) -> tuple[Command, ...]:
    selection = oxlint.select_oxlint_commands(root, paths or (str(root),), fix=fix)
    assert selection.unowned_count == 0
    return tuple(local(command) for command in selection.commands)


def analyze(root: Path, request: oxlint.OxlintRequest, *paths: str) -> ToolReport:
    (command,) = commands(root, *paths)
    return oxlint.run_oxlint(command, root=root, runner=DEFAULT_EXECUTOR, environment=environment(), request=request)


def run_native(command: Command) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command.argv, cwd=command.cwd, env=environment(), capture_output=True, text=True, check=False, timeout=120
    )
