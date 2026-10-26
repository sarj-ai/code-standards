from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
import weakref

import pytest

from sarj_python_lint._analysis_session import AnalysisSession
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules._copy_on_write import CopyOnWriteAnalysis
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules._test_provenance import TestProvenance as FileTestProvenance


if TYPE_CHECKING:
    from pathlib import Path


type AnalysisKind = Literal["copy_on_write", "test_provenance"]
type Analysis = CopyOnWriteAnalysis | FileTestProvenance


@dataclass(frozen=True)
class _OwnerReferences:
    context: weakref.ReferenceType[PythonFileContext]
    session: weakref.ReferenceType[AnalysisSession]
    project: weakref.ReferenceType[ProjectIndexSet]


@dataclass(frozen=True)
class _EscapedAnalysis:
    analysis: Analysis
    references: _OwnerReferences


def _new_context(path: Path) -> PythonFileContext:
    source = "value = 1\n"
    session = AnalysisSession()
    session.project = ProjectIndexSet.single(path, source)
    return PythonFileContext(path, source, session)


def _references(context: PythonFileContext) -> _OwnerReferences:
    project = context.session.project
    assert project is not None
    return _OwnerReferences(weakref.ref(context), weakref.ref(context.session), weakref.ref(project))


def _cached(context: PythonFileContext, kind: AnalysisKind) -> Analysis:
    if kind == "copy_on_write":
        return context.copy_on_write
    return context.test_provenance


def _standalone(context: PythonFileContext, kind: AnalysisKind) -> Analysis:
    if kind == "copy_on_write":
        return CopyOnWriteAnalysis(context)
    return FileTestProvenance(context)


def _assert_released(references: _OwnerReferences) -> None:
    assert references.context() is None
    assert references.session() is None
    assert references.project() is None


def _cached_scope(path: Path, kind: AnalysisKind) -> _OwnerReferences:
    context = _new_context(path)
    analysis = _cached(context, kind)
    assert _cached(context, kind) is analysis
    assert analysis.context is context
    return _references(context)


def _escaped_cached(path: Path, kind: AnalysisKind) -> _EscapedAnalysis:
    context = _new_context(path)
    return _EscapedAnalysis(_cached(context, kind), _references(context))


def _escaped_cached_scope(path: Path, kind: AnalysisKind) -> _OwnerReferences:
    escaped = _escaped_cached(path, kind)
    analysis = escaped.analysis
    references = escaped.references
    # Analysis data can own the project, but the cached helper borrows its file owner.
    assert references.context() is None
    assert references.session() is None
    assert references.project() is not None
    with pytest.raises(ReferenceError, match="file context has been released"):
        assert analysis.context is not None
    return references


def _standalone_after_context_scope(path: Path, kind: AnalysisKind) -> _EscapedAnalysis:
    context = _new_context(path)
    return _EscapedAnalysis(_standalone(context, kind), _references(context))


def _standalone_scope(path: Path, kind: AnalysisKind) -> _OwnerReferences:
    escaped = _standalone_after_context_scope(path, kind)
    analysis = escaped.analysis
    references = escaped.references
    # Direct constructors remain strong owners when no borrowing option is supplied.
    assert references.context() is analysis.context
    assert references.session() is analysis.context.session
    assert references.project() is analysis.context.session.project
    return references


def _both_cached_scope(path: Path) -> _OwnerReferences:
    context = _new_context(path)
    assert context.copy_on_write.context is context
    assert context.test_provenance.context is context
    return _references(context)


@pytest.mark.parametrize("kind", ["copy_on_write", "test_provenance"])
def test_cached_analysis_keeps_identity_while_file_owner_is_alive(tmp_path: Path, kind: AnalysisKind) -> None:
    context = _new_context(tmp_path / "owner.py")
    analysis = _cached(context, kind)
    assert _cached(context, kind) is analysis
    assert analysis.context is context
    assert analysis.context.session.project is context.session.project


@pytest.mark.parametrize("kind", ["copy_on_write", "test_provenance"])
def test_file_owned_analysis_releases_session_and_project(tmp_path: Path, kind: AnalysisKind) -> None:
    _assert_released(_cached_scope(tmp_path / "owner.py", kind))


@pytest.mark.parametrize("kind", ["copy_on_write", "test_provenance"])
def test_escaped_cached_analysis_borrows_context_but_retains_its_data(tmp_path: Path, kind: AnalysisKind) -> None:
    _assert_released(_escaped_cached_scope(tmp_path / "owner.py", kind))


@pytest.mark.parametrize("kind", ["copy_on_write", "test_provenance"])
def test_standalone_analysis_owns_context_until_analysis_release(tmp_path: Path, kind: AnalysisKind) -> None:
    _assert_released(_standalone_scope(tmp_path / "owner.py", kind))


def test_both_file_owned_analyses_release_the_shared_session_and_project(tmp_path: Path) -> None:
    _assert_released(_both_cached_scope(tmp_path / "owner.py"))
