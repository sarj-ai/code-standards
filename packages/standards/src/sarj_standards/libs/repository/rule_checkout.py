from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import shlex

from sarj_standards.libs.rules import RuleEngine


_AUTHORING_SOURCE = Path("packages/standards/src/sarj_standards/libs/repository/rule_authoring.py")


def ensure_current(
    root: Path,
    arguments: tuple[str, ...],
    *,
    engine: RuleEngine | None = None,
    all_engines: bool = False,
) -> None:
    if not (root / _AUTHORING_SOURCE).is_file():
        return
    packages = {"standards": "sarj_standards", "contracts": "sarj_rule_contracts"}
    for native in (RuleEngine.PYTHON, RuleEngine.SQL, RuleEngine.IAC):
        if all_engines or engine is native:
            packages[native.value] = f"sarj_{native.value}_lint"
    for package, module in packages.items():
        expected = root / f"packages/{package}/src/{module}/__init__.py"
        spec = find_spec(module)
        if spec is not None and spec.origin is not None and Path(spec.origin).resolve() == expected.resolve():
            continue
        invocation = shlex.join(
            (
                "uv",
                "run",
                "--frozen",
                "--project",
                str(root / "packages/standards"),
                "code-standards",
                "--root",
                str(root),
                *arguments,
            )
        )
        msg = f"rule authoring requires the selected checkout's source packages; {module} is loaded from another installation. Run:\n{invocation}"
        raise RuntimeError(msg)
