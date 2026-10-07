from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import time
import tomllib
from typing import TYPE_CHECKING, Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, JsonValue, RootModel
import typer

from sarj_standards.libs.release.process import ProcessFailureError, ProcessRunner, run_process


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


_MAX_JOBS = 16
_PARALLEL_FILE_THRESHOLD = 8
_PACKAGE = "packages/standards"
_SOURCE = f"{_PACKAGE}/src/sarj_standards/"
_LOCAL_NAMES = frozenset(
    {"code-standards", "sarj-standards", "sarj-python-lint", "sarj-sql-lint", "sarj-iac-lint", "sarj-rule-contracts"}
)
_SMOKE = frozenset({"test_smoke.py", "test_cli_startup.py", "test_architecture.py", "test_supply_chain.py"})
_RULE_INTEGRATION = frozenset(
    {
        "test_api.py",
        "test_runner.py",
        "test_engine_invariants.py",
        "test_external_diagnostics.py",
        "test_selected_eslint_execution.py",
    }
)


class _Document(RootModel[dict[str, JsonValue]]):
    pass


class TestPlan(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    full: bool
    reason: str
    changed_files: tuple[str, ...]
    tests: tuple[str, ...]
    total_files: int


def _metadata(source: str, path: str) -> _Document:
    value: object = tomllib.loads(source)
    document = _Document.model_validate(value)
    if path == ".sarj-standards.toml":
        document.root.pop("bundle", None)
    _strip_project_version(document.root.get("project"))
    _strip_local_lock_versions(document.root.get("package"))
    return document


def _strip_project_version(project: JsonValue) -> None:
    if not isinstance(project, dict):
        return
    project.pop("version", None)
    dependencies = project.get("dependencies")
    if isinstance(dependencies, list):
        project["dependencies"] = [_without_local_pin(item) for item in dependencies]


def _without_local_pin(item: JsonValue) -> JsonValue:
    if isinstance(item, str) and item.split("==", 1)[0] in _LOCAL_NAMES:
        return re.sub(r"==[0-9]+(?:\.[0-9]+)*$", "", item)
    return item


def _strip_local_lock_versions(packages: JsonValue) -> None:
    if not isinstance(packages, list):
        return
    for package in packages:
        if not isinstance(package, dict) or package.get("name") not in _LOCAL_NAMES:
            continue
        local_source = package.get("source")
        if isinstance(local_source, dict) and "editable" in local_source:
            package.pop("version", None)


def _metadata_only(root: Path, base: str, path: str, runner: ProcessRunner) -> bool:
    try:
        previous = runner(("git", "show", f"{base}:{path}"), cwd=root, capture_output=True).stdout
        return _metadata(previous, path) == _metadata((root / path).read_text(), path)
    except OSError, ValueError, ProcessFailureError:
        return False


def _module(path: Path, source_root: Path) -> str:
    parts = path.relative_to(source_root).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(("sarj_standards", *parts))


def _imports(source: Path, module: str = "") -> set[str]:
    imports: set[str] = set()
    package = module if source.name == "__init__.py" else module.rpartition(".")[0]
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    # Release commands have their own complete cohort. Deferred imports in the
    # CLI dispatcher affect those commands, not every unrelated CLI command.
    nodes = _dispatcher_import_nodes(tree) if module == "sarj_standards.cli.main" else ast.walk(tree)
    for node in nodes:
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.update(_from_import_names(node, package))
    return imports


def _dispatcher_import_nodes(tree: ast.AST) -> Iterator[ast.AST]:
    pending = [tree]
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        pending.extend(ast.iter_child_nodes(node))


def _from_import_names(node: ast.ImportFrom, package: str) -> set[str]:
    imported = node.module or ""
    if node.level:
        prefix = package.split(".")[: len(package.split(".")) - node.level + 1]
        imported = ".".join((*prefix, *((imported,) if imported else ())))
    if not imported:
        return set()
    return {imported, *(f"{imported}.{alias.name}" for alias in node.names)}


class _Comparison(BaseModel):
    base: str
    changed: tuple[str, ...]


def _release_dependents(root: Path, changed: Sequence[str], tests: Sequence[Path]) -> set[Path]:
    source_root = root / _SOURCE
    affected = {_module(root / path, source_root) for path in changed if path.startswith(_SOURCE)}
    modules = {
        _module(path, source_root): _imports(path, _module(path, source_root)) for path in source_root.rglob("*.py")
    }
    while True:
        additional = {name for name, imports in modules.items() if imports.intersection(affected)}
        if additional.issubset(affected):
            break
        affected.update(additional)
    return {path for path in tests if _imports(path).intersection(affected)}


def _comparison(root: Path, base: str, head: str, event: str, runner: ProcessRunner) -> _Comparison:
    revision = runner(
        ("git", "rev-parse", "--verify", f"{base}^{{commit}}"), cwd=root, capture_output=True
    ).stdout.strip()
    comparison = revision
    if event != "push":
        comparison = runner(
            ("git", "merge-base", revision, head or "HEAD"), cwd=root, capture_output=True
        ).stdout.strip()
    output = runner(
        ("git", "diff", "--no-renames", "--name-only", "-z", comparison, *((head,) if head else ()), "--"),
        cwd=root,
        capture_output=True,
    ).stdout
    paths = set(output.split("\0")) - {""}
    if not head:
        paths.update(
            runner(
                ("git", "ls-files", "--others", "--exclude-standard", "-z"), cwd=root, capture_output=True
            ).stdout.split("\0")
        )
    return _Comparison(base=comparison, changed=tuple(sorted(paths - {""})))


def select_tests(
    root: Path,
    *,
    base: str = "origin/main",
    head: str = "",
    event: str = "local",
    runner: ProcessRunner = run_process,
) -> TestPlan:
    root = root.resolve()
    directory = root / _PACKAGE / "tests"
    tests = tuple(sorted(directory.rglob("test_*.py")))
    all_tests = tuple(str(path.relative_to(root / _PACKAGE)) for path in tests)
    changed: tuple[str, ...] = ()

    def full(reason: str) -> TestPlan:
        return TestPlan(full=True, reason=reason, changed_files=changed, tests=all_tests, total_files=len(tests))

    if event not in {"local", "pull_request", "push"}:
        return full("scheduled/manual audit or uncertified comparison base")
    if not base or base.startswith("-") or head.startswith("-"):
        return full("missing or invalid comparison; full fallback")
    try:
        comparison = _comparison(root, base, head, event, runner)
        changed = comparison.changed
        selected = _focused_tests(root, comparison, tests, runner)
    except OSError, ProcessFailureError:
        return full("comparison unavailable; full fallback")
    except (ValueError, SyntaxError) as exc:
        return full(str(exc))
    return TestPlan(
        full=False,
        reason="affected changes with smoke/contracts",
        changed_files=changed,
        tests=tuple(str(path.relative_to(root / _PACKAGE)) for path in sorted(selected)),
        total_files=len(tests),
    )


def _focused_tests(root: Path, comparison: _Comparison, tests: Sequence[Path], runner: ProcessRunner) -> set[Path]:
    kinds = {_path_kind(root, comparison.base, path, runner) for path in comparison.changed}
    selected = {path for path in tests if path.name in _SMOKE}
    selected.update(root / path for path in comparison.changed if _is_test_path(path) and (root / path).is_file())
    selected.update(path for path in tests if _cohort_match(path, kinds))
    if "release" in kinds:
        selected.update(_release_dependents(root, comparison.changed, tests))
    return selected


def _cohort_match(path: Path, kinds: set[str]) -> bool:
    if "docs" in kinds and path.name == "test_docs.py":
        return True
    if "cli-artifact" in kinds and path.name == "test_cli_reference_artifact.py":
        return True
    if "artifacts" in kinds and ("artifact" in path.name or path.name.startswith("test_rule_")):
        return True
    if kinds.intersection({"release", "rules"}) and path.parent.name == "release":
        return True
    return "rules" in kinds and (
        path.name in _RULE_INTEGRATION
        or path.name.startswith(("test_rule_", "test_corpus_", "test_cli_", "test_repo_"))
        or "artifact" in path.name
        or path.parent.name == "repository"
    )


def _is_test_path(path: str) -> bool:
    return path.startswith(f"{_PACKAGE}/tests/") and Path(path).name.startswith("test_") and path.endswith(".py")


def _path_kind(root: Path, base: str, path: str, runner: ProcessRunner) -> str:
    if path.startswith(f"{_PACKAGE}/tests/"):
        return _test_kind(path)
    if path.startswith(f"{_SOURCE}libs/release/") and path.endswith(".py"):
        return _release_kind(path)
    if path in {".sarj-standards.toml", "pyproject.toml", "uv.lock"} or (
        path.startswith("packages/") and Path(path).name in {"pyproject.toml", "uv.lock"}
    ):
        if not _metadata_only(root, base, path, runner):
            msg = f"dependencies or shared metadata: {path}"
            raise ValueError(msg)
        return "metadata"
    if any(
        path.startswith((f"packages/{name}/src/", f"packages/{name}/tests/"))
        for name in ("python", "sql", "iac", "typescript")
    ):
        return _rule_kind(path)
    if path == f"{_SOURCE}configs/cli-reference.v1.json":
        return "cli-artifact"
    if path.startswith(f"{_SOURCE}configs/rule-") or path == f"{_SOURCE}schemas/rule-catalog.v1.json":
        return "artifacts"
    if path.startswith("apps/docs/") or path == "README.md" or path.endswith("/README.md"):
        return "docs"
    msg = f"shared or unknown path: {path}"
    raise ValueError(msg)


def _test_kind(path: str) -> str:
    if not _is_test_path(path):
        msg = f"shared test helper or fixture: {path}"
        raise ValueError(msg)
    return "tests"


def _release_kind(path: str) -> str:
    if Path(path).name in {"test_selection.py", "wheel_tests.py", "ci_artifacts.py", "__init__.py"}:
        msg = f"test/artifact infrastructure: {path}"
        raise ValueError(msg)
    return "release"


def _rule_kind(path: str) -> str:
    if "/src/" in path and "/rules/" not in path and Path(path).name != "_registry.py":
        msg = f"shared linter implementation: {path}"
        raise ValueError(msg)
    return "rules"


def execute_plan(root: Path, plan: TestPlan, *, jobs: int = 4, runner: ProcessRunner = run_process) -> None:
    if not plan.tests:
        msg = "test plan is empty"
        raise ValueError(msg)
    if not 1 <= jobs <= _MAX_JOBS:
        msg = "test jobs must be between 1 and 16"
        raise ValueError(msg)
    parallel = (
        ("-n", str(jobs), "--dist", "worksteal") if jobs > 1 and len(plan.tests) >= _PARALLEL_FILE_THRESHOLD else ()
    )
    runner((sys.executable, "-m", "pytest", "-q", *parallel, *plan.tests), cwd=root / _PACKAGE)


def main(argv: Sequence[str] | None = None) -> int:
    app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
    exit_code = 0

    @app.command()
    def check(
        *,
        root: Annotated[Path, typer.Option("--root")] = Path(),
        base: Annotated[str, typer.Option("--base")] = "origin/main",
        head: Annotated[str, typer.Option("--head")] = "",
        event: Annotated[str, typer.Option("--event")] = "local",
        run: Annotated[bool, typer.Option("--run")] = False,
        jobs: Annotated[int, typer.Option("--jobs", min=1, max=_MAX_JOBS)] = 4,
        report: Annotated[Path | None, typer.Option("--report")] = None,
        summary: Annotated[Path | None, typer.Option("--summary")] = None,
    ) -> None:
        nonlocal exit_code
        started = time.monotonic()
        plan = select_tests(root, base=base, head=head, event=event)
        if report is not None:
            report.write_text(plan.model_dump_json(indent=2) + "\n")
        sys.stdout.write(plan.model_dump_json(indent=2) + "\n")
        try:
            if run:
                execute_plan(root.resolve(), plan, jobs=jobs)
        except ProcessFailureError as exc:
            exit_code = exc.returncode
        finally:
            if summary is not None:
                with summary.open("a") as stream:
                    stream.write(
                        f"Standards: {len(plan.tests)}/{plan.total_files} test files; {plan.reason}; {time.monotonic() - started:.1f}s; exit {exit_code}.\n"
                    )

    app(args=None if argv is None else list(argv), prog_name="standards-test-plan", standalone_mode=False)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
