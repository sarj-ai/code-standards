"""Corpus manifests pin local bytes and keep private overlays private."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs.libs.corpus import (
    CorpusKind,
    CorpusManifest,
    CorpusSnapshot,
    CorpusSource,
    CorpusVisibility,
    load_manifest,
    load_private_overlay,
    merge_manifests,
    snapshot,
    verify,
)


if TYPE_CHECKING:
    from pathlib import Path


_EMPTY_DIGEST = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _source(root: Path, *, digest: str = _EMPTY_DIGEST) -> CorpusSource:
    return CorpusSource("sample", root, CorpusKind.LOCAL, digest, ("**/*.py",), ("vendor/**",))


def test_snapshot_is_stable_and_sensitive_to_selected_content(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    source_file = tmp_path / "src" / "app.py"
    source_file.write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("ignored\n", encoding="utf-8")

    first = snapshot(_source(tmp_path))
    second = snapshot(_source(tmp_path))
    source_file.write_text("VALUE = 2\n", encoding="utf-8")
    changed = snapshot(_source(tmp_path))

    assert first == second
    assert first.files == 1
    assert first.digest != changed.digest


def test_snapshot_value_rejects_invalid_or_empty_identity() -> None:
    with pytest.raises(ValueError, match="sha256"):
        CorpusSnapshot("sample", "not-a-digest", 1, 1)
    with pytest.raises(ValueError, match="counts"):
        CorpusSnapshot("sample", _EMPTY_DIGEST, 0, -1)


def test_verify_requires_the_declared_content_digest(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    actual = snapshot(_source(tmp_path))

    verified = verify(_source(tmp_path, digest=actual.digest))
    assert verified == actual
    assert verified.verified is True
    assert actual.verified is False
    with pytest.raises(ValueError, match="digest drifted"):
        verify(_source(tmp_path))


def test_public_manifest_resolves_local_paths_without_network_access(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    manifest = tmp_path / "corpora.toml"
    manifest.write_text(
        "schema = 1\n"
        "[[corpus]]\n"
        'name = "sample"\n'
        'root = "corpus"\n'
        'kind = "local"\n'
        f'digest = "{_EMPTY_DIGEST}"\n'
        'include = ["**/*.py"]\n',
        encoding="utf-8",
    )

    loaded = load_manifest(manifest)

    assert loaded.sources[0].root == corpus
    assert loaded.sources[0].visibility is CorpusVisibility.PUBLIC


def test_git_manifest_requires_and_preserves_a_full_revision_pin(tmp_path: Path) -> None:
    corpus = tmp_path / "checkout"
    corpus.mkdir()
    revision = "a" * 40
    manifest = tmp_path / "pinned.toml"
    manifest.write_text(
        "schema = 1\n"
        "[[corpus]]\n"
        'name = "pinned-project"\n'
        'root = "checkout"\n'
        'kind = "git"\n'
        f'revision = "{revision}"\n'
        f'digest = "{_EMPTY_DIGEST}"\n'
        'include = ["**/*.py"]\n',
        encoding="utf-8",
    )

    loaded = load_manifest(manifest)

    assert loaded.sources[0].kind is CorpusKind.GIT
    assert loaded.sources[0].revision == revision


def test_git_corpus_rejects_a_floating_revision(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="full lowercase 40-character"):
        CorpusSource(
            "floating",
            tmp_path,
            CorpusKind.GIT,
            _EMPTY_DIGEST,
            ("**/*.py",),
            revision="main",
        )


def test_public_manifest_cannot_masquerade_as_private_overlay(tmp_path: Path) -> None:
    manifest = tmp_path / "corpora.toml"
    manifest.write_text("schema = 1\nprivate = true\n", encoding="utf-8")

    with pytest.raises(ValueError, match="public manifest"):
        load_manifest(manifest)


def test_private_overlay_requires_owner_only_file_and_redacts_identity(tmp_path: Path) -> None:
    corpus = tmp_path / "customer-code"
    corpus.mkdir()
    (corpus / "sample.py").write_text("value = 1\n", encoding="utf-8")
    overlay = tmp_path / "private.toml"
    overlay.write_text(
        "schema = 1\n"
        "private = true\n"
        "[[corpus]]\n"
        'name = "customer-bank"\n'
        f'root = "{corpus}"\n'
        'kind = "local"\n'
        f'digest = "{_EMPTY_DIGEST}"\n'
        'include = ["**/*.py"]\n',
        encoding="utf-8",
    )
    overlay.chmod(0o644)
    with pytest.raises(PermissionError, match="chmod 600"):
        load_private_overlay(overlay)

    overlay.chmod(0o600)
    loaded = load_private_overlay(overlay)

    assert loaded.sources[0].report_name == "<private-corpus>"
    assert "customer-bank" not in repr(loaded)
    private_snapshot = snapshot(loaded.sources[0])
    assert str(corpus) not in repr(private_snapshot)
    assert private_snapshot.digest not in repr(private_snapshot)
    assert str(corpus) not in repr(loaded)
    assert loaded.sources[0].digest not in repr(loaded)

    with pytest.raises(ValueError, match="digest drifted") as error:
        verify(loaded.sources[0])
    assert str(corpus) not in str(error.value)
    assert loaded.sources[0].digest not in str(error.value)
    assert private_snapshot.digest not in str(error.value)


def test_private_snapshot_errors_do_not_reveal_roots(tmp_path: Path) -> None:
    root = tmp_path / "confidential-customer"
    source = CorpusSource(
        "customer-bank",
        root,
        CorpusKind.LOCAL,
        _EMPTY_DIGEST,
        ("**/*.py",),
        visibility=CorpusVisibility.PRIVATE,
    )

    with pytest.raises(ValueError, match="root is not a directory") as error:
        snapshot(source)

    assert str(root) not in str(error.value)
    assert "customer-bank" not in str(error.value)


def test_git_corpus_root_must_match_repository_top_level(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    corpus = tmp_path / "repository" / "nested-corpus"
    corpus.mkdir(parents=True)
    (corpus / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    source = CorpusSource(
        "nested",
        corpus,
        CorpusKind.GIT,
        "sha256:" + "0" * 64,
        ("**/*.py",),
        revision="a" * 40,
    )

    completed = subprocess.CompletedProcess(
        args=("git",),
        returncode=0,
        stdout=f"{corpus.parent}\n{'a' * 40}\n",
    )

    def which(_name: str) -> str:
        return "/usr/bin/git"

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = _args[0]
        if isinstance(argv, tuple) and "ls-files" in argv:
            return subprocess.CompletedProcess(("git",), 0, "app.py\0")
        return completed

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(ValueError, match="repository root does not match"):
        snapshot(source)


def test_git_corpus_ignores_ambient_repository_routing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    corpus = tmp_path / "repository"
    corpus.mkdir()
    (corpus / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    revision = "a" * 40
    source = CorpusSource(
        "pinned",
        corpus,
        CorpusKind.GIT,
        "sha256:" + "0" * 64,
        ("**/*.py",),
        revision=revision,
    )
    monkeypatch.setenv("GIT_DIR", "/wrong/repository/.git")
    monkeypatch.setenv("GIT_WORK_TREE", "/wrong/repository")

    def which(_name: str) -> str:
        return "/usr/bin/git"

    monkeypatch.setattr(shutil, "which", which)

    def run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs.get("env")
        assert isinstance(environment, dict)
        assert "GIT_DIR" not in environment
        assert "GIT_WORK_TREE" not in environment
        argv = _args[0]
        stdout = "app.py\0" if isinstance(argv, tuple) and "ls-files" in argv else f"{corpus}\n{revision}\n"
        return subprocess.CompletedProcess(("git",), 0, stdout)

    monkeypatch.setattr(subprocess, "run", run)

    assert snapshot(source).revision == revision


def test_git_corpus_selects_only_tracked_existing_files(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is required")
    corpus = tmp_path / "repository"
    corpus.mkdir()
    tracked = corpus / "tracked.py"
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    (corpus / "generated.py").write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(("git", "init", "-q"), cwd=corpus, check=True)
    subprocess.run(("git", "add", "tracked.py"), cwd=corpus, check=True)
    subprocess.run(
        ("git", "-c", "user.name=Standards", "-c", "user.email=standards@example.invalid", "commit", "-qm", "pin"),
        cwd=corpus,
        check=True,
    )
    revision = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=corpus,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    unpinned = CorpusSource(
        "tracked-only",
        corpus,
        CorpusKind.GIT,
        _EMPTY_DIGEST,
        ("**/*.py",),
        revision=revision,
    )

    actual = snapshot(unpinned)

    assert actual.files == 1
    assert actual.bytes == tracked.stat().st_size


def test_public_manifest_rejects_absolute_nonportable_roots(tmp_path: Path) -> None:
    manifest = tmp_path / "corpora.toml"
    manifest.write_text(
        "schema = 1\n"
        "[[corpus]]\n"
        'name = "sample"\n'
        f'root = "{tmp_path}"\n'
        'kind = "local"\n'
        f'digest = "{_EMPTY_DIGEST}"\n'
        'include = ["**/*.py"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be relative"):
        load_manifest(manifest)


def test_public_manifest_rejects_parent_directory_roots(tmp_path: Path) -> None:
    manifest = tmp_path / "corpora.toml"
    manifest.write_text(
        "schema = 1\n"
        "[[corpus]]\n"
        'name = "sample"\n'
        'root = "../outside"\n'
        'kind = "local"\n'
        f'digest = "{_EMPTY_DIGEST}"\n'
        'include = ["**/*.py"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="below the manifest"):
        load_manifest(manifest)


def test_snapshot_rejects_a_corpus_that_selects_no_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="selected no files"):
        snapshot(_source(tmp_path))


def test_private_overlay_cannot_duplicate_a_public_corpus_name(tmp_path: Path) -> None:
    source = _source(tmp_path)
    public = CorpusManifest(tmp_path / "public.toml", (source,))
    private_source = CorpusSource(
        source.name,
        source.root,
        source.kind,
        source.digest,
        source.include,
        visibility=CorpusVisibility.PRIVATE,
    )
    private = CorpusManifest(tmp_path / "private.toml", (private_source,), private=True)

    with pytest.raises(ValueError, match="unique"):
        merge_manifests(public, private)
