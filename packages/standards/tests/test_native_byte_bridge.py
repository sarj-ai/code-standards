from __future__ import annotations

import base64
from dataclasses import FrozenInstanceError, replace
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

import pytest

from sarj_standards.libs.linting import native_byte_bridge as bridge, native_byte_process as process


if TYPE_CHECKING:
    from sarj_standards.libs.adoption import lifecycle


_Tool = Literal["eslint", "biome", "prettier"]
_SOURCE = b"\xef\xbb\xbf// raw \xff\x00\r\n" + "export const face = '😀';\r\n".encode()
_STDOUT = b"\xef\xbb\xbf\xff\x00first\r\nsecond\n" + "😀".encode()
_STDERR = b"warning\r\n\xff\x00"


@pytest.fixture
def private_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "verified-temporary"
    base.mkdir(mode=0o700)
    monkeypatch.setenv("TMPDIR", str(base))
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the bridge validates Python's actual global temporary-directory cache; an injected base would bypass that security boundary.
        tempfile, "tempdir", str(base)
    )
    return base


def _fixture(root: Path, tool: _Tool = "prettier") -> bridge.NativeInvocation:
    root.mkdir(exist_ok=True)
    node = root / "runtime" / "node"
    node.parent.mkdir()
    node.write_bytes(b"protocol fixture; never executed\n")
    node.chmod(0o700)
    packages: dict[_Tool, tuple[str, str, str]] = {
        "eslint": ("eslint", "eslint", "10.13.0"),
        "biome": ("@biomejs/biome", "biome", "2.6.3"),
        "prettier": ("prettier", "prettier", "3.9.10"),
    }
    name, binary, version = packages[tool]
    package = root / "node_modules" / name
    package.mkdir(parents=True)
    entrypoint = package / "bin" / "native.js"
    entrypoint.parent.mkdir()
    entrypoint.write_bytes(b"// protocol fixture; never executed\n")
    (package / "package.json").write_text(
        json.dumps({"name": name, "version": version, "bin": {binary: "bin/native.js"}}),
        encoding="utf-8",
    )
    config = root / "native.config.json"
    config.write_bytes(b"{}\n")
    source = root / "source.js"
    source.write_bytes(_SOURCE)
    match tool:
        case "eslint":
            args = (
                "--config",
                str(config),
                "--fix-dry-run",
                "--fix-type",
                "directive",
                "--format",
                "json",
                "--no-cache",
                "--stdin",
                "--stdin-filename",
                str(source),
            )
        case "biome":
            args = ("format", "--stdin-file-path", str(source), "--config-path", str(config))
        case "prettier":
            args = ("--config", str(config), "--stdin-filepath", str(source))
    return bridge.NativeInvocation(tool, node, entrypoint, root, args)


def _request(invocation: bridge.NativeInvocation) -> dict[str, process.JsonValue]:
    return process.request_json(
        process.make_request(
            {
                "tool": invocation.tool,
                "node": str(invocation.node),
                "entrypoint": str(invocation.entrypoint),
                "cwd": str(invocation.cwd),
                "args": list(invocation.args),
            },
            _SOURCE,
        )
    )


def _completed(command: lifecycle.Command, status: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command.argv, 0, process.response(status, _STDOUT, _STDERR).decode("ascii"), "")


@pytest.mark.parametrize("tool", ["eslint", "biome", "prettier"])
@pytest.mark.parametrize("status", [0, 1, -15])
def test_transport_keeps_raw_bytes_status_and_fixed_isolated_invocation(
    tmp_path: Path,
    private_tmp: Path,
    tool: _Tool,
    status: int,
) -> None:
    invocation = _fixture(tmp_path / "project", tool)
    calls: list[lifecycle.Command] = []

    def run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert command.argv[:3] == (sys.executable, "-I", str(Path(process.__file__).resolve()))
        assert len(command.argv) == 4
        assert command.cwd == invocation.cwd
        payload = Path(command.argv[3])
        assert payload.parent.parent == private_tmp
        assert stat.S_IMODE(payload.stat().st_mode) == 0o600
        assert stat.S_IMODE(payload.parent.stat().st_mode) == 0o700
        assert payload.stat().st_uid == os.geteuid()
        assert payload.stat().st_nlink == 1
        raw = payload.read_bytes()
        assert payload.name == f"payload.{hashlib.sha256(raw).hexdigest()}.json"
        validated = process.validate_request(process.load_json(raw))
        assert process.load_json(raw) == process.request_json(validated.request)
        assert validated.source == _SOURCE
        return _completed(command, status)

    result = bridge.run_bytes(invocation, _SOURCE, run=run)
    assert result == bridge.NativeBytes(status, _STDOUT, _STDERR)
    assert len(calls) == 1
    assert not tuple(private_tmp.iterdir())
    assert (invocation.cwd / "source.js").read_bytes() == _SOURCE
    with pytest.raises(FrozenInstanceError):
        result.returncode = 42  # pyright: ignore[reportAttributeAccessIssue] -- exercise the frozen runtime contract.
    with pytest.raises(FrozenInstanceError):
        invocation.tool = "other"  # pyright: ignore[reportAttributeAccessIssue] -- exercise the frozen runtime contract.


@pytest.mark.parametrize("tool", ["eslint", "biome", "prettier"])
@pytest.mark.parametrize("extra", ["--write", "--fix", "--rule", "--", "source.js", "--unknown"])
def test_argv_rejects_writes_overrides_and_file_operands(tmp_path: Path, tool: _Tool, extra: str) -> None:
    invocation = _fixture(tmp_path / "project", tool)
    with pytest.raises(ValueError, match="argv"):
        _request(replace(invocation, args=(*invocation.args, extra)))


def test_stdin_path_config_package_bin_and_runtime_are_bound(tmp_path: Path) -> None:
    invocation = _fixture(tmp_path / "project")
    with pytest.raises(ValueError, match="outside"):
        _request(replace(invocation, args=(*invocation.args[:-1], str(tmp_path / "outside.js"))))
    with pytest.raises(ValueError, match="entrypoint"):
        _request(replace(invocation, entrypoint=invocation.cwd / "source.js"))
    invocation.node.chmod(0o722)
    with pytest.raises(ValueError, match="permissions"):
        _request(invocation)
    invocation.node.chmod(0o700)
    package = invocation.entrypoint.parents[1]
    (package / "package.json").write_text(
        '{"name":"prettier","version":"latest","bin":"bin/native.js"}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="version"):
        _request(invocation)


def test_internal_pnpm_package_link_is_allowed_but_external_package_link_is_refused(tmp_path: Path) -> None:
    invocation = _fixture(tmp_path / "project")
    package = invocation.entrypoint.parents[1]
    internal = package.parent / ".pnpm" / "prettier@3.9.10" / "node_modules" / "prettier"
    internal.parent.mkdir(parents=True)
    package.rename(internal)
    package.symlink_to(internal, target_is_directory=True)
    request = _request(invocation)
    process.validate_request(request)
    package.unlink()
    outside = tmp_path / "outside-package"
    internal.rename(outside)
    package.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside local"):
        _request(invocation)


@pytest.mark.parametrize("mutation", ["content", "mode", "replace", "hardlink", "directory"])
def test_payload_mutations_fail_closed_and_do_not_return_native_results(
    tmp_path: Path,
    private_tmp: Path,
    mutation: str,
) -> None:
    invocation = _fixture(tmp_path / "project")

    def run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        payload = Path(command.argv[3])
        match mutation:
            case "content":
                payload.write_bytes(b"changed")
            case "mode":
                payload.chmod(0o640)
            case "replace":
                replacement = payload.parent / "replacement"
                replacement.write_bytes(payload.read_bytes())
                replacement.chmod(0o600)
                replacement.replace(payload)
            case "hardlink":
                os.link(payload, payload.parent / "another-link")
            case "directory":
                (payload.parent / "extra").write_bytes(b"extra")
            case _:
                message = "Unexpected payload mutation fixture"
                raise AssertionError(message)
        return _completed(command)

    with pytest.raises(ValueError, match=r"native bridge|native byte|payload"):
        bridge.run_bytes(invocation, _SOURCE, run=run)
    assert not tuple(private_tmp.iterdir())
    assert (invocation.cwd / "source.js").read_bytes() == _SOURCE


@pytest.mark.parametrize("target", ["runtime", "entrypoint", "manifest", "config"])
@pytest.mark.parametrize("raises", [False, True])
def test_native_input_mutation_is_checked_even_when_callback_raises(
    tmp_path: Path,
    private_tmp: Path,
    target: str,
    raises: bool,
) -> None:
    invocation = _fixture(tmp_path / "project")
    paths = {
        "runtime": invocation.node,
        "entrypoint": invocation.entrypoint,
        "manifest": invocation.entrypoint.parents[1] / "package.json",
        "config": Path(invocation.args[1]),
    }

    def run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        path = paths[target]
        path.write_bytes(path.read_bytes() + b"\n")
        if raises:
            message = "fixture runner stopped"
            raise RuntimeError(message)
        return _completed(command)

    with pytest.raises(ValueError, match=r"native invocation|installed package|invalid installed"):
        bridge.run_bytes(invocation, _SOURCE, run=run)
    assert not tuple(private_tmp.iterdir())


def test_unchanged_callback_failure_propagates_after_post_guards(
    tmp_path: Path,
    private_tmp: Path,
) -> None:
    invocation = _fixture(tmp_path / "project")

    def stopped(_command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        message = "fixture runner stopped"
        raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="fixture runner stopped"):
        bridge.run_bytes(invocation, _SOURCE, run=stopped)
    assert not tuple(private_tmp.iterdir())


def test_request_rejects_boolean_schema_and_tampered_proof_values(tmp_path: Path) -> None:
    invocation = _fixture(tmp_path / "project")
    request = _request(invocation)
    request["schema"] = True
    with pytest.raises(ValueError, match="integer"):
        process.validate_request(request)
    request["schema"] = 1
    request["proofs"] = {"runtime": True, "package": {}, "configs": {}}
    with pytest.raises(ValueError, match="proofs changed"):
        process.validate_request(request)


@pytest.mark.parametrize("bad", ["status", "stderr", "not-json", "duplicate", "bool-status", "base64", "extra-key"])
def test_transport_refuses_bad_outer_results_and_response_envelopes(
    tmp_path: Path,
    private_tmp: Path,
    bad: str,
) -> None:
    invocation = _fixture(tmp_path / "project")

    def run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        payload = {"schema": 1, "returncode": 0, "stdout": "", "stderr": ""}
        match bad:
            case "bool-status":
                payload["returncode"] = True
            case "base64":
                payload["stdout"] = "!invalid!"
            case "extra-key":
                payload["extra"] = "not allowed"
            case "status" | "stderr" | "not-json" | "duplicate":
                pass
            case _:
                message = "Unexpected transport response fixture"
                raise AssertionError(message)
        rendered = json.dumps(payload)
        match bad:
            case "not-json":
                rendered = "not JSON"
            case "duplicate":
                rendered = '{"schema":1,"schema":1,"returncode":0,"stdout":"","stderr":""}'
            case _:
                pass
        return subprocess.CompletedProcess(
            command.argv, int(bad == "status"), rendered, "unexpected transport stderr" if bad == "stderr" else ""
        )

    with pytest.raises(ValueError, match=r"native bridge|native byte|native bridge JSON|isolated native"):
        bridge.run_bytes(invocation, _SOURCE, run=run)
    assert not tuple(private_tmp.iterdir())


def test_node_is_stat_bound_without_reading_or_hashing_its_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invocation = _fixture(tmp_path / "project")
    original = process.file_record
    calls: list[bool] = []

    def recorded(path: Path, *, contents: bool) -> process.FileRecord:
        if path == invocation.node:
            calls.append(contents)
            assert not contents
        return original(path, contents=contents)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the actual Node metadata lookup to reject content reads; injecting the spy would stop testing the production lookup.
        process, "file_record", recorded
    )
    process.validate_request(_request(invocation))
    assert calls
    assert all(not contents for contents in calls)


def test_child_removes_routing_injection_and_git_overrides_without_mutating_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overrides = {
        "BIOME_BINARY": "/outside/binary",
        "BIOME_CONFIG_PATH": "/outside/config",
        "BIOME_LOG_FILE": "/outside/log",
        "BIOME_LOG_PATH": "/outside/log-dir",
        "BIOME_LOG_PREFIX_NAME": "outside",
        "BIOME_LOG_FILE_NAME": "outside",
        "NODE_OPTIONS": "--require=/outside/inject.js",
        "NODE_PATH": "/outside/modules",
        "NODE_V8_COVERAGE": "/outside/coverage",
        "NODE_REDIRECT_WARNINGS": "/outside/warnings.log",
        "NODE_COMPILE_CACHE": "/outside/compile-cache",
        "GIT_DIR": "/outside/git",
        "GIT_INDEX_FILE": "/outside/index",
        "GIT_CONFIG_COUNT": "1",
        "GIT_OPTIONAL_LOCKS": "1",
        "GIT_TERMINAL_PROMPT": "1",
    }
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("NODE_ENV", "production")
    environment = process.child_environment()
    assert all(key not in environment for key in overrides if key not in {"GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT"})
    assert environment["GIT_OPTIONAL_LOCKS"] == "0"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["CI"] == "true"
    assert environment["NODE_ENV"] == "production"
    assert all(os.environ[key] == value for key, value in overrides.items())  # ruff: ignore[banned-api] -- prove child filtering did not mutate the test process environment.


def test_child_sanitizes_supplied_immutable_mapping_without_mutating_it_or_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI", "parent-value")
    original = {
        "CI": "fixture-value",
        "NODE_ENV": "production",
        "PATH": "/fixture/tools",
        "NODE_OPTIONS": "--require=/outside/inject.js",
        "NODE_PATH": "/outside/modules",
        "NODE_V8_COVERAGE": "/outside/coverage",
        "NODE_REDIRECT_WARNINGS": "/outside/warnings.log",
        "NODE_COMPILE_CACHE": "/outside/cache",
        "GIT_INDEX_FILE": "/outside/index",
        "GIT_OPTIONAL_LOCKS": "1",
        "GIT_TERMINAL_PROMPT": "1",
        "BIOME_LOG_PATH": "/outside/logs",
    }
    supplied = MappingProxyType(original.copy())

    sanitized = process.child_environment(supplied)

    assert sanitized == {
        "CI": "fixture-value",
        "NODE_ENV": "production",
        "PATH": "/fixture/tools",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }
    assert dict(supplied) == original
    sanitized["CI"] = "child-only-change"
    assert supplied["CI"] == "fixture-value"
    assert process.child_environment()["CI"] == "parent-value"


def test_main_supplies_raw_stdin_and_filtered_environment_to_nested_native_process(
    tmp_path: Path,
    private_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invocation = _fixture(tmp_path / "project")
    overrides = {
        "BIOME_BINARY": "/outside/native",
        "NODE_OPTIONS": "--require=/outside/injection",
        "NODE_V8_COVERAGE": "/outside/coverage",
        "NODE_REDIRECT_WARNINGS": "/outside/warnings.log",
        "NODE_COMPILE_CACHE": "/outside/compile-cache",
    }
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    # This protocol-only Node double tests bytes/environment, never native formatting.
    script = (
        f"#!{sys.executable}\n"
        "import base64, os, sys\n"
        f"assert sys.argv[1:] == {[str(invocation.entrypoint), *invocation.args]!r}\n"
        f"assert sys.stdin.buffer.read() == {_SOURCE!r}\n"
        f"assert all(name not in os.environ for name in {tuple(overrides)!r})\n"
        "assert os.environ['GIT_OPTIONAL_LOCKS'] == '0'\n"
        "assert os.environ['GIT_TERMINAL_PROMPT'] == '0'\n"
        f"sys.stdout.buffer.write({_STDOUT!r})\n"
        f"sys.stderr.buffer.write({_STDERR!r})\n"
        "raise SystemExit(1)\n"
    )
    invocation.node.write_text(script, encoding="utf-8")

    def run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        assert command.argv == (sys.executable, "-I", str(Path(process.__file__).resolve()), command.argv[3])
        return subprocess.run(command.argv, cwd=command.cwd, capture_output=True, text=True, check=False)

    result = bridge.run_bytes(invocation, _SOURCE, run=run)

    assert result == bridge.NativeBytes(1, _STDOUT, _STDERR)
    assert not tuple(private_tmp.iterdir())
    assert (invocation.cwd / "source.js").read_bytes() == _SOURCE
    assert all(os.environ[key] == value for key, value in overrides.items())  # ruff: ignore[banned-api] -- the child must not alter the parent environment.


def test_payload_rejects_python_temporary_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requested = tmp_path / "requested"
    requested.mkdir()
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    monkeypatch.setenv("TMPDIR", str(requested))
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- a stale global tempfile cache is the fallback behavior under test; injecting a path would not exercise it.
        tempfile, "tempdir", str(fallback)
    )
    with pytest.raises(ValueError, match="fell back"):
        process.temp_base()


def test_response_uses_base64_instead_of_lossy_text_decoding() -> None:
    response = process.load_json(process.response(1, _STDOUT, _STDERR))
    assert process.decode_response(response) == process.DecodedResponse(1, _STDOUT, _STDERR)
    assert base64.b64encode(_STDOUT) in process.response(1, _STDOUT, _STDERR)


def test_resolve_node_uses_callback_cwd_and_path_without_executing_node_or_writing_payload(
    tmp_path: Path,
    private_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "consumer"
    actual_node = project / "runtime/bin/node"
    actual_node.parent.mkdir(parents=True)
    actual_node.write_bytes(b"protocol Node fixture; never executed\n")
    actual_node.chmod(0o700)
    parent_node = tmp_path / "parent/bin/node"
    parent_node.parent.mkdir(parents=True)
    parent_node.write_bytes(b"wrong controller Node fixture; never executed\n")
    parent_node.chmod(0o700)
    monkeypatch.setenv("PATH", str(parent_node.parent))
    assert shutil.which("node") == str(parent_node)
    seen: list[lifecycle.Command] = []

    def run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        assert command.cwd == project
        assert command.argv == (sys.executable, "-I", str(Path(process.__file__).resolve()), "--node-path")
        environment = process.child_environment()
        environment["PATH"] = "runtime/bin"
        return subprocess.run(
            command.argv, cwd=command.cwd, env=environment, capture_output=True, text=True, check=False
        )

    resolved = bridge.resolve_node(project, run=run)

    assert resolved == actual_node
    assert resolved != parent_node
    assert len(seen) == 1
    assert not tuple(private_tmp.iterdir())
    assert actual_node.read_bytes() == b"protocol Node fixture; never executed\n"


@pytest.mark.parametrize("bad", ["status", "stderr", "schema", "bool-schema", "extra", "stat", "replaced", "not-ascii"])
def test_resolve_node_refuses_failed_transport_or_stale_runtime_proofs(
    tmp_path: Path,
    bad: str,
) -> None:
    node = tmp_path / "node"
    node.write_bytes(b"protocol Node fixture; never executed\n")
    node.chmod(0o700)

    def run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        response: dict[str, object] = {"schema": 1, "path": str(node), "stat": process.runtime_record(node)}
        match bad:
            case "schema":
                response["schema"] = 2
            case "bool-schema":
                response["schema"] = True
            case "extra":
                response["unapproved"] = "extra"
            case "stat":
                response["stat"] = {}
            case "replaced":
                replacement = tmp_path / "replacement"
                replacement.write_bytes(node.read_bytes())
                replacement.chmod(0o700)
                replacement.replace(node)
            case "status" | "stderr" | "not-ascii":
                pass
            case _:
                message = "Unexpected Node response fixture"
                raise AssertionError(message)
        rendered = json.dumps(response) if bad != "not-ascii" else "unescaped 😀"
        return subprocess.CompletedProcess(
            command.argv, int(bad == "status"), rendered, "unexpected stderr" if bad == "stderr" else ""
        )

    with pytest.raises(ValueError, match=r"native Node|Node runtime|native bridge|native runtime"):
        bridge.resolve_node(tmp_path, run=run)


def test_static_node_path_probe_refuses_missing_node_and_unsafe_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ValueError, match="absent"):
        process.node_path_response()
    node = tmp_path / "node"
    node.write_bytes(b"protocol Node fixture; never executed\n")
    node.chmod(0o722)
    with pytest.raises(ValueError, match="permissions"):
        process.node_path_response()


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("absent", "Node is absent from the callback PATH"),
        ("unsafe", "selected Node must be executable and not writable by group or others"),
        ("renamed", "selected Node must resolve to a canonical node or node.exe file"),
    ],
)
def test_isolated_node_probe_reports_only_static_actionable_reasons(
    tmp_path: Path,
    kind: str,
    reason: str,
) -> None:
    node = tmp_path / "node"
    if kind != "absent":
        runtime = tmp_path / "renamed-runtime" if kind == "renamed" else node
        runtime.write_bytes(b"protocol Node fixture; never executed\n")
        runtime.chmod(0o722 if kind == "unsafe" else 0o700)
        if kind == "renamed":
            node.symlink_to(runtime)
    observed: list[subprocess.CompletedProcess[str]] = []

    def run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        environment = process.child_environment()
        environment["PATH"] = str(tmp_path)
        result = subprocess.run(
            command.argv, cwd=command.cwd, env=environment, capture_output=True, text=True, check=False
        )
        observed.append(result)
        return result

    with pytest.raises(ValueError, match=r"^isolated native runtime path probe failed:") as failure:
        bridge.resolve_node(tmp_path, run=run)

    assert str(failure.value) == f"isolated native runtime path probe failed: {reason}"
    assert len(observed) == 1
    assert observed[0].returncode == 2
    assert not observed[0].stdout
    assert observed[0].stderr == f"native Node runtime path rejected: {reason}\n"
    assert str(tmp_path) not in observed[0].stderr
    if kind != "absent":
        assert node.read_bytes() == b"protocol Node fixture; never executed\n"


@pytest.mark.parametrize("bad", ["unknown", "suffix", "status", "stdout"])
def test_resolve_node_does_not_propagate_unrecognized_or_invalid_failure_transport(
    tmp_path: Path,
    bad: str,
) -> None:
    known = "native Node runtime path rejected: Node is absent from the callback PATH\n"
    secret = "private-runtime-secret"

    def run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        stderr = known
        if bad == "unknown":
            stderr = secret
        elif bad == "suffix":
            stderr += secret
        return subprocess.CompletedProcess(
            command.argv, 1 if bad == "status" else 2, secret if bad == "stdout" else "", stderr
        )

    with pytest.raises(ValueError, match=r"^isolated native runtime path probe failed$") as failure:
        bridge.resolve_node(tmp_path, run=run)

    assert secret not in str(failure.value)


@pytest.mark.parametrize(
    "kind",
    ["ValueError", "ValueError-object", "ValueError-subclass", "OSError", "OSError-unknown", "OSError-list", "payload"],
)
def test_isolated_probe_unknown_errors_and_payload_failures_keep_generic_private_diagnostic(
    tmp_path: Path,
    kind: str,
) -> None:
    script = Path(process.__file__).resolve()
    if kind == "payload":
        argv = (sys.executable, "-I", str(script), str(tmp_path / "private-payload-secret"))
    else:
        driver = tmp_path / "probe_driver.py"
        match kind:
            case "ValueError-object":
                failure = "ValueError(PrivateSecret())"
            case "ValueError-subclass":
                failure = "ValueError(PrivateString('Node runtime permissions are unsafe'))"
            case "OSError-unknown":
                failure = f"OSError({errno.EIO}, 'private-runtime-secret', 'private-filename-secret')"
            case "OSError-list":
                failure = "OSError([], 'private-runtime-secret', 'private-filename-secret')"
            case _:
                failure = f"{kind}('private-runtime-secret')"
        driver.write_text(
            "import runpy\nimport shutil\nimport sys\n"
            "class PrivateSecret:\n"
            "    def __str__(self) -> str:\n"
            "        raise AssertionError('private-runtime-secret')\n"
            "class PrivateString(str):\n"
            "    def __hash__(self) -> int:\n"
            "        raise AssertionError('private-runtime-secret')\n"
            "def reject(_command: str) -> str | None:\n"
            f"    raise {failure}\n"
            "shutil.which = reject\n"
            "script = sys.argv[1]\n"
            "sys.argv = [script, '--node-path']\n"
            "runpy.run_path(script, run_name='__main__')\n",
            encoding="utf-8",
        )
        argv = (sys.executable, "-I", str(driver), str(script))
    environment = process.child_environment()
    environment["PATH"] = str(tmp_path)

    result = subprocess.run(argv, cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)

    assert result.returncode == 2
    assert not result.stdout
    assert result.stderr == "native byte bridge rejected its payload or execution\n"


@pytest.mark.parametrize(
    ("number", "reason"),
    [
        (errno.ENOENT, "selected Node filesystem entry is missing"),
        (errno.EACCES, "selected Node filesystem metadata is not accessible"),
        (errno.EPERM, "selected Node filesystem metadata access is not permitted"),
        (errno.ENOTDIR, "selected Node runtime path has a non-directory component"),
        (errno.ELOOP, "selected Node runtime path contains a symbolic-link loop"),
    ],
)
def test_isolated_node_probe_reports_allowlisted_os_errors_without_secret_filenames(
    tmp_path: Path,
    number: int,
    reason: str,
) -> None:
    driver = tmp_path / "probe_driver.py"
    driver.write_text(
        "import runpy\nimport shutil\nimport sys\n"
        "def reject(_command: str) -> str | None:\n"
        f"    raise OSError({number}, 'private-runtime-secret', 'private-filename-secret')\n"
        "shutil.which = reject\n"
        "script = sys.argv[1]\n"
        "sys.argv = [script, '--node-path']\n"
        "runpy.run_path(script, run_name='__main__')\n",
        encoding="utf-8",
    )
    observed: list[subprocess.CompletedProcess[str]] = []

    def run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
        environment = process.child_environment()
        environment["PATH"] = str(tmp_path)
        result = subprocess.run(
            (sys.executable, "-I", str(driver), command.argv[2]),
            cwd=command.cwd,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        observed.append(result)
        return result

    with pytest.raises(ValueError, match=r"^isolated native runtime path probe failed:") as failure:
        bridge.resolve_node(tmp_path, run=run)

    assert str(failure.value) == f"isolated native runtime path probe failed: {reason}"
    assert len(observed) == 1
    assert observed[0].returncode == 2
    assert not observed[0].stdout
    assert observed[0].stderr == f"native Node runtime path rejected: {reason}\n"
