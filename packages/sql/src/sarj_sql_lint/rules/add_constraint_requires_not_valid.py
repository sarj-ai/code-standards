from __future__ import annotations

from bisect import bisect_right
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    StatementFragment,
    is_dump_file,
    is_generated_migration,
    is_postgres_migration,
    locate,
    mask_sql_literals_and_comments,
    split_statements,
)
from sarj_sql_lint.rules._constraint_analysis import (
    TableKey,
    Token,
    alter_table,
    consume,
    drop_table,
    fresh_create_table,
    identifier,
    migration_section_lines,
    sequence,
    table_actions,
    tokenize,
    top_level_tokens,
)


if TYPE_CHECKING:
    from pathlib import Path


_SAFE_BETWEEN_CREATE_AND_ALTER = frozenset({"COMMENT", "CREATE", "DROP", "GRANT", "REVOKE", "SET"})


@final
class AddConstraintRequiresNotValid(Rule):
    id = "existing-table-check-or-foreign-key-requires-not-valid"
    code = "SARJ111"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="CHECK and foreign-key constraints added to existing PostgreSQL tables should defer validation.",
        rationale=(
            "Validating a CHECK or foreign key while adding it scans existing rows while PostgreSQL holds locks "
            "that can block writes to the altered table and, for a foreign key, the referenced table."
        ),
        remediation=(
            "Add the constraint with NOT VALID and commit that migration or transaction. Validate it in a later "
            "committed migration or transaction so the lower-lock validation scan does not inherit the ADD lock."
        ),
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        aliases=(
            "add-constraint-not-valid",
            "add-constraint-requires-not-valid",
            "existing-table-check-or-fk-requires-not-valid",
        ),
        limitations=(
            "Only PostgreSQL migration files and ALTER TABLE actions that directly add CHECK or foreign-key constraints are inspected.",
            "Foreign keys may use the referenced table's implicit primary key; NOT VALID and NOT ENFORCED constraints do not require deferred validation advice.",
            "A table is treated as fresh only after an unconditional empty CREATE TABLE in the same migration section; ambiguous or populating statements revoke that exemption.",
            "Migration sections, executing table or materialized-view creation, extensions, and existing-table column rewrites revoke earlier empty-table proofs. Relation-resolution settings revoke unqualified proofs while preserving explicit schema identity; nonexecuting DDL retains them.",
            "Validation transactions are not inferred; the diagnostic explains that VALIDATE CONSTRAINT belongs in a later committed migration or transaction.",
        ),
        examples=(
            RuleExample(
                example_id="quoted-lowercase-fresh-table",
                title="Quoted lowercase names retain the fresh empty-table exemption",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_boundary.sql",
                        'CREATE TABLE "users" (age integer);\nALTER TABLE users ADD CHECK (age >= 18);\n',
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_boundary.sql"),
                expected_count=0,
                public=True,
                scenario="semantic-boundary",
            ),
            RuleExample(
                example_id="quoted-mixed-case-distinct-table",
                title="A mixed-case quoted name does not exempt a different existing table",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_boundary.sql",
                        'CREATE TABLE "Users" (age integer);\nALTER TABLE users ADD CHECK (age >= 18);\n',
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_boundary.sql"),
                expected_count=1,
                public=True,
                scenario="semantic-boundary",
            ),
            RuleExample(
                example_id="validating-check-constraint",
                title="Constraint validated while it is added",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_age.sql",
                        "ALTER TABLE public.users ADD CONSTRAINT check_age CHECK (age >= 18);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_age.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="deferred-check-validation",
                title="Constraint validation is deferred to a later migration",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_age.sql",
                        "ALTER TABLE public.users ADD CONSTRAINT check_age CHECK (age >= 18) NOT VALID;\n",
                    ),
                    ExampleFile.sql(
                        "supabase/migrations/002_validate_age.sql",
                        "ALTER TABLE public.users VALIDATE CONSTRAINT check_age;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_age.sql"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="renamed-existing-relation-reuses-fresh-name",
                title="An existing relation cannot inherit a former fresh spelling",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_renamed.sql",
                        "CREATE TABLE scratch (id bigint);\nALTER TABLE scratch RENAME TO scratch_empty;\nALTER TABLE old_existing RENAME TO scratch;\nALTER TABLE scratch ADD CONSTRAINT positive_id CHECK (id > 0);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_renamed.sql"),
                expected_count=1,
                public=True,
                scenario="relation-rename-ownership",
            ),
            RuleExample(
                example_id="renamed-existing-relation-defers-validation",
                title="A reused relation name safely defers constraint validation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_renamed.sql",
                        "CREATE TABLE scratch (id bigint);\nALTER TABLE scratch RENAME TO scratch_empty;\nALTER TABLE old_existing RENAME TO scratch;\nALTER TABLE scratch ADD CONSTRAINT positive_id CHECK (id > 0) NOT VALID;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_renamed.sql"),
                expected_count=0,
                public=True,
                scenario="relation-rename-ownership",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            is_dump_file(source, path)
            or is_generated_migration(path, source)
            or not is_postgres_migration(path, source)
        ):
            return []

        diags: list[Diagnostic] = []
        masked = mask_sql_literals_and_comments(source)
        fresh_tables: set[TableKey] = set()
        sections = migration_section_lines(source)
        previous_section = -1
        for statement in split_statements(masked):
            tokens = tokenize("\n".join(fragment for _, fragment in statement))
            if tokens is None or not tokens:
                fresh_tables.clear()
                continue
            section = bisect_right(sections, locate(statement, tokens[0].start).line)
            if section != previous_section:
                fresh_tables.clear()
                previous_section = section

            _update_fresh_table_proof(tokens, fresh_tables)
            altered = alter_table(tokens)
            if altered is not None:
                table, actions, _, _ = altered
                diags.extend(_constraint_action_findings(actions, table, fresh_tables, statement, path, code=self.code))

        return diags


def _update_fresh_table_proof(tokens: list[Token], fresh_tables: set[TableKey]) -> None:
    resolution_setting = _changes_relation_resolution(tokens)
    if resolution_setting:
        fresh_tables.intersection_update({table for table in fresh_tables if len(table) > 1})
    if _revokes_freshness(tokens, fresh_tables):
        fresh_tables.clear()
    created = fresh_create_table(tokens)
    if created is not None:
        fresh_tables.add(created)
        return
    altered = alter_table(tokens)
    if altered is not None:
        table, _, can_attach_existing_rows, renamed_to = altered
        _update_fresh_tables_after_alter(
            fresh_tables, table, renamed_to=renamed_to, can_attach_existing_rows=can_attach_existing_rows
        )
        return
    dropped = drop_table(tokens)
    if dropped is not None:
        fresh_tables.discard(dropped)
        return
    if tokens[0].text.upper() not in _SAFE_BETWEEN_CREATE_AND_ALTER and not resolution_setting:
        fresh_tables.clear()


def _changes_relation_resolution(tokens: list[Token]) -> bool:
    if consume(tokens, 0, "SET") or consume(tokens, 0, "RESET"):
        cursor = 1
        if consume(tokens, cursor, "LOCAL") or consume(tokens, cursor, "SESSION"):
            cursor += 1
        setting = identifier(tokens, cursor)
        if setting is not None and setting[0][0].casefold() in {
            "search_path",
            "schema",
            "role",
            "authorization",
            "session_authorization",
            "all",
        }:
            return True
    return False


def _revokes_freshness(tokens: list[Token], fresh_tables: set[TableKey]) -> bool:
    if consume(tokens, 0, "CREATE"):
        return _creation_executes_query(tokens)
    altered = table_actions(tokens)
    return (
        altered is not None
        and altered[0] not in fresh_tables
        and any(_rewrites_existing_column(action) for action in altered[1])
    )


def _creation_executes_query(tokens: list[Token]) -> bool:
    if consume(tokens, 1, "EXTENSION"):
        return True
    top = top_level_tokens(tokens)
    if not any(consume(top, cursor, "AS") for cursor in range(len(top))):
        return False
    if any(sequence(top, cursor, ("WITH", "NO", "DATA")) for cursor in range(len(top))):
        return False
    return any(consume(top, cursor, kind) for cursor in range(1, len(top)) for kind in ("TABLE", "MATERIALIZED"))


def _rewrites_existing_column(action: list[Token]) -> bool:
    if consume(action, 0, "ALTER"):
        cursor = 2 if consume(action, 1, "COLUMN") else 1
        column = identifier(action, cursor)
        return column is not None and (
            consume(action, column[1], "TYPE") or sequence(action, column[1], ("SET", "DATA", "TYPE"))
        )
    if not consume(action, 0, "ADD"):
        return False
    top = top_level_tokens(action)
    return any(consume(top, cursor, word) for cursor in range(len(top)) for word in ("DEFAULT", "GENERATED"))


def _update_fresh_tables_after_alter(
    fresh_tables: set[TableKey],
    table: TableKey,
    *,
    renamed_to: TableKey | None,
    can_attach_existing_rows: bool,
) -> None:
    if renamed_to is not None and table in fresh_tables:
        fresh_tables.discard(table)
        fresh_tables.add(renamed_to)
    if can_attach_existing_rows:
        fresh_tables.discard(table)


def _constraint_action_findings(
    actions: list[list[Token]],
    table: TableKey,
    fresh_tables: set[TableKey],
    statement: list[StatementFragment],
    path: Path,
    *,
    code: str,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for action in actions:
        if table in fresh_tables or _action_skips_validation(action):
            continue
        location = locate(statement, action[0].start)
        diags.append(
            Diagnostic(
                path=path,
                line=location.line,
                col=location.column,
                code=code,
                message=(
                    "Add this CHECK or foreign-key constraint with `NOT VALID`, commit that "
                    "migration or transaction, then run `VALIDATE CONSTRAINT` in a later one."
                ),
            )
        )
    return diags


def _action_skips_validation(action: list[Token]) -> bool:
    depth = 0
    for index, token in enumerate(action[:-1]):
        if token.text == "(":
            depth += 1
            continue
        if token.text == ")":
            depth -= 1
            continue
        if depth == 0 and token.text.upper() == "NOT" and action[index + 1].text.upper() in {"VALID", "ENFORCED"}:
            return True
    return False
