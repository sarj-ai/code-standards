"""SARJ112 — migration-tree index scope, line attribution, and the dump wording."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sarj_sql_lint.rules.require_fk_index import RequireFkIndex


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


P = Path("migration.sql")


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return RequireFkIndex().check(path, source)


# Test covering index in later migration.


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
    """The boundary: widening the scope must not silence a genuinely unindexed FK."""
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
    """The boundary: an index in an unrelated sibling tree must not count."""
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
    """A path that is not a real file must not trigger a filesystem scan."""
    src = "CREATE TABLE child (parent_id INT REFERENCES parent(id));"
    assert len(_check(src)) == 1


# Test line attribution.


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


# Test dump messages.


def test_dump_findings_are_kept_and_point_at_the_migration() -> None:
    """A dump is complete, so an absent CREATE INDEX really is an absent index."""
    src = """-- PostgreSQL database dump
-- Dumped by pg_dump version 16.2
CREATE TABLE public.child (parent_id integer REFERENCES public.parent(id));
"""
    diags = RequireFkIndex().check(Path("schema.sql"), src)
    assert len(diags) == 1
    assert "schema dump" in diags[0].message
    assert "add the index in a migration" in diags[0].message


def test_non_dump_findings_keep_the_plain_message() -> None:
    """The boundary: the dump wording must not leak onto ordinary migrations."""
    src = "CREATE TABLE child (parent_id INT REFERENCES parent(id));"
    diags = _check(src)
    assert len(diags) == 1
    assert "schema dump" not in diags[0].message


# Test covering index spellings.


def test_multiline_using_btree_index_covers_the_fk() -> None:
    src = """
    CREATE TABLE orders (user_id UUID REFERENCES users(id));
    CREATE INDEX idx_orders
      ON orders USING btree (user_id);
    """
    assert _check(src) == []


def test_table_level_primary_key_covers_the_fk() -> None:
    """A PRIMARY KEY is an index; demanding a second one on the same column is noise."""
    src = """
    CREATE TABLE profiles (
        user_id UUID,
        PRIMARY KEY (user_id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """
    assert _check(src) == []


def test_alter_table_only_composite_fk_is_covered_by_a_concurrent_index() -> None:
    """The leading columns of the concurrent index match the composite FK, so it is covered."""
    src = """
    CREATE INDEX CONCURRENTLY idx_pdi ON public.pdi (team_id, person_id);

    ALTER TABLE ONLY public.pdi
        ADD CONSTRAINT pdi_person_id_fkey
        FOREIGN KEY (team_id, person_id) REFERENCES person_new(team_id, id) NOT VALID;
    """
    assert _check(src) == []
