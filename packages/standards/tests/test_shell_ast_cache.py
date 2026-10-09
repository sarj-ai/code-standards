from pathlib import Path

import pytest

from sarj_standards.libs.linting import shell_ast, textlint
from sarj_standards.libs.linting.devops_programs import ExecutionBlock, block_embeds_program


def _record_parser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def checked() -> Path:
        return Path("/controlled/shfmt")

    def output(source: str, *, executable: Path, dialect: str) -> str:
        assert executable == Path("/controlled/shfmt")
        assert dialect == "bash"
        calls.append(source)
        return '{"Type":"File","Stmts":[],"Nested":{"items":[1]}}'

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native interception proves invocation cache reuse and failure retries.
        shell_ast, "_checked_executable", checked
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native interception proves invocation cache reuse and failure retries.
        shell_ast, "_shell_json", output
    )
    return calls


def test_duplicate_sources_reuse_successful_native_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_parser(monkeypatch)
    parser = shell_ast.make_shell_parser()
    for _ in range(20):
        assert parser("make test")["Type"] == "File"
    assert calls == ["make test"]


def test_cache_returns_independent_nested_trees(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_parser(monkeypatch)
    parser = shell_ast.make_shell_parser()
    first = parser("make test")
    assert isinstance(first, dict)
    nested = first["Nested"]
    assert isinstance(nested, dict)
    nested["items"] = ["poison"]
    first["Type"] = "changed"
    assert parser("make test") == {"Type": "File", "Stmts": [], "Nested": {"items": [1]}}
    assert calls == ["make test"]


def test_distinct_sources_have_distinct_products(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_parser(monkeypatch)
    parser = shell_ast.make_shell_parser()
    parser("make test")
    parser("make lint")
    parser("make test")
    assert calls == ["make test", "make lint"]


def test_new_invocation_attests_again_and_has_no_cached_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_parser(monkeypatch)
    tools = iter((Path("/tools/first/shfmt"), Path("/tools/second/shfmt")))
    attested: list[Path] = []
    executed: list[Path] = []

    def checked() -> Path:
        tool = next(tools)
        attested.append(tool)
        return tool

    def output(source: str, *, executable: Path, dialect: str) -> str:
        assert dialect == "bash"
        calls.append(source)
        executed.append(executable)
        return '{"Type":"File"}'

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native interception proves invocation cache reuse and failure retries.
        shell_ast, "_checked_executable", checked
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native interception proves invocation cache reuse and failure retries.
        shell_ast, "_shell_json", output
    )
    for _ in range(2):
        parser = shell_ast.make_shell_parser()
        parser("make test")
        parser("make test")
    assert calls == ["make test", "make test"]
    assert attested == executed == [Path("/tools/first/shfmt"), Path("/tools/second/shfmt")]


@pytest.mark.parametrize("payload", ["bad json", "{}", "[]", '{"Type":"CallExpr"}'])
def test_invalid_native_products_are_never_cached(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    _record_parser(monkeypatch)
    calls: list[str] = []

    def output(source: str, *, executable: Path, dialect: str) -> str:
        assert executable == Path("/controlled/shfmt")
        assert dialect == "bash"
        calls.append(source)
        return payload

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native interception proves invocation cache reuse and failure retries.
        shell_ast, "_shell_json", output
    )
    parser = shell_ast.make_shell_parser()
    for _ in range(2):
        with pytest.raises(shell_ast.ShellParseError):
            parser("make test")
    assert calls == ["make test", "make test"]


@pytest.mark.parametrize("error", [shell_ast.ShellSyntaxError, shell_ast.ShellParseError, OSError])
def test_native_failure_is_retried(monkeypatch: pytest.MonkeyPatch, error: type[Exception]) -> None:
    _record_parser(monkeypatch)
    calls: list[str] = []

    def output(source: str, *, executable: Path, dialect: str) -> str:
        assert executable == Path("/controlled/shfmt")
        assert dialect == "bash"
        calls.append(source)
        if len(calls) == 1:
            msg = "controlled failure"
            raise error(msg)
        return '{"Type":"File"}'

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native interception proves invocation cache reuse and failure retries.
        shell_ast, "_shell_json", output
    )
    parser = shell_ast.make_shell_parser()
    with pytest.raises(error):
        parser("make test")
    assert parser("make test")["Type"] == "File"
    assert calls == ["make test", "make test"]


def test_character_budget_eviction_preserves_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_parser(monkeypatch)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native interception proves invocation cache reuse and failure retries.
        shell_ast, "_MAX_CACHE_CHARACTERS", 80
    )
    parser = shell_ast.make_shell_parser()
    for source in ("make test", "make lint", "make test", "make test"):
        assert parser(source)["Type"] == "File"
    assert calls == ["make test", "make lint", "make test"]


def test_entry_budget_eviction_preserves_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_parser(monkeypatch)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native interception proves invocation cache reuse and failure retries.
        shell_ast, "_MAX_CACHE_ENTRIES", 2
    )
    parser = shell_ast.make_shell_parser()
    for source in ("one", "two", "three", "one", "one"):
        assert parser(source)["Type"] == "File"
    assert calls == ["one", "two", "three", "one"]


def test_oversize_product_bypasses_retention(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_parser(monkeypatch)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native interception proves invocation cache reuse and failure retries.
        shell_ast, "_MAX_CACHE_CHARACTERS", 20
    )
    parser = shell_ast.make_shell_parser()
    for _ in range(2):
        assert parser("make test")["Type"] == "File"
    assert calls == ["make test", "make test"]


_NATIVE_CASES = (
    ("external-script", "python3 scripts/check.py", False),
    ("inline-python", "python3 -c 'print(1)'", True),
    ("quoted-inline-data", "printf %s 'python3 -c pass'", False),
    ("nested-shell", "sh -c 'make lint && make test'", True),
    ("forwarded-external", "sh -c 'exec \"$@\"' -- python3 scripts/check.py", False),
    ("forwarded-inline", "sh -c 'exec \"$@\"' -- python3 -c 'print(1)'", True),
    ("command-substitution", 'printf %s "$(python3 -c pass)"', True),
    ("multicommand", "make lint\nmake test", True),
    ("empty", "", False),
    ("unicode-argument", "printf %s 'é🐍'", False),
)


@pytest.mark.parametrize(("case_id", "source", "expected"), _NATIVE_CASES, ids=[case[0] for case in _NATIVE_CASES])
def test_native_reuse_retains_policy(case_id: str, source: str, *, expected: bool) -> None:
    parser = shell_ast.make_shell_parser()
    block = ExecutionBlock(1, source)
    for _ in range(2):
        assert block_embeds_program(block, parse_shell=parser) is expected, case_id


def test_reused_native_tree_preserves_workflow_use_sites(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "workflows" / "checks.yml"
    path.parent.mkdir(parents=True)
    source = "name: checks\n'on': push\ndefaults:\n  run:\n    shell: bash\njobs:\n  checks:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python3 -c 'print(1)'\n      - run: python3 -c 'print(1)'\n"
    path.write_text(source)
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
    assert [(finding.line, finding.code) for finding in findings] == [(10, "SARJ310"), (11, "SARJ310")]
