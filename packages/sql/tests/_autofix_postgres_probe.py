from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory, gettempdir
from time import monotonic
from typing import TYPE_CHECKING, Literal
from uuid import uuid7

from sarj_rule_contracts import RuleId

from sarj_sql_lint.autofix import fix_source
from sarj_sql_lint.rules import REGISTRY


if TYPE_CHECKING:
    from types import FrameType
    from typing import NoReturn


_IMAGE = "docker.io/library/postgres@sha256:9770878138a2e83abcb10856d30cc3f24dae0d317bb956db6ab9159de6c3c80d"
_LABEL = "ai.sarj.code-standards.autofix-probe"
_PATH = Path("supabase/queries/literals.sql")
_ROOT = Path(__file__).resolve().parents[3]
_TIMEOUT_SECONDS = 60
_READINESS_SECONDS = 45
_SHORT_TIMEOUT_SECONDS = 5
_MESSAGE_LIMIT = 2000
_PG18_MIN = 180000
_PG19_MIN = 190000
_CID = re.compile(r"[0-9a-f]{64}\Z")
_ZONES = ("UTC", "America/New_York", "Asia/Kathmandu")
_SOURCE_PATHS = (
    "packages/sql/tests/_autofix_postgres_probe.py",
    "packages/sql/src/sarj_sql_lint/autofix.py",
    "packages/sql/src/sarj_sql_lint/_autofix_literals.py",
    "packages/sql/src/sarj_sql_lint/_postgres.py",
    "packages/sql/src/sarj_sql_lint/rule_base.py",
    "packages/sql/src/sarj_sql_lint/rules/enforce_timestamptz.py",
    "packages/sql/src/sarj_sql_lint/rules/prefer_text_over_varchar.py",
    "packages/sql/src/sarj_sql_lint/rules/prefer_jsonb.py",
    "packages/contracts/src/sarj_rule_contracts/autofix.py",
)


@dataclass(frozen=True, slots=True)
class _Case:
    rule_id: RuleId
    source: str
    column: str
    datatype: str
    table: str | None


@dataclass(frozen=True, slots=True)
class _Comparison:
    case: _Case
    fixed: str


@dataclass(frozen=True, slots=True)
class _Report:
    status: Literal["passed"]
    image: str
    server_version_num: int
    rule_ids: list[RuleId]
    comparison_cases: int
    rejected_counterexamples: list[str]
    container_removed: bool
    source_sha256: dict[str, str]


class _ProbeError(RuntimeError):
    pass


def main() -> None:
    temporary_base = _temporary_base()
    before = _source_hashes()
    comparisons = _comparisons()
    _check_refusals()
    with TemporaryDirectory(prefix="sarj-postgres-autofix-", dir=temporary_base) as directory:
        container = _Container(Path(directory))
        signal.signal(signal.SIGINT, _interrupted)
        signal.signal(signal.SIGTERM, _interrupted)
        try:
            container.start()
            version = int(container.sql("SELECT current_setting('server_version_num');").strip())
            if not _PG18_MIN <= version < _PG19_MIN:
                msg = f"expected PostgreSQL18, observed {version}"
                raise _ProbeError(msg)
            _expect_true(container.sql(_session_comparisons(comparisons)), len(comparisons) * len(_ZONES))
            _expect_true(container.sql(_prepared_comparisons(comparisons)), len(comparisons) * len(_ZONES[1:]))
            _expect_true(container.sql(_rejected_prepared_timezone()), len(_ZONES[1:]))
            _expect_true(container.sql(_rejected_column_label()), 1)
        finally:
            container.remove()
    if _source_hashes() != before:
        msg = "a probe implementation changed during verification"
        raise _ProbeError(msg)
    report = _Report(
        status="passed",
        image=_IMAGE,
        server_version_num=version,
        rule_ids=sorted({comparison.case.rule_id for comparison in comparisons}),
        comparison_cases=len(comparisons),
        rejected_counterexamples=["prepared-timezone", "unaliased-column-label"],
        container_removed=container.removed,
        source_sha256=before,
    )
    sys.stdout.write(json.dumps(asdict(report), sort_keys=True) + "\n")


def _temporary_base() -> Path:
    configured = os.environ.get("TMPDIR")  # ruff: ignore[banned-api] -- Verify the runner's actual temporary-directory contract.
    if configured is None:
        msg = "TMPDIR must identify the verified private temporary base"
        raise _ProbeError(msg)
    expected = Path(configured).resolve()
    if Path(gettempdir()).resolve() != expected:
        msg = "Python's actual temporary directory differs from configured TMPDIR"
        raise _ProbeError(msg)
    return expected


def _source_hashes() -> dict[str, str]:
    return {path: sha256((_ROOT / path).read_bytes()).hexdigest() for path in _SOURCE_PATHS}


def _comparisons() -> list[_Comparison]:
    comparisons: list[_Comparison] = []
    for case in _cases():
        rule = REGISTRY[case.rule_id]()
        if len(rule.check(_PATH, case.source)) != 1:
            msg = f"{case.rule_id}: expected one original native finding"
            raise _ProbeError(msg)
        fixed = fix_source(_PATH, case.source, rule_ids=[case.rule_id])
        if fixed == case.source or rule.check(_PATH, fixed):
            msg = f"{case.rule_id}: expected a real fix with no remaining owned finding"
            raise _ProbeError(msg)
        if fix_source(_PATH, fixed, rule_ids=[case.rule_id]) != fixed:
            msg = f"{case.rule_id}: fix did not converge"
            raise _ProbeError(msg)
        comparisons.append(_Comparison(case=case, fixed=fixed))
    return comparisons


def _cases() -> list[_Case]:
    return [
        _Case(
            rule_id=RuleId("prefer-text-over-varchar"),
            source="SELECT CAST(CAST('abc' AS pg_catalog.varchar(8)) AS pg_catalog.text) AS name;",
            column="name",
            datatype="text",
            table=None,
        ),
        _Case(
            rule_id=RuleId("prefer-text-over-varchar"),
            source="SELECT ('abc'::pg_catalog.varchar(3))::pg_catalog.text AS name;",
            column="name",
            datatype="text",
            table=None,
        ),
        *[
            _Case(
                rule_id=RuleId("prefer-jsonb"),
                source="CREATE TABLE IF NOT EXISTS document (metadata pg_catalog.jsonb DEFAULT "
                f"('{literal}'::pg_catalog.json)::pg_catalog.jsonb);",
                column="metadata",
                datatype="jsonb",
                table="document",
            )
            for literal in ("{}", "[]")
        ],
        _Case(
            rule_id=RuleId("enforce-timestamptz"),
            source="SELECT pg_catalog.timezone(INTERVAL '00:00', "
            "CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp)) AS instant;",
            column="instant",
            datatype="timestamptz",
            table=None,
        ),
        _Case(
            rule_id=RuleId("enforce-timestamptz"),
            source="SELECT CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp) "
            "AT TIME ZONE INTERVAL '00:00' AS instant;",
            column="instant",
            datatype="timestamptz",
            table=None,
        ),
        _Case(
            rule_id=RuleId("enforce-timestamptz"),
            source="CREATE TABLE IF NOT EXISTS events (at pg_catalog.timestamptz DEFAULT "
            "pg_catalog.timezone(INTERVAL '00:00', CAST('2024-02-29 23:59:59' AS pg_catalog.timestamp)));",
            column="at",
            datatype="timestamptz",
            table="events",
        ),
    ]


def _check_refusals() -> None:
    for source in (
        "SELECT CAST(CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp) AS pg_catalog.timestamptz) AS instant;",
        "SELECT pg_catalog.timezone(INTERVAL '00:00', CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp));",
        "SELECT pg_catalog.timezone('UTC', CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp)) AS instant;",
    ):
        if fix_source(_PATH, source, rule_ids=["enforce-timestamptz"]) != source:
            msg = "timestamp fixer accepted a rejected timezone/label boundary"
            raise _ProbeError(msg)


def _session_comparisons(comparisons: list[_Comparison]) -> str:
    statements: list[str] = []
    for zone in _ZONES:
        for comparison in comparisons:
            statements.extend(
                [
                    "BEGIN;",
                    f"SET LOCAL TimeZone = '{zone}';",
                    "CREATE TEMP TABLE probe_namespace (initialized boolean);",
                    _relations(comparison),
                    _same_result(comparison.case),
                    "ROLLBACK;",
                ]
            )
    return "\n".join(statements)


def _relations(comparison: _Comparison) -> str:
    case = comparison.case
    if case.table is None:
        return f"CREATE TEMP VIEW probe_old AS {case.source}\nCREATE TEMP VIEW probe_new AS {comparison.fixed}"
    return (
        _renamed_table(case.source, case.table, "probe_old")
        + "\n"
        + _renamed_table(comparison.fixed, case.table, "probe_new")
        + "\nINSERT INTO pg_temp.probe_old DEFAULT VALUES;"
        "\nINSERT INTO pg_temp.probe_new DEFAULT VALUES;"
    )


def _renamed_table(source: str, original: str, replacement: str) -> str:
    prefix = f"CREATE TABLE IF NOT EXISTS {original} "
    if not source.startswith(prefix):
        msg = "unexpected authored DEFAULT fixture target"
        raise _ProbeError(msg)
    return source.replace(prefix, f"CREATE TABLE IF NOT EXISTS pg_temp.{replacement} ", 1)


def _same_result(case: _Case) -> str:
    return (
        "SELECT (SELECT to_jsonb(observed) FROM pg_temp.probe_old AS observed) = "  # ruff: ignore[hardcoded-sql-expression] -- Identifiers and types come only from the authored _cases fixtures.
        "(SELECT to_jsonb(observed) FROM pg_temp.probe_new AS observed) AND "
        f"(SELECT pg_typeof({case.column}) FROM pg_temp.probe_old) = 'pg_catalog.{case.datatype}'::regtype AND "
        f"(SELECT pg_typeof({case.column}) FROM pg_temp.probe_new) = 'pg_catalog.{case.datatype}'::regtype AND "
        f"{_metadata('probe_old')} = {_metadata('probe_new')};"
    )


def _metadata(table: str) -> str:
    return (
        "(SELECT array_agg(ROW(attname, atttypid, atttypmod, attcollation)::text ORDER BY attnum) "  # ruff: ignore[hardcoded-sql-expression] -- Callers supply only the two authored temporary relation names.
        f"FROM pg_catalog.pg_attribute WHERE attrelid = 'pg_temp.{table}'::regclass "
        "AND attnum > 0 AND NOT attisdropped)"
    )


def _prepared_comparisons(comparisons: list[_Comparison]) -> str:
    statements: list[str] = []
    for comparison in comparisons:
        statements.extend(["BEGIN;", "SET LOCAL TimeZone = 'UTC';"])
        if comparison.case.table is not None:
            statements.extend(["CREATE TEMP TABLE probe_namespace (initialized boolean);", _relations(comparison)])
        statements.extend(
            [
                f"PREPARE probe_old_query AS {_prepared_query(comparison.case, comparison.case.source, 'probe_old')};",
                f"PREPARE probe_new_query AS {_prepared_query(comparison.case, comparison.fixed, 'probe_new')};",
            ]
        )
        for zone in _ZONES[1:]:
            statements.extend(
                [
                    f"SET LOCAL TimeZone = '{zone}';",
                    "EXECUTE probe_old_query\n\\gset old_",
                    "EXECUTE probe_new_query\n\\gset new_",
                    (
                        "SELECT :'old_payload'::pg_catalog.jsonb = :'new_payload'::pg_catalog.jsonb "
                        "AND :'old_value_type' = :'new_value_type';"
                    ),
                ]
            )
        statements.extend(["DEALLOCATE probe_old_query;", "DEALLOCATE probe_new_query;", "ROLLBACK;"])
    return "\n".join(statements)


def _prepared_query(case: _Case, source: str, table: str) -> str:
    projection = f"to_jsonb(observed) AS payload, pg_typeof(observed.{case.column})::text AS value_type"
    if case.table is None:
        return f"SELECT {projection} FROM ({source.removesuffix(';')}) AS observed"  # ruff: ignore[hardcoded-sql-expression] -- Both programs and projection identifiers are authored _cases or their actual selected fixes.
    return f"INSERT INTO pg_temp.{table} AS observed DEFAULT VALUES RETURNING {projection}"  # ruff: ignore[hardcoded-sql-expression] -- The table and projection are fixed probe relation names and authored case identifiers.


def _rejected_prepared_timezone() -> str:
    source = "CAST(CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp) AS pg_catalog.timestamptz)"
    manual = "CAST('2000-01-01 00:00:00+00' AS pg_catalog.timestamptz)"
    statements = [
        "BEGIN;",
        "SET LOCAL TimeZone = 'UTC';",
        f"PREPARE probe_old_query AS SELECT EXTRACT(EPOCH FROM {source}) AS epoch;",  # ruff: ignore[hardcoded-sql-expression] -- source is the immediately authored rejection counterexample above.
        f"PREPARE probe_new_query AS SELECT EXTRACT(EPOCH FROM {manual}) AS epoch;",  # ruff: ignore[hardcoded-sql-expression] -- manual is the immediately authored alternative used to prove inequivalence.
    ]
    for zone in _ZONES[1:]:
        statements.extend(
            [
                f"SET LOCAL TimeZone = '{zone}';",
                "EXECUTE probe_old_query\n\\gset old_",
                "EXECUTE probe_new_query\n\\gset new_",
                "SELECT :'old_epoch'::numeric <> :'new_epoch'::numeric;",
            ]
        )
    statements.extend(["DEALLOCATE probe_old_query;", "DEALLOCATE probe_new_query;", "ROLLBACK;"])
    return "\n".join(statements)


def _rejected_column_label() -> str:
    return (
        "BEGIN; CREATE TEMP VIEW probe_old AS SELECT pg_catalog.timezone(INTERVAL '00:00', "
        "CAST('2000-01-01 00:00:00' AS pg_catalog.timestamp));\n"
        "CREATE TEMP VIEW probe_new AS SELECT CAST('2000-01-01 00:00:00+00' AS pg_catalog.timestamptz);\n"
        "SELECT (SELECT attname FROM pg_catalog.pg_attribute WHERE attrelid='pg_temp.probe_old'::regclass "
        "AND attnum=1) <> (SELECT attname FROM pg_catalog.pg_attribute WHERE "
        "attrelid='pg_temp.probe_new'::regclass AND attnum=1) AND "
        "(SELECT atttypid FROM pg_catalog.pg_attribute WHERE attrelid='pg_temp.probe_old'::regclass "
        "AND attnum=1) = 'pg_catalog.timestamptz'::regtype AND "
        "(SELECT atttypid FROM pg_catalog.pg_attribute WHERE attrelid='pg_temp.probe_new'::regclass "
        "AND attnum=1) = 'pg_catalog.timestamptz'::regtype;\nROLLBACK;"
    )


def _expect_true(output: str, expected: int) -> None:
    if output.splitlines() != ["t"] * expected:
        msg = f"PostgreSQL comparison mismatch: {output[:_MESSAGE_LIMIT]!r}"
        raise _ProbeError(msg)


def _interrupted(number: int, _frame: FrameType | None) -> NoReturn:
    msg = f"interrupted by signal {number}"
    raise _ProbeError(msg)


class _Container:
    def __init__(self, directory: Path) -> None:
        self.token = uuid7().hex
        self.name = f"sarj-sql-autofix-{self.token}"
        self.cidfile = directory / "container.cid"
        self.cid: str | None = None
        self.removed = False

    def start(self) -> None:
        _checked(["docker", "pull", "--platform", "linux/amd64", _IMAGE])
        _checked(
            [
                "docker",
                "create",
                "--platform",
                "linux/amd64",
                "--name",
                self.name,
                "--label",
                f"{_LABEL}={self.token}",
                "--cidfile",
                str(self.cidfile),
                "--network",
                "none",
                "--read-only",
                "--security-opt",
                "no-new-privileges:true",
                "--memory",
                "512m",
                "--memory-swap",
                "512m",
                "--cpus",
                "1",
                "--pids-limit",
                "128",
                "--tmpfs",
                "/var/lib/postgresql:rw,nosuid,nodev,size=256m",
                "--tmpfs",
                "/var/run/postgresql:rw,nosuid,nodev,size=8m",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=16m",  # ruff: ignore[hardcoded-temp-file] -- Container-private bounded tmpfs; no shared host temporary path is mounted.
                "--env",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "--env",
                "POSTGRES_DB=proof",
                "--env",
                "PGDATA=/var/lib/postgresql/18/docker",
                _IMAGE,
                "postgres",
                "-c",
                "shared_buffers=32MB",
                "-c",
                "max_connections=10",
                "-c",
                "autovacuum=off",
                "-c",
                "fsync=off",
                "-c",
                "jit=off",
                "-c",
                "listen_addresses=",
            ]
        )
        self.cid = self._owned(self.cidfile.read_text().strip())
        _checked(["docker", "start", self.cid])
        self._ready()

    def _owned(self, identifier: str) -> str:
        if _CID.fullmatch(identifier) is None:
            msg = "invalid owned container identifier"
            raise _ProbeError(msg)
        template = '{{.Id}}\t{{index .Config.Labels "' + _LABEL + '"}}'
        identity = _checked(["docker", "inspect", "--type", "container", "--format", template, identifier])
        if identity.stdout.strip() != f"{identifier}\t{self.token}":
            msg = "refusing a container without the exact probe ownership label"
            raise _ProbeError(msg)
        return identifier

    def _ready(self) -> None:
        deadline = monotonic() + _READINESS_SECONDS
        while monotonic() < deadline:
            process = _command(
                ["docker", "exec", self._identifier(), "cat", "/proc/1/comm"], timeout=_SHORT_TIMEOUT_SECONDS
            )
            if process.returncode != 0 or process.stdout.strip() != "postgres":
                continue
            ready = _command(self._psql_command(), payload="SELECT 1;", timeout=_SHORT_TIMEOUT_SECONDS)
            if ready.returncode == 0 and ready.stdout.strip() == "1":
                return
        msg = "PostgreSQL did not complete final server startup within the readiness deadline"
        raise _ProbeError(msg)

    def sql(self, source: str) -> str:
        return _checked(self._psql_command(), payload=source).stdout

    def _psql_command(self) -> list[str]:
        return [
            "docker",
            "exec",
            "--user",
            "postgres",
            "-i",
            self._identifier(),
            "psql",
            "--no-psqlrc",
            "--quiet",
            "--tuples-only",
            "--no-align",
            "--set",
            "ON_ERROR_STOP=1",
            "--username",
            "postgres",
            "--dbname",
            "proof",
        ]

    def _identifier(self) -> str:
        if self.cid is None:
            msg = "container identifier is not available"
            raise _ProbeError(msg)
        return self.cid

    def remove(self) -> None:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        identifier = self.cid or self._recover()
        if identifier is not None:
            identifier = self._owned(identifier)
            _checked(["docker", "rm", "--force", "--volumes", identifier])
            remaining = _checked(["docker", "ps", "--all", "--quiet", "--no-trunc", "--filter", f"id={identifier}"])
            if remaining.stdout.strip():
                msg = "owned container remains after removal"
                raise _ProbeError(msg)
        self.removed = True

    def _recover(self) -> str | None:
        if self.cidfile.is_file():
            identifier = self.cidfile.read_text().strip()
            if _CID.fullmatch(identifier) is not None:
                return identifier
        found = _checked(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--no-trunc",
                "--filter",
                f"name=^/{self.name}$",
                "--filter",
                f"label={_LABEL}={self.token}",
            ]
        ).stdout.splitlines()
        if len(found) > 1:
            msg = "ambiguous owned container recovery"
            raise _ProbeError(msg)
        return found[0] if found else None


def _checked(arguments: list[str], *, payload: str | None = None) -> subprocess.CompletedProcess[str]:
    result = _command(arguments, payload=payload)
    if result.returncode:
        msg = f"command {arguments[0:2]!r} failed: {result.stderr[:_MESSAGE_LIMIT]}"
        raise _ProbeError(msg)
    return result


def _command(
    arguments: list[str], *, payload: str | None = None, timeout: int = _TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    with subprocess.Popen(
        arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as process:
        try:
            output, errors = process.communicate(payload, timeout=timeout)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=_SHORT_TIMEOUT_SECONDS)
        if process.returncode is None:
            msg = "command completed without an exit status"
            raise _ProbeError(msg)
        return subprocess.CompletedProcess(arguments, process.returncode, output, errors)


if __name__ == "__main__":
    main()
