from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, Manifest, load as load_manifest
from sarj_standards.libs.diagnostics import Completion, Diagnostic, Location, Position, Severity, ToolReport, baseline
from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.linting import autofix, format_only, suppression_descriptions
from sarj_standards.libs.linting.analysis import report_from_tools


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(("git", *arguments), cwd=root, capture_output=True, check=True, text=True).stdout.strip()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    modules = Path(__file__).parents[2] / "typescript" / "node_modules"
    if not (modules / "oxfmt").is_dir() or shutil.which("node") is None:
        pytest.skip("the installed TypeScript toolchain is required")
    _git(tmp_path, "init", "--quiet", "--template=")
    _git(tmp_path, "config", "user.name", "Standards fixture")
    _git(tmp_path, "config", "user.email", "standards-fixture@example.invalid")
    metadata = parse_unique_json((modules / "oxfmt/package.json").read_text())
    assert isinstance(metadata, dict)
    version = metadata["version"]
    assert isinstance(version, str)
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"oxfmt": version}}))
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    (tmp_path / ".oxfmtrc.json").write_text("{}\n")
    (tmp_path / ".gitignore").write_text("node_modules\n")
    shutil.copytree(modules / "oxfmt", tmp_path / "node_modules/oxfmt")
    (tmp_path / "node_modules/@oxfmt").symlink_to(modules / "@oxfmt", target_is_directory=True)
    (tmp_path / "node_modules/tinypool").symlink_to(modules / "tinypool", target_is_directory=True)
    (tmp_path / "source.ts").write_text('export const fallback = (value: string) => value || "default";\n')
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "fixture")
    return tmp_path


@pytest.mark.parametrize(
    ("source", "equivalent"),
    [
        ('export const fallback = (value: string) =>\n  value || "default";\n', True),
        ('export const fallback = (value: string) => value ?? "default";\n', False),
        ('export const fallback = (value: string) => value || "changed";\n', False),
        ('export const fallback = (value: string) => value || "default";\ndebugger;\n', False),
        (
            '// eslint-disable-next-line no-debugger\nexport const fallback = (value: string) => value || "default";\n',
            False,
        ),
        ("export const fallback = (;\n", False),
    ],
)
@pytest.mark.parametrize("absolute", [False, True])
def test_only_layout_can_retain_existing_debt(project: Path, source: str, *, equivalent: bool, absolute: bool) -> None:
    (project / "source.ts").write_text(source)
    _git(project, "add", "source.ts")

    selected = str(project / "source.ts") if absolute else "source.ts"
    assert format_only.equivalent_paths(project, (selected,), staged=True) == (
        frozenset({"source.ts"}) if equivalent else frozenset()
    )


def test_proof_requires_the_exact_index_and_worktree_postimage(project: Path) -> None:
    (project / "source.ts").write_text('export const fallback = (value: string) =>\n  value || "default";\n')
    _git(project, "add", "source.ts")
    (project / "source.ts").write_text('export const fallback = (value: string) => value ?? "default";\n')

    assert format_only.equivalent_paths(project, ("source.ts",), staged=True) == frozenset()


def test_added_sources_have_no_existing_identity(project: Path) -> None:
    (project / "added.ts").write_text("debugger;\n")
    _git(project, "add", "added.ts")

    assert format_only.equivalent_paths(project, ("added.ts",), staged=True) == frozenset()


def test_import_order_is_code_rather_than_layout(project: Path) -> None:
    source = project / "source.ts"
    source.write_text('import "a";\nimport "b";\n')
    _git(project, "add", "source.ts")
    _git(project, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "imports")
    source.write_text('import "b";\nimport "a";\n')
    _git(project, "add", "source.ts")

    assert format_only.equivalent_paths(project, ("source.ts",), staged=True) == frozenset()


def test_staged_layout_does_not_trigger_unrelated_lint_autofixes(project: Path) -> None:
    source = project / "source.ts"
    source.write_text(
        'const bytes = new Uint8Array([0xab, 0xcd]);\nexport const hex = [...bytes].map((byte) => byte.toString(16)).join("");\n'
    )
    (project / ".oxlintrc.json").write_text('{"rules":{"unicorn/no-useless-spread":"error"}}\n')
    _git(project, "add", "--all")
    _git(project, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "typed array fixture")
    source.write_text(
        'const bytes = new Uint8Array([0xab, 0xcd]);\nexport const hex = [...bytes]\n  .map((byte) => byte.toString(16))\n  .join("");\n'
    )
    _git(project, "add", "source.ts")
    binary = project / "node_modules/.bin/oxfmt"
    binary.parent.mkdir()
    binary.symlink_to("../oxfmt/bin/oxfmt")
    proof = format_only.equivalent_paths(project, (str(source),), staged=True)

    result = autofix.run(project, (str(source),), trusted=True, format_only_paths=proof)

    assert result.status == 0
    executed = subprocess.run(
        (
            "node",
            "--input-type=module",
            "--eval",
            "const {hex} = await import(process.argv[1]); process.stdout.write(hex);",
            source.as_uri(),
        ),
        cwd=project,
        capture_output=True,
        check=True,
        text=True,
    )
    assert executed.stdout == "abcd"


@pytest.mark.parametrize("changed_code", [False, True])
def test_baseline_guard_keeps_budgets_without_hiding_new_diagnostics(project: Path, *, changed_code: bool) -> None:
    value = "changed" if changed_code else "default"
    (project / "source.ts").write_text(f'export const fallback = (value: string) =>\n  value || "{value}";\n')
    _git(project, "add", "source.ts")
    existing = Diagnostic(
        "existing",
        "accepted finding",
        Severity.ERROR,
        "oxlint",
        Location("source.ts", position=Position(1, 2, 60)),
        fingerprint="a" * 64,
    )
    new = Diagnostic(
        "new",
        "new finding",
        Severity.ERROR,
        "oxlint",
        Location("source.ts", position=Position(1, 2, 60)),
        fingerprint="b" * 64,
    )
    report = report_from_tools(project, (ToolReport("oxlint", Completion.COMPLETE, diagnostics=(existing, new)),))
    budget = baseline.Budget({"a" * 64: 1}, None)

    scope = api._analysis_changed_scope(project, report, budget, staged=True, trusted=True)  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access] -- exercise the real changed-line/budget seam with an installed formatter, without mocking analysis output.
    filtered = api._without_baselined_diagnostics(report, budget.counts, changed_scope=scope)  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access] -- verify actual budget filtering after source classification.

    assert filtered.diagnostics == ((existing, new) if changed_code else (new,))


def test_more_than_512_sources_keep_layout_proofs_and_baseline_budgets(project: Path) -> None:
    names = [f"source-{index:04}.ts" for index in range(955)]
    for name in names:
        (project / name).write_text('export const value: string = "same";\n')
    _git(project, "add", "--all")
    _git(project, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "large fixture")
    for name in names:
        value = "changed" if name == names[-1] else "same"
        (project / name).write_text(f'export const value: string =\n  "{value}";\n')
    _git(project, "add", "--all")

    assert format_only.equivalent_paths(project, names, staged=True) == frozenset(names[:-1])
    existing = tuple(
        Diagnostic(
            "existing",
            "accepted finding",
            Severity.ERROR,
            "oxlint",
            Location(name, position=Position(1, 2, 40)),
            fingerprint="a" * 64,
        )
        for name in names
    )
    new = Diagnostic(
        "new",
        "new finding",
        Severity.ERROR,
        "oxlint",
        Location(names[0], position=Position(1, 2, 40)),
        fingerprint="b" * 64,
    )
    report = report_from_tools(project, (ToolReport("oxlint", Completion.COMPLETE, diagnostics=(*existing, new)),))
    budget = baseline.Budget({"a" * 64: len(names)}, None)
    scope = api._analysis_changed_scope(project, report, budget, staged=True, trusted=True)  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access] -- exercise the real large changed-line/budget seam.
    filtered = api._without_baselined_diagnostics(report, budget.counts, changed_scope=scope)  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access] -- global budgets must retain new findings and semantic edits across batches.
    assert filtered.diagnostics == (existing[-1], new)


@pytest.mark.parametrize("mutation", ["index", "postimage", "owner"])
def test_later_batch_drift_invalidates_all_earlier_proofs(
    project: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    for name in ("a.ts", "b.ts"):
        (project / name).write_text('export const value = "same";\n')
    _git(project, "add", "--all")
    _git(project, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "batch fixture")
    for name in ("a.ts", "b.ts"):
        (project / name).write_text('export const value =\n  "same";\n')
    _git(project, "add", "--all")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept real batch execution; injection would bypass the proof.
        format_only, "_MAX_FILES", 1
    )
    compare = format_only._compare  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access] -- intercept the real native comparison to mutate inputs between batches.
    calls = 0

    def changing_compare(root: Path, inputs: format_only._FormatterInputs, raw: bytes) -> frozenset[str]:  # pyright: ignore[reportPrivateUsage] -- mutate inputs at the real batch comparison seam.
        nonlocal calls
        calls += 1
        result = compare(root, inputs, raw)
        if calls == 2:
            target = root / ("package-lock.json" if mutation == "owner" else "a.ts")
            target.write_text("{}\n" if mutation == "owner" else 'export const value = "changed";\n')
            if mutation == "index":
                _git(root, "add", "a.ts")
                # Restore the worktree so the final index check itself must catch this.
                target.write_text('export const value =\n  "same";\n')
        return result

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept real batch execution; injection would bypass the proof.
        format_only, "_compare", changing_compare
    )
    assert format_only.equivalent_paths(project, ("a.ts", "b.ts"), staged=True) == frozenset()
    assert calls == 2


@pytest.mark.parametrize(("limit", "repetitions", "count"), [(2600, 20, 4), (32 * 1024 * 1024, 130_000, 12)])
def test_batch_limit_counts_escaped_json_bytes(
    project: Path, monkeypatch: pytest.MonkeyPatch, limit: int, repetitions: int, count: int
) -> None:
    names = [f"unicode-{index}.ts" for index in range(count)]
    value = '界😀\\"' * repetitions
    literal = json.dumps(value, ensure_ascii=False)
    for name in names:
        (project / name).write_text(f"export const value = {literal};\n")
    _git(project, "add", "--all")
    _git(project, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "unicode fixture")
    for name in names:
        (project / name).write_text(f"export const value =\n  {literal};\n")
    _git(project, "add", "--all")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept real batch execution; injection would bypass the proof.
        format_only, "_MAX_INPUT_BYTES", limit
    )
    compare = format_only._compare  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access] -- intercept the real native comparison to mutate inputs between batches.
    sizes: list[int] = []

    def bounded_compare(root: Path, inputs: format_only._FormatterInputs, raw: bytes) -> frozenset[str]:  # pyright: ignore[reportPrivateUsage] -- inspect the actual serialized adapter payload.
        sizes.append(len(raw))
        assert len(raw) < limit
        assert json.loads(raw)[0]["after"] == inputs.requests[0].after
        return compare(root, inputs, raw)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept real batch execution; injection would bypass the proof.
        format_only, "_compare", bounded_compare
    )
    assert format_only.equivalent_paths(project, names, staged=True) == frozenset(names)
    assert len(sizes) > 1


@pytest.mark.parametrize("staged", [False, True])
def test_batches_keep_one_base_and_reject_type_and_import_changes(
    project: Path, monkeypatch: pytest.MonkeyPatch, *, staged: bool
) -> None:
    originals = {
        "a.ts": 'export const value: string = "same";\n',
        "b.ts": 'export const value: string = "same";\n',
        "c.ts": 'import "a";\nimport "b";\n',
    }
    for name, source in originals.items():
        (project / name).write_text(source)
    _git(project, "add", "--all")
    _git(project, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "base fixture")
    base = _git(project, "rev-parse", "HEAD")
    (project / "a.ts").write_text('export const value: string =\n  "same";\n')
    (project / "b.ts").write_text('export const value: unknown = "same";\n')
    (project / "c.ts").write_text('import "b";\nimport "a";\n')
    _git(project, "add", "--all")
    if not staged:
        _git(project, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "changes")
        monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept real batch execution; injection would bypass the proof.
        format_only, "_MAX_FILES", 1
    )

    assert format_only.equivalent_paths(project, originals, staged=staged) == frozenset({"a.ts"})


def test_native_python_type_ignore_description_retains_accepted_budget(tmp_path: Path) -> None:
    source = tmp_path / "bench_common.py"
    original = 'get_openai.clear = getattr(_shared_openai, "clear", None) or _shared_openai.cache_clear  # type: ignore[attr-defined]\n'
    source.write_text(original)
    _git(tmp_path, "init", "--quiet", "--template=")
    _git(tmp_path, "config", "user.name", "Standards fixture")
    _git(tmp_path, "config", "user.email", "standards-fixture@example.invalid")
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "--quiet", "-m", "original")
    standards = api.Standards(tmp_path)
    rules = ["python:no-dynamic-builtins"]
    raw = standards.analyze([str(source)], mode=api.AnalysisMode.RAW, rules=rules)
    assert raw.completion is Completion.COMPLETE
    assert len(raw.diagnostics) == 1
    assert raw.diagnostics[0].source == "sarj-python-lint"
    (tmp_path / "baseline.json").write_text(
        baseline.render(
            raw.diagnostics,
            bundle_version=api.__version__,
            consumer_base_sha=_git(tmp_path, "rev-parse", "HEAD"),
            catalog_digest=baseline.bundled_catalog_digest(),
        )
    )
    (tmp_path / MANIFEST_NAME).write_text(
        Manifest(
            version=api.__version__,
            configs=(),
            python_dest=".",
            typescript_dest=".",
            hook_manager="none",
            diagnostic_baseline="baseline.json",
        ).render()
    )
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "--quiet", "-m", "accepted baseline")
    description = " — attach the cache invalidator shared by Streamlit clear and functools cache_clear to this callable"
    source.write_text(original.rstrip("\n") + description + "\n")
    _git(tmp_path, "add", "--all")
    current = standards.analyze([str(source)], mode=api.AnalysisMode.RAW, staged=True, rules=rules)
    assert current.diagnostics[0].fingerprint == raw.diagnostics[0].fingerprint
    fingerprint = raw.diagnostics[0].fingerprint
    assert fingerprint is not None
    budget = baseline.Budget({fingerprint: 1}, None)
    scope = api._analysis_changed_scope(tmp_path, current, budget, staged=True, trusted=True)  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access] -- exercise native findings through the real staged compatibility seam.
    filtered = api._without_baselined_diagnostics(current, budget.counts, changed_scope=scope)  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access] -- verify accepted native fingerprints remain budgeted.
    assert filtered.diagnostics == ()

    policy = standards.analyze([str(source)], staged=True, trust=api.TrustMode.TRUSTED, rules=rules)
    assert policy.issues == ()
    assert policy.diagnostics == ()
    assert policy.exit_code == 0


@pytest.mark.parametrize(
    ("before", "after", "accepted"),
    [
        ("x = 1  # type: ignore[attr-defined]", "x = 1  # type: ignore[attr-defined] — existing boundary", True),
        ("x = 1  # noqa: F401", "x = 1  # noqa: F401 -- existing boundary", True),
        ("x = 1  # noqa: F401 — old reason", "x = 1  # noqa: F401 — precise reason", True),
        ("x = 1", "x = 1  # type: ignore[attr-defined] — boundary", False),
        ("x = 1  # type: ignore[attr-defined]", "x = 1  # type: ignore[assignment] — boundary", False),
        ("x = 1  # type: ignore[attr-defined]", "x = 1  # type: ignore[attr-defined,assignment] — boundary", False),
        ("x = 1  # type: ignore[attr-defined]", "x = 2  # type: ignore[attr-defined] — boundary", False),
        ("x = 1  # type: ignore[attr-defined]", "x: int = 1  # type: ignore[attr-defined] — boundary", False),
        ("x = 1  # type: ignore[attr-defined]", "x = 1  # type: ignore[attr-defined] — noqa: F401", False),
        ("x = 1  # type: ignore[attr-defined]", "x = 1  # type: ignore[attr-defined] — pylint disable", False),
        ("x = 1  # type: ignore[attr-defined]", "x = 1  # type: ignore[attr-defined] — preserve nosem", False),
        ("x = 1  # type: ignore[attr-defined]", "x = 1  # type: ignore[attr-defined] — preserve nosemgrep", False),
        ("x = 1  # noqa: F401", "x = 1  # noqa: F401 — preserve NOSEMGREP", False),
        ("x = 1  # noqa: F401", "x = 1  # noqa: F401 — preserve nosemantics", False),
        ("x = 1  # type: ignore[attr-defined]", "x = 1  # type: ignore[attr-defined] — # fmt: off", False),
        ("x = 1  # type: ignore[attr-defined]", "x = 1  # type: ignore[attr-defined] — " + "a" * 2049, False),
        ("x = 1  # type: ignore", "x = 1  # type: ignore — boundary", False),
        ("x = 1  # arbitrary", "x = 1  # arbitrary — boundary", False),
        ("# type: ignore[attr-defined]", "# type: ignore[attr-defined] — boundary", False),
        ('x = "# type: ignore[attr-defined]"', 'x = "# type: ignore[attr-defined] — boundary"', False),
        ('"""# type: ignore[attr-defined]"""', '"""# type: ignore[attr-defined] — boundary"""', False),
        ("x = 1  # noqa: F401", "x = 1  # noqa: F401, F841 — boundary", False),
        ("x = 1  # noqa: F401", "x = 1  # ruff: noqa: F401 — boundary", False),
    ],
)
def test_description_proof_is_lexical_and_bounded(before: str, after: str, *, accepted: bool) -> None:
    assert suppression_descriptions.equivalent(before + "\n", after + "\n") is accepted
    if not accepted:
        assert not suppression_descriptions.equivalent(after + "\n", before + "\n")


@pytest.mark.parametrize("mutation", ["worktree", "index", "head"])
def test_python_description_proof_rejects_inflight_ownership_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    source = tmp_path / "app.py"
    source.write_text("x = 1  # type: ignore[attr-defined]\n")
    _git(tmp_path, "init", "--quiet", "--template=")
    _git(tmp_path, "config", "user.name", "Standards fixture")
    _git(tmp_path, "config", "user.email", "standards-fixture@example.invalid")
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "--quiet", "-m", "original")
    current = "x = 1  # type: ignore[attr-defined] — boundary\n"
    source.write_text(current)
    _git(tmp_path, "add", "--all")
    compare = suppression_descriptions.equivalent

    def mutate(before: str, after: str) -> bool:
        result = compare(before, after)
        source.write_text("x = 2\n")
        if mutation == "index":
            _git(tmp_path, "add", "--all")
            source.write_text(current)
        if mutation == "head":
            _git(tmp_path, "commit", "--quiet", "-m", "inflight")
            source.write_text(current)
        return result

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- mutate actual Git/worktree ownership during the lexical proof.
        suppression_descriptions,
        "equivalent",
        mutate,
    )
    assert format_only.equivalent_paths(tmp_path, ("app.py",), staged=True) == frozenset()


def test_normal_staged_fix_preserves_description_only_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sarj_standards.cli.main import main  # ruff: ignore[import-outside-top-level] -- run the production CLI path in this native integration fixture.

    monkeypatch.setenv("SARJ_STANDARDS_BOOTSTRAPPED", "1")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n'
    )
    source = tmp_path / "app.py"
    original = "def render(item):\n    payload = item\n    return dict(payload=payload)\n\nx = 1  # type: ignore[attr-defined]\n"
    source.write_text(original)
    _git(tmp_path, "init", "--quiet", "--template=")
    _git(tmp_path, "config", "user.name", "Standards fixture")
    _git(tmp_path, "config", "user.email", "standards-fixture@example.invalid")
    assert main(["--root", str(tmp_path), "setup", "--no-install"]) == 0
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "--quiet", "-m", "original")
    standards = api.Standards(tmp_path)
    raw = standards.analyze(
        [str(source)],
        external=True,
        trust=api.TrustMode.TRUSTED,
        mode=api.AnalysisMode.RAW,
        python_type_check=False,
        typescript=False,
    )
    assert raw.completion is Completion.COMPLETE
    assert raw.diagnostics, raw
    assert any(item.code == "C408" for item in raw.diagnostics)
    (tmp_path / "baseline.json").write_text(
        baseline.render(
            raw.diagnostics,
            bundle_version=api.__version__,
            consumer_base_sha=_git(tmp_path, "rev-parse", "HEAD"),
            catalog_digest=baseline.bundled_catalog_digest(),
        )
    )
    adopted = load_manifest(tmp_path)
    assert adopted is not None
    assert "ruff" in adopted.enabled_capabilities
    (tmp_path / MANIFEST_NAME).write_text(replace(adopted, diagnostic_baseline="baseline.json").render())
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "--quiet", "-m", "accepted baseline")
    reviewed = original.replace("[attr-defined]", "[attr-defined] — legacy callable boundary")
    source.write_text(reviewed)
    control = autofix.run(tmp_path, (str(source),), trusted=True, typescript=False)
    assert control.status in {0, 1}
    assert source.read_bytes() == reviewed.encode()
    source.write_text(reviewed)
    _git(tmp_path, "add", "app.py")
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "check",
                "--staged",
                "--fix",
                "--trust-repository-code",
                "--skip-python-type-check",
                "--skip-typescript",
            ]
        )
        == 0
    )
    assert source.read_bytes() == reviewed.encode()
    assert _git(tmp_path, "show", ":app.py") == reviewed.rstrip("\n")


def test_python_description_proof_keeps_count_growth_and_required_floors(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        'get_openai.clear = getattr(_shared_openai, "clear", None) or _shared_openai.cache_clear  # type: ignore[attr-defined]\n'
    )
    _git(tmp_path, "init", "--quiet", "--template=")
    _git(tmp_path, "config", "user.name", "Standards fixture")
    _git(tmp_path, "config", "user.email", "standards-fixture@example.invalid")
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "--quiet", "-m", "original")
    raw = api.Standards(tmp_path).analyze(
        [str(source)], mode=api.AnalysisMode.RAW, rules=["python:no-dynamic-builtins"]
    )
    [existing] = raw.diagnostics
    assert existing.fingerprint is not None
    source.write_text(source.read_text().rstrip("\n") + " — existing boundary\n")
    _git(tmp_path, "add", "app.py")
    new = replace(existing, fingerprint="f" * 64, message="new finding")
    floor = replace(existing, fingerprint="e" * 64, tags=("non-baselineable",), message="required source policy")
    report = report_from_tools(
        tmp_path, (ToolReport("sarj-python-lint", Completion.COMPLETE, diagnostics=(existing, existing, new, floor)),)
    )
    budget = baseline.Budget({existing.fingerprint: 1, "f" * 64: 0, "e" * 64: 9}, None)
    scope = api._analysis_changed_scope(tmp_path, report, budget, staged=True, trusted=True)  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access] -- actual native finding and lexical proof with count/new/floor controls.
    filtered = api._without_baselined_diagnostics(report, budget.counts, changed_scope=scope)  # pyright: ignore[reportPrivateUsage]  # ruff: ignore[private-member-access] -- one accepted occurrence cannot absorb growth or required findings.
    assert filtered.diagnostics == (existing, new, floor)


@pytest.mark.parametrize("mutation", ["unstaged", "missing", "oversized", "added"])
def test_python_description_proof_rejects_unowned_inputs(tmp_path: Path, mutation: str) -> None:
    source = tmp_path / "app.py"
    original = "x = 1  # type: ignore[attr-defined]\n"
    source.write_text(original)
    _git(tmp_path, "init", "--quiet", "--template=")
    _git(tmp_path, "config", "user.name", "Standards fixture")
    _git(tmp_path, "config", "user.email", "standards-fixture@example.invalid")
    _git(tmp_path, "add", "--all")
    _git(tmp_path, "commit", "--quiet", "-m", "original")
    source.write_text(f"{original.rstrip(chr(10))} — existing boundary\n")
    if mutation == "oversized":
        source.write_text(source.read_text() + "#" * (2 * 1024 * 1024))
    if mutation == "added":
        source = tmp_path / "added.py"
        source.write_text(original)
    _git(tmp_path, "add", "--all")
    if mutation == "unstaged":
        source.write_text(original)
    if mutation == "missing":
        source.unlink()
    assert format_only.equivalent_paths(tmp_path, (source.name,), staged=True) == frozenset()


@pytest.mark.parametrize("mutation", ["layout", "literal", "imports", "raw", "added"])
def test_jsx_width_policy_and_source_identity(project: Path, mutation: str) -> None:
    original = (
        'import "first";\nimport "second";\n'
        "export const raw = String.raw`first\\nsecond`;\n"
        "export const View = () => <p>Review the selected workspace settings before continuing.</p>;\n"
    )
    canonical = (
        'import "first";\nimport "second";\n'
        "export const raw = String.raw`first\\nsecond`;\n"
        "export const View = () => (\n"
        "  <p>Review the selected workspace settings before continuing.</p>\n"
        ");\n"
    )
    source = project / "view.tsx"
    source.write_text(original)
    _git(project, "add", "view.tsx")
    _git(project, "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "JSX fixture")
    if mutation == "literal":
        canonical = canonical.replace("Review", "Change")
    if mutation == "imports":
        canonical = canonical.replace('import "first";\nimport "second";', 'import "second";\nimport "first";')
    if mutation == "raw":
        canonical = canonical.replace(r"first\nsecond", r"first\tsecond")
    if mutation == "added":
        source = project / "added.tsx"
    source.write_text(canonical)
    _git(project, "add", source.name)
    assert format_only.equivalent_paths(project, (source.name,), staged=True) == (
        frozenset({source.name}) if mutation == "layout" else frozenset()
    )


def test_comparison_formats_real_jsx_at_shared_eighty_columns(project: Path) -> None:
    modules = project / "node_modules/oxfmt"
    real_module = (Path(__file__).parents[2] / "typescript/node_modules/oxfmt/dist/index.js").resolve()
    (modules / "package.json").write_text('{"type":"module","exports":"./observe.mjs"}')
    (modules / "observe.mjs").write_text(
        f"import {{ format as nativeFormat }} from {json.dumps(real_module.as_uri())};\n"
        "export async function format(...args) {\n"
        "  const result = await nativeFormat(...args);\n"
        '  process.stderr.write(JSON.stringify(result.code) + "\\n");\n'
        "  return result;\n}\n"
    )
    source = "export const View = () => <p>Review the selected workspace settings before continuing.</p>;\n"
    script = Path(format_only.__file__).parents[2] / "configs/format-only.mjs"
    result = subprocess.run(
        ("node", str(script)),
        input=json.dumps(
            [{"entrypoint": str(project / "package.json"), "path": "view.tsx", "before": source, "after": source}]
        ),
        capture_output=True,
        check=True,
        text=True,
    )
    expected = "export const View = () => (\n  <p>Review the selected workspace settings before continuing.</p>\n);\n"
    assert [json.loads(line) for line in result.stderr.splitlines()] == [expected, expected]
    assert json.loads(result.stdout) == ["view.tsx"]
