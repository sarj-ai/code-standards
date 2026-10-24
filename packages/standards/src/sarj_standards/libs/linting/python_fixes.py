from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_rule_contracts import AutofixPolicy

from sarj_standards.libs.adoption.transaction import FileTransaction, validate_targets

from .analysis import PythonSourceDocument, native_metadata, normalize_native
from .runner import group_paths


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sarj_python_lint import AnalysisSession
    from sarj_python_lint.rule_base import Rule

    from sarj_standards.libs.diagnostics import SourceDocument

    from .policy import Policy


def fix_python(files: Sequence[str], *, root: Path, policy: Policy, python_root: Path | None = None) -> int:
    inputs = _owned_inputs(files, root=root, policy=policy, python_root=python_root)
    paths = tuple(root / name for name in group_paths(inputs, policy=policy, python_only=True).python)
    if not paths:
        return 0
    from sarj_python_lint import AnalysisSession  # ruff: ignore[import-outside-top-level] -- load the native engine only for Python targets.
    from sarj_python_lint.rules import DEFAULT_REGISTRY  # ruff: ignore[import-outside-top-level] -- load only the selected engine.

    validate_targets(root, paths)
    transaction = FileTransaction.capture(root, paths, explicit_only=True)
    rules = [
        cls()
        for cls in DEFAULT_REGISTRY.values()
        if cls.documentation is not None and cls.documentation.autofix is AutofixPolicy.SAFE
    ]
    session = AnalysisSession()
    for rule in rules:
        rule.prepare_session(session)
    planned = _planned_writes(paths, transaction=transaction, rules=rules, session=session, policy=policy)
    try:
        for path, fixed in planned:
            transaction.write_bytes(path, fixed)
    except BaseException as exc:
        report = transaction.rollback()
        if report.issues:
            exc.add_note(str(report))
        raise
    return len(planned)


def _owned_inputs(files: Sequence[str], *, root: Path, policy: Policy, python_root: Path | None) -> list[str]:
    inputs: list[str] = []
    for name in files:
        path = root / name
        policy.relative(path)
        candidate = _owned_input(path, python_root)
        if candidate is None:
            continue
        inputs.append(str(candidate))
    return inputs


def _owned_input(path: Path, python_root: Path | None) -> Path | None:
    if python_root is None or path.resolve().is_relative_to(python_root.resolve()):
        return path
    if path.is_dir() and python_root.resolve().is_relative_to(path.resolve()):
        return python_root
    return None


def _planned_writes(
    paths: tuple[Path, ...],
    *,
    transaction: FileTransaction,
    rules: list[Rule],
    session: AnalysisSession,
    policy: Policy,
) -> list[tuple[Path, bytes]]:
    from sarj_python_lint import apply_fixes  # ruff: ignore[import-outside-top-level] -- source application is Python-only.
    from sarj_python_lint.__main__ import check_source  # ruff: ignore[import-outside-top-level] -- reuse native shared contexts and suppression handling.
    from sarj_python_lint.rules import REGISTRY  # ruff: ignore[import-outside-top-level] -- metadata for the selected engine.

    metadata = native_metadata(REGISTRY)
    planned: list[tuple[Path, bytes]] = []
    root = transaction.root
    for path in paths:
        document = PythonSourceDocument.read(path)
        if transaction.before[path].contents != document.raw:
            msg = f"source changed before fix analysis: {path}"
            raise OSError(msg)
        source = document.document.text
        canonical = source.replace("\r\n", "\n").replace("\r", "\n")
        diagnostics = check_source(rules, path, canonical, session=session)
        documents: dict[Path, SourceDocument | PythonSourceDocument | None] = {path.resolve(): document}
        fixes = tuple(
            fix
            for item in diagnostics
            if item.fixes
            and policy.allows_rule(
                normalize_native(item, source="sarj-python-lint", root=root, metadata=metadata, documents=documents)
            )
            for fix in item.fixes
        )
        fixed = apply_fixes(source, fixes)
        if fixed != source:
            planned.append((path, fixed.encode(document.encoding)))
    return planned
