from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.require_fk_index import RequireFkIndex


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


P = Path("migration.sql")


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return RequireFkIndex().check(path, source)


_PUBLIC_EXAMPLES = RequireFkIndex.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(RequireFkIndex().check(Path(focus.path), focus.source)) == example.expected_count


def test_mysql_foreign_keys_do_not_require_a_separate_index() -> None:
    source = """
CREATE TABLE child (
    parent_id BIGINT,
    FOREIGN KEY (parent_id) REFERENCES parent(id)
) ENGINE=InnoDB;
"""
    assert _check(source) == []


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "prisma" / "migrations"
    for name, body in files.items():
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "migration.sql").write_text(body)
    return root


def test_allows_fk_whose_index_arrives_in_a_later_migration(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "20220711182928_add_workflows": (
                'CREATE TABLE "WorkflowsOnEventTypes" (\n'
                '    "eventTypeId" INTEGER NOT NULL,\n'
                '    FOREIGN KEY ("eventTypeId") REFERENCES "EventType"("id")\n'
                ");\n"
            ),
            "20230410234751_add_foreign_key_indexes": (
                'CREATE INDEX "WorkflowsOnEventTypes_eventTypeId_idx"\n    ON "WorkflowsOnEventTypes"("eventTypeId");\n'
            ),
        },
    )
    target = root / "20220711182928_add_workflows" / "migration.sql"
    assert _check(target.read_text(), target) == []


def test_flags_fk_that_no_migration_in_the_tree_indexes(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "20220711182928_add_workflows": (
                'CREATE TABLE "WorkflowsOnEventTypes" (\n'
                '    "eventTypeId" INTEGER NOT NULL,\n'
                '    FOREIGN KEY ("eventTypeId") REFERENCES "EventType"("id")\n'
                ");\n"
            ),
            "20230410234751_add_other_indexes": ('CREATE INDEX "Booking_userId_idx" ON "Booking"("userId");\n'),
        },
    )
    target = root / "20220711182928_add_workflows" / "migration.sql"
    diags = _check(target.read_text(), target)
    assert len(diags) == 1
    assert "eventTypeId".lower() in diags[0].message


def test_tree_scan_does_not_reach_outside_the_migrations_directory(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "20220711182928_add_workflows": (
                'CREATE TABLE "Child" (\n'
                '    "parentId" INTEGER NOT NULL,\n'
                '    FOREIGN KEY ("parentId") REFERENCES "Parent"("id")\n'
                ");\n"
            )
        },
    )
    other = tmp_path / "other_project"
    other.mkdir()
    (other / "indexes.sql").write_text('CREATE INDEX "Child_parentId_idx" ON "Child"("parentId");\n')
    target = root / "20220711182928_add_workflows" / "migration.sql"
    assert len(_check(target.read_text(), target)) == 1


def test_in_memory_source_is_judged_on_its_own_content() -> None:
    src = "CREATE TABLE child (parent_id INT REFERENCES parent(id));"
    assert len(_check(src)) == 1


def test_reports_the_line_of_the_fk_it_names() -> None:
    src = """CREATE TABLE membership (
    account_id INT,
    FOREIGN KEY (account_id) REFERENCES tenant(id),
    FOREIGN KEY (account_id) REFERENCES billing_account(id)
);
"""
    # Both clauses share the text `FOREIGN KEY (account_id) REFERENCES`, so a
    # find()-by-value attributed the second one to the first one's line.
    assert sorted(d.line for d in _check(src)) == [3, 4]


def test_reports_the_line_of_each_inline_reference() -> None:
    src = """CREATE TABLE order_item (
    id INT PRIMARY KEY,
    customer_id INT REFERENCES customer(id),
    product_id INT REFERENCES product(id)
);
"""
    diags = _check(src)
    by_column = {d.message.split("`")[1]: d.line for d in diags}
    assert by_column == {"customer_id": 3, "product_id": 4}


def test_dump_findings_are_kept_and_point_at_the_migration() -> None:
    src = """-- PostgreSQL database dump
-- Dumped by pg_dump version 16.2
CREATE TABLE public.child (parent_id integer REFERENCES public.parent(id));
"""
    diags = RequireFkIndex().check(Path("schema.sql"), src)
    assert len(diags) == 1
    assert "schema dump" in diags[0].message
    assert "add the index in a migration" in diags[0].message


def test_non_dump_findings_keep_the_plain_message() -> None:
    src = "CREATE TABLE child (parent_id INT REFERENCES parent(id));"
    diags = _check(src)
    assert len(diags) == 1
    assert "schema dump" not in diags[0].message


def test_multiline_using_btree_index_covers_the_fk() -> None:
    src = """
    CREATE TABLE orders (user_id UUID REFERENCES users(id));
    CREATE INDEX idx_orders
      ON orders USING btree (user_id);
    """
    assert _check(src) == []


def test_table_level_primary_key_covers_the_fk() -> None:
    src = """
    CREATE TABLE profiles (
        user_id UUID,
        PRIMARY KEY (user_id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """
    assert _check(src) == []


def test_inline_primary_key_column_covers_a_table_level_fk() -> None:
    src = """
    CREATE TABLE profiles (
        user_id UUID PRIMARY KEY,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """
    assert _check(src) == []


def test_inline_unique_column_covers_a_table_level_fk() -> None:
    src = """
    CREATE TABLE profiles (
        user_id UUID UNIQUE,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """
    assert _check(src) == []


def test_table_level_unique_covers_the_fk() -> None:
    source = """
    CREATE TABLE child (
        parent_id BIGINT,
        UNIQUE (parent_id),
        FOREIGN KEY (parent_id) REFERENCES parent(id)
    );
    """
    assert _check(source) == []


def test_nonleading_index_does_not_cover_the_fk() -> None:
    source = """
    CREATE TABLE child (
        id BIGINT,
        parent_id BIGINT REFERENCES parent(id)
    );
    CREATE INDEX child_idx ON child(id, parent_id);
    """
    assert len(_check(source)) == 1


def test_named_inline_constraint_reference_is_checked() -> None:
    src = """
    CREATE TABLE child (
        parent_id INT CONSTRAINT child_parent_fk REFERENCES parent(id)
    );
    """
    diags = _check(src)
    assert len(diags) == 1
    assert (diags[0].line, diags[0].message.split("`")[1]) == (3, "parent_id")


def test_index_covers_a_named_inline_constraint_reference() -> None:
    src = """
    CREATE TABLE child (
        parent_id INT CONSTRAINT child_parent_fk REFERENCES parent(id)
    );
    CREATE INDEX child_parent_id_idx ON child (parent_id);
    """
    assert _check(src) == []


def test_inline_unique_named_constraint_covers_its_reference() -> None:
    src = """
    CREATE TABLE child (
        parent_id INT CONSTRAINT parent_unique UNIQUE CONSTRAINT child_parent_fk REFERENCES parent(id)
    );
    """
    assert _check(src) == []


def test_alter_table_only_composite_fk_is_covered_by_a_concurrent_index() -> None:
    src = """
    CREATE INDEX CONCURRENTLY idx_pdi ON public.pdi (team_id, person_id);

    ALTER TABLE ONLY public.pdi
        ADD CONSTRAINT pdi_person_id_fkey
        FOREIGN KEY (team_id, person_id) REFERENCES person_new(team_id, id) NOT VALID;
    """
    assert _check(src) == []


def test_composite_fk_is_not_covered_by_only_its_first_column() -> None:
    source = """
    CREATE TABLE membership (
        team_id BIGINT,
        person_id BIGINT,
        FOREIGN KEY (team_id, person_id) REFERENCES person(team_id, id)
    );
    CREATE INDEX membership_team_idx ON membership(team_id);
    """

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "team_id, person_id" in diagnostics[0].message


@pytest.mark.parametrize(
    "index_columns",
    ["team_id, person_id", "person_id, team_id", "team_id, person_id, archived_at"],
    ids=("exact-order", "reversed-equality-order", "trailing-column"),
)
def test_composite_fk_requires_all_columns_in_the_index_prefix(index_columns: str) -> None:
    source = f"""
    CREATE TABLE membership (
        team_id BIGINT,
        person_id BIGINT,
        archived_at TIMESTAMPTZ,
        FOREIGN KEY (team_id, person_id) REFERENCES person(team_id, id)
    );
    CREATE INDEX membership_person_idx ON membership({index_columns});
    """

    assert _check(source) == []


def test_composite_fk_uses_a_covering_index_from_a_sibling_migration(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "001_membership": (
                "CREATE TABLE membership (team_id BIGINT, person_id BIGINT, "
                "FOREIGN KEY (team_id, person_id) REFERENCES person(team_id, id));\n"
            ),
            "002_index": "CREATE INDEX membership_person_idx ON membership(person_id, team_id);\n",
        },
    )
    target = root / "001_membership" / "migration.sql"

    assert _check(target.read_text(), target) == []


def test_nested_comment_cannot_create_a_foreign_key_or_index() -> None:
    source = """
    /* outer /* inner */
       CREATE INDEX fake ON child(parent_id);
       FOREIGN KEY (other_id) REFERENCES other(id)
    */
    CREATE TABLE child (parent_id BIGINT REFERENCES parent(id));
    """

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "parent_id" in diagnostics[0].message


def test_postgres_escape_string_cannot_create_a_foreign_key_or_index() -> None:
    source = """
    SELECT E'it\\'s CREATE INDEX fake ON child(parent_id)';
    CREATE TABLE child (parent_id BIGINT REFERENCES parent(id));
    """

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "parent_id" in diagnostics[0].message


def test_alter_add_column_if_not_exists_uses_the_real_fk_column_name() -> None:
    src = """
    ALTER TABLE provisioned_number
      ADD COLUMN IF NOT EXISTS sip_connection_id UUID REFERENCES sip_connection(id);
    CREATE INDEX CONCURRENTLY idx_number_connection
      ON provisioned_number (sip_connection_id) WHERE sip_connection_id IS NOT NULL;
    """

    assert _check(src) == []
