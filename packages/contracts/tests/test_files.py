from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from sarj_rule_contracts import SourceChangedError, fix_file


def test_fix_preserves_bom_crlf_unicode_and_mode(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_bytes(b"\xef\xbb\xbffirst\r\n" + "☃\r\n".encode())
    path.chmod(0o755)
    original = path.stat()
    assert fix_file(path, lambda source: source.replace("first", "second"))
    assert path.read_bytes() == b"\xef\xbb\xbfsecond\r\n" + "☃\r\n".encode()
    assert stat.S_IMODE(path.stat().st_mode) == 0o755
    assert (path.stat().st_uid, path.stat().st_gid) == (original.st_uid, original.st_gid)
    assert not fix_file(path, lambda source: source)


def test_custom_encoding_selector_preserves_legacy_python_source(tmp_path: Path) -> None:
    path = tmp_path / "source.py"
    path.write_bytes("# coding: latin-1\nname = 'café'\n".encode("latin-1"))
    assert fix_file(path, lambda source: source.replace("name", "label"), source_encoding=lambda _data: "latin-1")
    assert path.read_bytes() == "# coding: latin-1\nlabel = 'café'\n".encode("latin-1")


def test_invalid_encoding_is_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_bytes(b"bad\xff\n")
    with pytest.raises(UnicodeDecodeError):
        fix_file(path, lambda source: source.upper())
    assert path.read_bytes() == b"bad\xff\n"


def test_transform_failure_is_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")

    def reject(_source: str) -> str:
        message = "invalid source"
        raise ValueError(message)

    with pytest.raises(ValueError, match="invalid source") as caught:
        fix_file(path, reject)
    assert type(caught.value) is ValueError
    assert path.read_text() == "first"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("parent_link", [False, True])
def test_symlinks_are_preserved(tmp_path: Path, *, parent_link: bool) -> None:
    original = tmp_path / "original"
    original.mkdir()
    target = original / "source.txt"
    target.write_text("first")
    link = tmp_path / "linked"
    link.symlink_to(original if parent_link else target, target_is_directory=parent_link)
    path = link / "source.txt" if parent_link else link
    with pytest.raises(ValueError, match="symlink"):
        fix_file(path, lambda source: source.upper())
    assert target.read_text() == "first"
    assert link.is_symlink()


def test_hard_links_are_preserved(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    link = tmp_path / "linked.txt"
    link.hardlink_to(path)
    with pytest.raises(ValueError, match="one link"):
        fix_file(path, lambda source: source.upper())
    assert path.read_text() == link.read_text() == "first"


def test_concurrent_source_edit_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")

    def concurrent(source: str) -> str:
        path.write_text("concurrent")
        return source.upper()

    with pytest.raises(SourceChangedError, match="changed while fixes"):
        fix_file(path, concurrent)
    assert path.read_text() == "concurrent"
    assert list(tmp_path.iterdir()) == [path]


def test_concurrent_inode_replacement_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    original_inode = path.stat().st_ino

    def concurrent(source: str) -> str:
        replacement = tmp_path / "replacement.txt"
        replacement.write_text(source)
        replacement.replace(path)
        return source.upper()

    with pytest.raises(SourceChangedError, match="changed while fixes"):
        fix_file(path, concurrent)
    assert path.read_text() == "first"
    assert path.stat().st_ino != original_inode
    assert list(tmp_path.iterdir()) == [path]


def test_concurrent_symlink_replacement_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    other = tmp_path / "other.txt"
    other.write_text("external")

    def concurrent(source: str) -> str:
        path.unlink()
        path.symlink_to(other)
        return source.upper()

    with pytest.raises(ValueError, match="symlink"):
        fix_file(path, concurrent)
    assert path.is_symlink()
    assert other.read_text() == "external"
    assert set(tmp_path.iterdir()) == {path, other}


def test_atomic_write_failure_cleans_temporary_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")

    def fail_replace(_temporary: Path, _destination: Path) -> Path:
        message = "write failure"
        raise OSError(message)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts the native atomic commit failure; injection would bypass the filesystem boundary.
        Path, "replace", fail_replace
    )
    with pytest.raises(OSError, match="write failure"):
        fix_file(path, str.upper)
    assert path.read_text() == "first"
    assert list(tmp_path.iterdir()) == [path]


def test_source_edit_during_temporary_fsync_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    native_fsync = os.fsync

    def concurrent_fsync(descriptor: int) -> None:
        native_fsync(descriptor)
        path.write_text("concurrent")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- a concurrent edit during native fsync is the behavior under test.
        "sarj_rule_contracts.files.os.fsync", concurrent_fsync
    )
    with pytest.raises(SourceChangedError, match="changed while fixes") as caught:
        fix_file(path, str.upper)
    assert isinstance(caught.value, ValueError)
    assert path.read_text() == "concurrent"
    assert list(tmp_path.iterdir()) == [path]


def _mock_temporary_group(path: Path, monkeypatch: pytest.MonkeyPatch, *, result: str) -> list[tuple[int, int]]:
    original = path.stat()
    native_fstat = os.fstat
    group = original.st_gid + 1
    calls: list[tuple[int, int]] = []

    def temporary_status(descriptor: int) -> os.stat_result:
        status = native_fstat(descriptor)
        if status.st_ino == original.st_ino:
            return status
        return os.stat_result(
            (
                status.st_mode,
                status.st_ino,
                status.st_dev,
                status.st_nlink,
                status.st_uid,
                group,
                status.st_size,
                status.st_atime,
                status.st_mtime,
                status.st_ctime,
            )
        )

    def preserve_group(_descriptor: int, owner: int, requested: int) -> None:
        nonlocal group
        calls.append((owner, requested))
        if result == "refused":
            message = "group change refused"
            raise PermissionError(message)
        if result == "preserved":
            group = requested

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native descriptor identity distinguishes source and temporary group ownership.
        "sarj_rule_contracts.files.os.fstat", temporary_status
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observes the native ownership request without changing host groups.
        "sarj_rule_contracts.files.os.fchown", preserve_group
    )
    return calls


def test_different_temporary_group_is_restored_before_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    original = path.stat()
    calls = _mock_temporary_group(path, monkeypatch, result="preserved")
    native_fchmod = os.fchmod

    def preserve_mode(descriptor: int, mode: int) -> None:
        assert calls == [(-1, original.st_gid)]
        native_fchmod(descriptor, mode)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- verifies native mode restoration runs after group preservation.
        "sarj_rule_contracts.files.os.fchmod", preserve_mode
    )
    assert fix_file(path, str.upper)
    assert path.read_text() == "FIRST"
    assert path.stat().st_gid == original.st_gid


@pytest.mark.parametrize("result", ["refused", "ignored", "unavailable"])
def test_unpreservable_group_keeps_source_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result: str
) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    _mock_temporary_group(path, monkeypatch, result=result)
    if result == "unavailable":
        monkeypatch.delattr(  # sarj-noqa: SARJ445 -- models absence of the native descriptor ownership API.
            "sarj_rule_contracts.files.os.fchown"
        )
    with pytest.raises((OSError, ValueError), match="group"):
        fix_file(path, str.upper)
    assert path.read_text() == "first"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "attribute", ["system.posix_acl_access", "user.notes", "security.capability", "com.apple.quarantine"]
)
@pytest.mark.parametrize("temporary_attribute", [False, True])
def test_extended_attributes_on_source_or_temporary_refuse_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attribute: str, *, temporary_attribute: bool
) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    original_inode = path.stat().st_ino

    def access_attributes(descriptor: int) -> list[str]:
        if temporary_attribute and os.fstat(descriptor).st_ino == original_inode:
            return []
        return [attribute]

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- models native file metadata without changing real security attributes.
        "sarj_rule_contracts.files.os.listxattr", access_attributes
    )
    with pytest.raises(ValueError, match="extended attribute"):
        fix_file(path, str.upper)
    assert path.read_text() == "first"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("temporary_inspection", [False, True])
def test_attribute_inspection_failure_keeps_source_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, temporary_inspection: bool
) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    original_inode = path.stat().st_ino

    def inaccessible_attributes(descriptor: int) -> list[str]:
        if temporary_inspection and os.fstat(descriptor).st_ino == original_inode:
            return []
        message = "metadata inspection unavailable"
        raise OSError(message)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- verifies fail-closed handling of a native metadata inspection error.
        "sarj_rule_contracts.files.os.listxattr", inaccessible_attributes
    )
    with pytest.raises(ValueError, match=r"inspect.*metadata"):
        fix_file(path, str.upper)
    assert path.read_text() == "first"
    assert list(tmp_path.iterdir()) == [path]


def test_unavailable_permission_api_keeps_source_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    monkeypatch.delattr(  # sarj-noqa: SARJ445 -- models absence of the native descriptor permission API.
        "sarj_rule_contracts.files.os.fchmod"
    )
    with pytest.raises(ValueError, match="permission preservation"):
        fix_file(path, str.upper)
    assert path.read_text() == "first"
    assert list(tmp_path.iterdir()) == [path]


def test_real_user_attribute_is_preserved_by_refusing_replacement(tmp_path: Path) -> None:
    if not hasattr(os, "setxattr") or not hasattr(os, "getxattr"):
        pytest.skip("native extended attributes require platform support")
    path = tmp_path / "source.txt"
    path.write_text("first")
    os.setxattr(path, "user.notes", b"keep this private fixture metadata")
    with pytest.raises(ValueError, match="extended attribute"):
        fix_file(path, str.upper)
    assert path.read_text() == "first"
    assert os.getxattr(path, "user.notes") == b"keep this private fixture metadata"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("privileged_bit", [stat.S_ISUID, stat.S_ISGID])
def test_privileged_source_mode_refuses_replacement_without_changing_host_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, privileged_bit: int
) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    native_lstat = Path.lstat

    def privileged_status(candidate: Path) -> os.stat_result:
        status = native_lstat(candidate)
        if candidate != path:
            return status
        return os.stat_result(
            (
                status.st_mode | privileged_bit,
                status.st_ino,
                status.st_dev,
                status.st_nlink,
                status.st_uid,
                status.st_gid,
                status.st_size,
                status.st_atime,
                status.st_mtime,
                status.st_ctime,
            )
        )

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- models native privileged mode bits without setting host SUID/SGID permissions.
        Path, "lstat", privileged_status
    )
    with pytest.raises(ValueError, match="privileged permission bits"):
        fix_file(path, str.upper)
    assert path.read_text() == "first"
    assert not native_lstat(path).st_mode & (stat.S_ISUID | stat.S_ISGID)
    assert list(tmp_path.iterdir()) == [path]


def test_ignored_mode_restoration_keeps_source_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    path.chmod(0o755)

    def ignored_mode(_descriptor: int, _mode: int) -> None:
        return None

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- models a native permission operation that reports success without preserving the requested mode.
        "sarj_rule_contracts.files.os.fchmod", ignored_mode
    )
    with pytest.raises(ValueError, match="preserve source permissions"):
        fix_file(path, str.upper)
    assert path.read_text() == "first"
    assert stat.S_IMODE(path.stat().st_mode) == 0o755
    assert list(tmp_path.iterdir()) == [path]


def test_temporary_attribute_detected_after_fsync_keeps_source_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first")
    original_inode = path.stat().st_ino
    native_fsync = os.fsync
    prepared = False

    def prepare_metadata(descriptor: int) -> None:
        nonlocal prepared
        native_fsync(descriptor)
        prepared = True

    def prepared_attributes(descriptor: int) -> list[str]:
        if prepared and os.fstat(descriptor).st_ino != original_inode:
            return ["user.notes"]
        return []

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts the native preparation boundary where inherited file metadata can become observable.
        "sarj_rule_contracts.files.os.fsync", prepare_metadata
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- models post-preparation native metadata without mutating real file security attributes.
        "sarj_rule_contracts.files.os.listxattr", prepared_attributes
    )
    with pytest.raises(ValueError, match="extended attribute"):
        fix_file(path, str.upper)
    assert path.read_text() == "first"
    assert list(tmp_path.iterdir()) == [path]
