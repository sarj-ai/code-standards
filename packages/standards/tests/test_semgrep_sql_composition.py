from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.semgrep_sql_composition import RULE, Correction, correct
from sarj_standards.libs.release.process import credential_free_environment


if TYPE_CHECKING:
    from pydantic import JsonValue


_FIXTURES = Path(__file__).parent / "fixtures" / "semgrep-sql-composition"
_SAFE = (_FIXTURES / "safe.py.txt").read_text(encoding="utf-8")
_UNSAFE = (
    '"SELECT {}".format(user)',
    'f"SELECT {user}"',
    "SQL(user).format()",
    'SQL("{}").format(SQL(user))',
    'unknown.format(SQL("id"))',
    'SQL("{}").format(*items)',
    'SQL("{}").format(**items)',
)
_MODULE = "sarj_standards.libs.linting.semgrep_sql_composition"


def _finding(source: str, *, rule: str = RULE) -> dict[str, JsonValue]:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute"
    )
    assert call.end_col_offset is not None
    return {
        "check_id": rule,
        "path": "example.py",
        "start": {"line": call.lineno, "col": call.col_offset + 1},
        "end": {"line": call.end_lineno, "col": call.end_col_offset + 1},
        "extra": {"message": "upstream finding"},
    }


def _payload(findings: list[dict[str, JsonValue]], *, errors: list[JsonValue] | None = None) -> str:
    return json.dumps({"version": "1.182.0", "results": findings, "errors": errors or []})


def _apply(tmp_path: Path, source: str, *, raw: int = 1) -> Correction:
    (tmp_path / "example.py").write_text(source, encoding="utf-8")
    return correct(_payload([_finding(source)]), source_root=tmp_path, raw_exit_status=raw)


def test_safe_local_abc_class_literal_and_nested_bound_values(tmp_path: Path) -> None:
    correction = _apply(tmp_path, _SAFE)
    effective, status = correction.report, correction.exit_status
    assert status == 0
    assert effective["results"] == []
    assert effective["errors"] == []


@pytest.mark.parametrize("expression", _UNSAFE)
def test_dynamic_or_unknown_composition_stays_failed(tmp_path: Path, expression: str) -> None:
    source = f"from psycopg.sql import SQL\ncursor.execute({expression}, (ids,))\n"
    correction = _apply(tmp_path, source)
    effective, status = correction.report, correction.exit_status
    assert status == 1
    assert effective["results"] == [_finding(source)]


@pytest.mark.parametrize(
    "suffix",
    [
        "\nSQL = unknown\n",
        "\nQUERY = unknown\n",
        "\nRepository.FIELDS = user\n",
        "\nclass Child(Repository):\n    FIELDS = user\n",
        "\nQUERY._obj = user\n",
        "\nRepository.__getattribute__ = lambda self, key: user\n",
        "\nRows.__getattribute__ = lambda self, key: user\n",
        "\nRepository.__bases__ = (Unknown,)\n",
        "\npatch = setattr\npatch(Repository, 'FIELDS', user)\n",
        "\n(other := QUERY)._obj = user\n",
        "\ndef escape(self):\n    self.saved = QUERY\n    self.saved._obj = user\n",
        "\nunknown(QUERY)\n",
        "\nmutator = QUERY.__setattr__\nmutator('_obj', user)\n",
        "\ndef mutation():\n    return QUERY.__setattr__\nmutation()('_obj', user)\n",
        "\n(lambda: QUERY.__setattr__)()('_obj', user)\n",
        "\ndef captured():\n    return QUERY.unknown\ncaptured()()\n",
        "\n(lambda: QUERY.unknown)()()\n",
        "\ndef captured():\n    yield QUERY\n",
        "\nreceiver = QUERY\nreceiver.unknown()\n",
        "\nunknown({'query': QUERY})\n",
        "\nsaved = SQL('{}').format(QUERY)\nunknown(saved)\n",
        "\nAlias = Repository\nclass Child(Alias):\n    FIELDS = user\n",
        "\nunknown(Repository)\n",
        "\n(other := QUERY)\nother._obj = user\n",
        "\na, = (abc,)\na.ABC = Unknown\n",
        "\nother, = (QUERY,)\nother._obj = user\n",
        "\nother = QUERY\nother._obj = user\n",
        "\nsetattr(Repository, 'FIELDS', user)\n",
        "\nmatch user:\n    case SQL:\n        pass\n",
    ],
)
def test_rebinding_subclasses_and_mutation_stay_failed(tmp_path: Path, suffix: str) -> None:
    correction = _apply(tmp_path, _SAFE + suffix)
    _, status = correction.report, correction.exit_status
    assert status == 1


@pytest.mark.parametrize(
    "access",
    [
        "marker.__globals__['QUERY']._obj = user",
        "getattr(marker, '__globals__')['QUERY']._obj = user",
        "namespace = object.__getattribute__(marker, '__globals__')\nnamespace.update(QUERY=SQL(user))",
        "reader = object.__getattribute__\nnamespace = reader(marker, '__globals__')\nnamespace.update(QUERY=SQL(user))",
        "reader = getattr\nnamespace = reader(marker, '__globals__')\nnamespace.update(QUERY=SQL(user))",
        "import builtins\nreader = builtins.getattr\nnamespace = reader(marker, '__globals__')\nnamespace.update(QUERY=SQL(user))",
    ],
)
def test_function_namespace_introspection_stays_unproven(tmp_path: Path, access: str) -> None:
    source = f"{_SAFE}\ndef marker():\n    pass\n{access}\n"
    assert _apply(tmp_path, source).exit_status == 1


@pytest.mark.parametrize("attribute", ["__closure__", "f_globals", "f_locals", "gi_frame", "cr_frame", "ag_frame"])
def test_frame_and_closure_introspection_stays_unproven(tmp_path: Path, attribute: str) -> None:
    source = _SAFE + f"\nnamespace = unknown.{attribute}\nnamespace.update(QUERY=SQL(user))\n"
    assert _apply(tmp_path, source).exit_status == 1


def test_verified_nested_type_lookup_does_not_capture_owner(tmp_path: Path) -> None:
    source = _SAFE.replace("    FIELDS: ClassVar", "    class Record:\n        pass\n    FIELDS: ClassVar")
    source += "\nRepository.Record()\n"
    assert _apply(tmp_path, source).exit_status == 0


def test_verified_staticmethod_lookup_does_not_capture_owner(tmp_path: Path) -> None:
    source = _SAFE.replace(
        "    FIELDS: ClassVar", "    @staticmethod\n    def parse(value):\n        return value\n    FIELDS: ClassVar"
    )
    source += "\nRepository.parse('fixed')\n"
    assert _apply(tmp_path, source).exit_status == 0


@pytest.mark.parametrize("body", ["unknown(__class__)", "super()"])
def test_staticmethod_implicit_class_capture_stays_unproven(tmp_path: Path, body: str) -> None:
    source = _SAFE.replace(
        "    FIELDS: ClassVar", f"    @staticmethod\n    def hook():\n        {body}\n    FIELDS: ClassVar"
    )
    source += "\nRepository.hook()\n"
    assert _apply(tmp_path, source).exit_status == 1


@pytest.mark.parametrize("member", ["parse", "Record"])
def test_unbound_namespace_lookup_still_rejects_protected_arguments(tmp_path: Path, member: str) -> None:
    declarations = "    class Record:\n        pass\n    @staticmethod\n    def parse(value):\n        return value\n"
    source = _SAFE.replace("    FIELDS: ClassVar", f"{declarations}    FIELDS: ClassVar")
    argument = "Repository" if member == "parse" else "QUERY"
    source += f"\nRepository.{member}({argument})\n"
    assert _apply(tmp_path, source).exit_status == 1


def test_classmethod_lookup_keeps_owner_capture_unproven(tmp_path: Path) -> None:
    source = _SAFE.replace(
        "    FIELDS: ClassVar", "    @classmethod\n    def parse(cls):\n        return None\n    FIELDS: ClassVar"
    )
    source += "\nRepository.parse()\n"
    assert _apply(tmp_path, source).exit_status == 1


def test_unresolved_long_alias_chain_stays_failed(tmp_path: Path) -> None:
    statements = [f"    alias_{index} = alias_{index - 1}" for index in range(40, 0, -1)]
    source = _SAFE + "\ndef unrelated_aliases():\n" + "\n".join(statements) + "\n    alias_0 = QUERY\n"
    correction = _apply(tmp_path, source)
    assert correction.exit_status == 1


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("def fetch(self, cursor, ids):", "def fetch(self, cursor, ids, SQL):"),
        ("class Rows(abc.ABC):", "class Rows(Unknown):"),
        ("ClassVar[LiteralString]", "str"),
        ("SQL(self.FIELDS)", "SQL(other.FIELDS)"),
        (
            "class Rows(abc.ABC):\n    pass",
            "class Rows(abc.ABC):\n    def __getattribute__(self, name):\n        return user",
        ),
        ("SQL(self.FIELDS)", "SQL(self.__dict__['FIELDS'])"),
        ("def fetch(self, cursor, ids):", "def fetch(self, cursor, ids):\n        self = other"),
    ],
)
def test_shadowing_annotation_and_lookup_provenance_stay_failed(tmp_path: Path, before: str, after: str) -> None:
    correction = _apply(tmp_path, _SAFE.replace(before, after))
    _, status = correction.report, correction.exit_status
    assert status == 1


@pytest.mark.parametrize("raw", [0, 1, 2, 7])
def test_other_findings_errors_and_raw_failures_are_preserved(tmp_path: Path, raw: int) -> None:
    (tmp_path / "example.py").write_text(_SAFE, encoding="utf-8")
    other = _finding(_SAFE, rule="unrelated.rule")
    errors: list[JsonValue] = [{"message": "engine error"}]
    correction = correct(_payload([_finding(_SAFE), other], errors=errors), source_root=tmp_path, raw_exit_status=raw)
    effective, status = correction.report, correction.exit_status
    assert status == (raw or 1)
    assert effective["results"] == [other]
    assert effective["errors"] == errors
    correction = _apply(tmp_path, _SAFE, raw=raw)
    _, safe_status = correction.report, correction.exit_status
    assert safe_status == (0 if raw in {0, 1} else raw)


@pytest.mark.parametrize("raw", [0, 1, 2])
def test_empty_findings_cannot_clear_unexplained_failed_status(tmp_path: Path, raw: int) -> None:
    correction = correct(_payload([]), source_root=tmp_path, raw_exit_status=raw)
    _, status = correction.report, correction.exit_status
    assert status == raw


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        "{",
        '{"version":"1.182.0","results":{},"errors":[]}',
        '{"version":"1.182.0","results":[],"results":[],"errors":[]}',
        '{"version":"other","results":[],"errors":[]}',
        '{"version":"1.182.0","results":[],"errors":NaN}',
    ],
)
def test_malformed_protocol_is_rejected(tmp_path: Path, payload: str) -> None:
    with pytest.raises(ValueError, match=r"JSON|report|Semgrep|Expecting|validation"):
        correct(payload, source_root=tmp_path, raw_exit_status=1)


def test_paths_syntax_and_span_fail_closed(tmp_path: Path) -> None:
    finding = _finding(_SAFE)
    finding["path"] = "../outside.py"
    with pytest.raises(ValueError, match="outside"):
        correct(_payload([finding]), source_root=tmp_path, raw_exit_status=1)
    outside = tmp_path.parent / "external.py"
    outside.write_text(_SAFE, encoding="utf-8")
    (tmp_path / "example.py").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        correct(_payload([_finding(_SAFE)]), source_root=tmp_path, raw_exit_status=1)
    (tmp_path / "example.py").unlink()
    (tmp_path / "example.py").write_text("invalid syntax !!!", encoding="utf-8")
    with pytest.raises(SyntaxError):
        correct(_payload([_finding(_SAFE)]), source_root=tmp_path, raw_exit_status=1)
    (tmp_path / "example.py").write_text(_SAFE, encoding="utf-8")
    finding = _finding(_SAFE)
    finding["end"] = {"line": 1, "col": 1}
    correction = correct(_payload([finding]), source_root=tmp_path, raw_exit_status=1)
    effective, status = correction.report, correction.exit_status
    assert status == 1
    assert effective["results"] == [finding]


@pytest.mark.parametrize("raw", [-1, 256, 512])
def test_invalid_raw_status_is_rejected(tmp_path: Path, raw: int) -> None:
    with pytest.raises(ValueError, match="exit status"):
        correct(_payload([]), source_root=tmp_path, raw_exit_status=raw)


def test_cli_preserves_raw_artifact_and_rejects_same_output(tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text(_SAFE, encoding="utf-8")
    raw, effective = tmp_path / "raw.json", tmp_path / "effective.json"
    payload = _payload([_finding(_SAFE)])
    raw.write_text(payload, encoding="utf-8")
    command = (
        sys.executable,
        "-m",
        _MODULE,
        "--input",
        str(raw),
        "--source-root",
        str(tmp_path),
        "--raw-exit-status",
        "1",
    )
    result = subprocess.run((*command, "--output", str(effective)), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert raw.read_text(encoding="utf-8") == payload
    assert effective.is_file()
    result = subprocess.run((*command, "--output", str(raw)), capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert raw.read_text(encoding="utf-8") == payload
    raw.write_text("{", encoding="utf-8")
    result = subprocess.run((*command, "--output", str(effective)), capture_output=True, text=True, check=False)
    assert result.returncode != 0


def test_hardlinked_output_cannot_change_raw_input(tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text(_SAFE, encoding="utf-8")
    raw, output = tmp_path / "raw.json", tmp_path / "linked.json"
    payload = _payload([_finding(_SAFE)])
    raw.write_text(payload, encoding="utf-8")
    output.hardlink_to(raw)
    process = subprocess.run(
        (
            sys.executable,
            "-m",
            _MODULE,
            "--input",
            str(raw),
            "--output",
            str(output),
            "--source-root",
            str(tmp_path),
            "--raw-exit-status",
            "1",
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode != 0
    assert raw.read_text(encoding="utf-8") == payload


@pytest.mark.parametrize("mixed", [False, True])
def test_pinned_native_rule_reproduces_and_preserves_unsafe_findings(tmp_path: Path, mixed: bool) -> None:
    evidence = parse_json((_FIXTURES / "upstream.json").read_text(encoding="utf-8"))
    assert isinstance(evidence, dict)
    rule = Path("rules/python/sqlalchemy/security/sqlalchemy-execute-raw-query.yaml")
    assert hashlib.sha256((_FIXTURES / rule).read_bytes()).hexdigest() == evidence["sha256"]
    shutil.copytree(_FIXTURES / "rules", tmp_path / "rules")
    (tmp_path / "example.py").write_text(_SAFE, encoding="utf-8")
    targets = ["example.py"]
    if mixed:
        for index, expression in enumerate(_UNSAFE):
            name = f"unsafe_{index}.py"
            (tmp_path / name).write_text(
                f"from psycopg.sql import SQL\ncursor.execute({expression}, (ids,))\n", encoding="utf-8"
            )
            targets.append(name)
        (tmp_path / "assigned.py").write_text(
            'query = "SELECT {}".format(user)\ncursor.execute(query, (ids,))\n', encoding="utf-8"
        )
        targets.append("assigned.py")
    result = _native_scan(tmp_path, rule, targets)
    assert result.returncode == 1, result.stderr
    report = parse_json(result.stdout)
    assert isinstance(report, dict)
    assert report["errors"] == []
    raw = report["results"]
    assert isinstance(raw, list)
    assert len(raw) == (9 if mixed else 1)
    correction = correct(result.stdout, source_root=tmp_path, raw_exit_status=result.returncode)
    effective, status = correction.report, correction.exit_status
    assert status == int(mixed)
    retained = effective["results"]
    assert isinstance(retained, list)
    assert len(retained) == (8 if mixed else 0)
    assert all(finding in raw for finding in retained)


def _native_scan(tmp_path: Path, rule: Path, targets: list[str]) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("uvx")
    assert executable is not None
    environment = credential_free_environment()
    environment.update(
        {"SEMGREP_LOG_FILE": str(tmp_path / "semgrep.log"), "SEMGREP_SETTINGS_FILE": str(tmp_path / "settings.yml")}
    )
    return subprocess.run(
        (
            executable,
            "--no-config",
            "--isolated",
            "--python",
            "3.12",
            "--from",
            "semgrep==1.182.0",
            "semgrep",
            "scan",
            "--config",
            str(rule),
            "--json",
            "--metrics=off",
            "--disable-version-check",
            "--quiet",
            "--strict",
            "--error",
            "--jobs=1",
            *targets,
        ),
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
