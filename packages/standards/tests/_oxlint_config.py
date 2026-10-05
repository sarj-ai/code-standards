from __future__ import annotations

from functools import cache
import json
from pathlib import Path
import subprocess

from sarj_standards.libs.adoption import manifest


@cache
def native_configuration(*, all_frameworks: bool = False) -> dict[str, object]:
    repository = Path(__file__).resolve().parents[3]
    module = repository / "packages/typescript/dist/config.js"
    assert module.is_file(), "run npm run build in packages/typescript before testing bundled policy"
    framework_options = (
        ",testFrameworks:['vitest','node','bun','testing-library','playwright']" if all_frameworks else ""
    )
    script = (
        f"import {{ createStrictOxlintConfig }} from {json.dumps(module.as_uri())};"
        f"console.log(JSON.stringify({{policy:await createStrictOxlintConfig({{root:process.cwd(){framework_options}}})}}));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    raw: object = json.loads(result.stdout)  # pyright: ignore[reportAny] -- immediately narrowed native tool boundary
    return manifest.as_table(raw)


def native_policy(*, all_frameworks: bool = False) -> dict[str, object]:
    return manifest.table_field(native_configuration(all_frameworks=all_frameworks), "policy")


def native_rules() -> dict[str, object]:
    return manifest.table_field(native_policy(), "rules")
