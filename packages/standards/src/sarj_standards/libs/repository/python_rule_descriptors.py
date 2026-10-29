from __future__ import annotations

import ast
from contextlib import redirect_stdout
from dataclasses import dataclass
from importlib.util import find_spec
from io import StringIO
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Annotated, Final

import typer

from sarj_standards.libs.adoption import transaction
from sarj_standards.libs.linting.external import run_process
from sarj_standards.libs.repository import rule_checkout
from sarj_standards.libs.rules import RuleEngine


if TYPE_CHECKING:
    from collections.abc import Callable

    from sarj_standards.libs.repository.rule_inventory_artifact import RuleInventoryEntry


DESCRIPTOR_PATH: Final = Path("packages/python/src/sarj_python_lint/_rule_descriptors.py")
_REGISTRY_PATH: Final = Path("packages/python/src/sarj_python_lint/rules/_registry.py")
_RUNTIME_PATH: Final = Path("packages/python/src/sarj_python_lint/rules/_runtime_registry.py")
_MODULE: Final = "sarj_standards.libs.repository.python_rule_descriptors"


@dataclass(frozen=True, slots=True)
class DescriptorPlan:
    path: Path
    before: bytes | None


@dataclass(frozen=True, slots=True)
class DescriptorSyncResult:
    status: int
    message: str


def enabled(root: Path) -> bool:
    registry = root / _REGISTRY_PATH
    try:
        tree = ast.parse(registry.read_text(encoding="utf-8"), filename=str(registry))
    except FileNotFoundError:
        tree = ast.Module(body=[], type_ignores=[])
    named_authoring = False
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "_AUTHORING_REGISTRY" for target in targets):
            continue
        named_authoring = True
        if (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "MappingProxyType"
            and len(node.value.args) == 1
            and isinstance(node.value.args[0], ast.Dict)
        ):
            return True
    if named_authoring or _present(root / _RUNTIME_PATH) or _present(root / DESCRIPTOR_PATH):
        msg = f"Python descriptor registry has no literal independent authoring table: {registry}"
        raise ValueError(msg)
    return False


def _present(path: Path) -> bool:
    try:
        path.stat()
    except FileNotFoundError:
        return False
    return True


def plan(root: Path) -> DescriptorPlan | None:
    if not enabled(root):
        return None
    destination = root / DESCRIPTOR_PATH
    try:
        before = destination.read_bytes()
    except FileNotFoundError:
        before = None
    return DescriptorPlan(destination, before)


def _validate_module(source: str, destination: Path) -> None:
    tree = ast.parse(source, filename=str(destination))
    schema = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SCHEMA_VERSION" for target in node.targets)
    ]
    descriptors = [
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "DESCRIPTORS"
    ]
    schema_valid = not (
        len(schema) != 1
        or not isinstance(schema[0], ast.Constant)
        or type(schema[0].value) is not int
        or schema[0].value != 1
    )
    if (
        not schema_valid
        or len(descriptors) != 1
        or not isinstance(descriptors[0], ast.Tuple)
        or not all(
            isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "RuleDescriptor"
            for item in descriptors[0].elts
        )
    ):
        msg = "Python descriptor oracle returned incompatible module exports"
        raise ValueError(msg)
    compile(source, str(destination), "exec", dont_inherit=True)


def emit(root: Path) -> str:
    repository = root.resolve()
    rule_checkout.ensure_current(repository, ("maintain", "rules", "sync"), engine=RuleEngine.PYTHON)
    from sarj_python_lint import rule_metadata  # ruff: ignore[import-outside-top-level] -- generation owns loading the selected source package.

    expected = repository / "packages/python/src/sarj_python_lint/rule_metadata.py"
    if Path(rule_metadata.__file__).resolve() != expected.resolve():
        msg = f"Python descriptor generation requires the selected checkout's metadata owner: {expected}"
        raise RuntimeError(msg)
    oracle = find_spec("sarj_python_lint.rules._registry")
    if (
        oracle is None
        or oracle.origin is None
        or Path(oracle.origin).resolve() != (repository / _REGISTRY_PATH).resolve()
    ):
        msg = "Python descriptor generation requires the selected checkout's independent registry oracle"
        raise RuntimeError(msg)
    noise = StringIO()
    with redirect_stdout(noise):
        rendered = rule_metadata.render_authored_descriptors()
    if noise.getvalue():
        msg = "Python registry oracle wrote unexpected output during descriptor generation"
        raise ValueError(msg)
    _validate_module(rendered, repository / DESCRIPTOR_PATH)
    return rendered


def render(root: Path) -> str:
    repository = root.resolve()
    completed = run_process(
        (sys.executable, "-I", "-m", _MODULE, "--emit", "--root", str(repository)),
        cwd=repository,
        timeout_seconds=120,
    )
    if completed.returncode != 0:
        msg = f"Python descriptor oracle failed with exit code {completed.returncode}: {completed.stderr}"
        raise RuntimeError(msg)
    _validate_module(completed.stdout, repository / DESCRIPTOR_PATH)
    return completed.stdout


def authoring_inventory(root: Path) -> list[RuleInventoryEntry]:
    source = render(root)
    tree = ast.parse(source)
    table = next(
        (
            node.value
            for node in tree.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "DESCRIPTORS"
        ),
        None,
    )
    if not isinstance(table, ast.Tuple):
        msg = "Python descriptor oracle did not return a literal descriptor table"
        raise TypeError(msg)
    entries: list[RuleInventoryEntry] = []
    for descriptor in table.elts:
        if not isinstance(descriptor, ast.Call):
            msg = "Python descriptor oracle did not return literal descriptor records"
            raise TypeError(msg)
        module = _literal_field(descriptor, "module").replace(".", "/")
        name = module.rsplit("/", maxsplit=1)[-1]
        entries.append(
            {
                "family": "python",
                "id": _literal_field(descriptor, "rule_id"),
                "code": _literal_field(descriptor, "code"),
                "source": f"packages/python/src/{module}.py",
                "test": f"packages/python/tests/rules/test_{name}.py",
            }
        )
    return entries


def _literal_field(descriptor: ast.Call, name: str) -> str:
    value = next((keyword.value for keyword in descriptor.keywords if keyword.arg == name), None)
    if name == "rule_id":
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "RuleId"
            and len(value.args) == 1
            and not value.keywords
        ):
            msg = "Python descriptor oracle did not return a literal RuleId constructor"
            raise ValueError(msg)
        value = value.args[0]
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        msg = f"Python descriptor oracle did not return a literal {name} field"
        raise TypeError(msg)
    return value.value


def sync(root: Path, *, check: bool, writer: Callable[[Path, str], None] | None = None) -> DescriptorSyncResult:
    repository = root.resolve()
    pending = plan(repository)
    if pending is None:
        return DescriptorSyncResult(0, "ok: Python registry does not use generated descriptors")
    expected = render(repository)
    if pending.before == expected.encode("utf-8"):
        return DescriptorSyncResult(0, "ok: Python rule descriptors match the independent authoring registry")
    if check:
        return DescriptorSyncResult(
            1, "drift: Python rule descriptors differ; run `code-standards maintain rules sync`"
        )
    transaction.assert_expected(repository, pending.path, pending.before)
    if writer is None:
        transaction.atomic_write_text(repository, pending.path, expected)
    else:
        writer(pending.path, expected)
    return DescriptorSyncResult(0, "updated: Python rule descriptors")


def main() -> int:
    app = typer.Typer(
        add_completion=False,
        pretty_exceptions_enable=False,
        context_settings={"help_option_names": ["-h", "--help"]},
    )

    @app.command(help="Check or regenerate Python rule descriptors from their source owner.")
    def run(
        *,
        root: Annotated[Path, typer.Option("--root")] = Path(),
        emit_source: Annotated[bool, typer.Option("--emit")] = False,
        check: Annotated[bool, typer.Option("--check")] = False,
        synchronize: Annotated[bool, typer.Option("--sync")] = False,
    ) -> None:
        if (emit_source, check, synchronize).count(True) != 1:
            msg = "choose exactly one of --emit, --check or --sync"
            raise typer.BadParameter(msg)
        if emit_source:
            sys.stdout.write(emit(root))
            return
        result = sync(root, check=check)
        sys.stdout.write(result.message + "\n")
        raise typer.Exit(result.status)

    try:
        app()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
