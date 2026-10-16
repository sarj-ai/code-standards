from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.__main__ import analyze
from sarj_sql_lint.rules.require_fk_index import RequireFkIndex, index_analysis_session


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
                '    FOREIGN KEY ("eventTypeId") REFERENCES "EventType"("id") ON DELETE CASCADE\n'
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
                '    FOREIGN KEY ("eventTypeId") REFERENCES "EventType"("id") ON DELETE CASCADE\n'
                ");\n"
            ),
            "20230410234751_add_other_indexes": ('CREATE INDEX "Booking_userId_idx" ON "Booking"("userId");\n'),
        },
    )
    target = root / "20220711182928_add_workflows" / "migration.sql"
    diags = _check(target.read_text(), target)
    assert len(diags) == 1
    assert '"eventTypeId"' in diags[0].message


def test_tree_scan_does_not_reach_outside_the_migrations_directory(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "20220711182928_add_workflows": (
                'CREATE TABLE "Child" (\n'
                '    "parentId" INTEGER NOT NULL,\n'
                '    FOREIGN KEY ("parentId") REFERENCES "Parent"("id") ON UPDATE SET NULL\n'
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
    src = "CREATE TABLE child (parent_id INT REFERENCES parent(id) ON DELETE CASCADE);"
    assert len(_check(src)) == 1


def test_reports_the_line_of_the_fk_it_names() -> None:
    src = """CREATE TABLE membership (
    account_id INT,
    FOREIGN KEY (account_id) REFERENCES tenant(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES billing_account(id) ON UPDATE SET DEFAULT
);
"""
    # Both clauses share the text `FOREIGN KEY (account_id) REFERENCES`, so a
    # find()-by-value attributed the second one to the first one's line.
    assert sorted(d.line for d in _check(src)) == [3, 4]


def test_reports_the_line_of_each_inline_reference() -> None:
    src = """CREATE TABLE order_item (
    id INT PRIMARY KEY,
    customer_id INT REFERENCES customer(id) ON DELETE CASCADE,
    product_id INT REFERENCES product(id) ON DELETE SET NULL
);
"""
    diags = _check(src)
    by_column = {d.message.split("`")[1]: d.line for d in diags}
    assert by_column == {"customer_id": 3, "product_id": 4}


def test_dump_foreign_keys_are_excluded() -> None:
    src = """-- PostgreSQL database dump
-- Dumped by pg_dump version 16.2
CREATE TABLE public.child (parent_id integer REFERENCES public.parent(id) ON DELETE CASCADE);
"""
    diags = RequireFkIndex().check(Path("schema.sql"), src)
    assert diags == []


def test_non_dump_findings_keep_the_plain_message() -> None:
    src = "CREATE TABLE child (parent_id INT REFERENCES parent(id) ON DELETE CASCADE);"
    diags = _check(src)
    assert len(diags) == 1
    assert "schema dump" not in diags[0].message


def test_multiline_using_btree_index_covers_the_fk() -> None:
    src = """
    CREATE TABLE orders (user_id UUID REFERENCES users(id) ON DELETE CASCADE);
    CREATE INDEX idx_orders
      ON orders USING btree (user_id);
    """
    assert _check(src) == []


def test_table_level_primary_key_covers_the_fk() -> None:
    src = """
    CREATE TABLE profiles (
        user_id UUID,
        PRIMARY KEY (user_id),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """
    assert _check(src) == []


def test_inline_primary_key_column_covers_a_table_level_fk() -> None:
    src = """
    CREATE TABLE profiles (
        user_id UUID PRIMARY KEY,
        FOREIGN KEY (user_id) REFERENCES users(id) ON UPDATE SET NULL
    );
    """
    assert _check(src) == []


def test_inline_unique_column_covers_a_table_level_fk() -> None:
    src = """
    CREATE TABLE profiles (
        user_id UUID UNIQUE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET DEFAULT
    );
    """
    assert _check(src) == []


def test_table_level_unique_covers_the_fk() -> None:
    source = """
    CREATE TABLE child (
        parent_id BIGINT,
        UNIQUE (parent_id),
        FOREIGN KEY (parent_id) REFERENCES parent(id) ON DELETE CASCADE
    );
    """
    assert _check(source) == []


def test_nonleading_index_does_not_cover_the_fk() -> None:
    source = """
    CREATE TABLE child (
        id BIGINT,
        parent_id BIGINT REFERENCES parent(id) ON DELETE CASCADE
    );
    CREATE INDEX child_idx ON child(id, parent_id);
    """
    assert len(_check(source)) == 1


def test_named_inline_constraint_reference_is_checked() -> None:
    src = """
    CREATE TABLE child (
        parent_id INT CONSTRAINT child_parent_fk REFERENCES parent(id) ON DELETE CASCADE
    );
    """
    diags = _check(src)
    assert len(diags) == 1
    assert (diags[0].line, diags[0].message.split("`")[1]) == (3, "parent_id")


def test_index_covers_a_named_inline_constraint_reference() -> None:
    src = """
    CREATE TABLE child (
        parent_id INT CONSTRAINT child_parent_fk REFERENCES parent(id) ON DELETE CASCADE
    );
    CREATE INDEX child_parent_id_idx ON child (parent_id);
    """
    assert _check(src) == []


def test_inline_unique_named_constraint_covers_its_reference() -> None:
    src = """
    CREATE TABLE child (
        parent_id INT CONSTRAINT parent_unique UNIQUE CONSTRAINT child_parent_fk REFERENCES parent(id) ON DELETE CASCADE
    );
    """
    assert _check(src) == []


def test_alter_table_only_composite_fk_is_covered_by_a_concurrent_index() -> None:
    src = """
    CREATE INDEX CONCURRENTLY idx_pdi ON public.pdi (team_id, person_id);

    ALTER TABLE ONLY public.pdi
        ADD CONSTRAINT pdi_person_id_fkey
        FOREIGN KEY (team_id, person_id) REFERENCES person_new(team_id, id) ON DELETE CASCADE NOT VALID;
    """
    assert _check(src) == []


def test_composite_fk_is_not_covered_by_only_its_first_column() -> None:
    source = """
    CREATE TABLE membership (
        team_id BIGINT,
        person_id BIGINT,
        FOREIGN KEY (team_id, person_id) REFERENCES person(team_id, id) ON DELETE CASCADE
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
        FOREIGN KEY (team_id, person_id) REFERENCES person(team_id, id) ON DELETE CASCADE
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
                "FOREIGN KEY (team_id, person_id) REFERENCES person(team_id, id) ON DELETE CASCADE);\n"
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
    CREATE TABLE child (parent_id BIGINT REFERENCES parent(id) ON DELETE CASCADE);
    """

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "parent_id" in diagnostics[0].message


def test_postgres_escape_string_cannot_create_a_foreign_key_or_index() -> None:
    source = """
    SELECT E'it\\'s CREATE INDEX fake ON child(parent_id)';
    CREATE TABLE child (parent_id BIGINT REFERENCES parent(id) ON DELETE CASCADE);
    """

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "parent_id" in diagnostics[0].message


def test_alter_add_column_if_not_exists_uses_the_real_fk_column_name() -> None:
    src = """
    ALTER TABLE provisioned_number
      ADD COLUMN IF NOT EXISTS sip_connection_id UUID REFERENCES sip_connection(id) ON DELETE CASCADE;
    CREATE INDEX CONCURRENTLY idx_number_connection
      ON provisioned_number (sip_connection_id) WHERE sip_connection_id IS NOT NULL;
    """

    assert _check(src) == []


@pytest.mark.parametrize("action", ["", " ON DELETE NO ACTION", " ON UPDATE RESTRICT"])
def test_non_cascading_foreign_keys_do_not_require_an_index(action: str) -> None:
    source = f"CREATE TABLE child (parent_id BIGINT REFERENCES parent(id){action});"

    assert _check(source) == []


@pytest.mark.parametrize(
    "action",
    ["ON DELETE CASCADE", "ON UPDATE CASCADE", "ON DELETE SET NULL", "ON UPDATE SET DEFAULT"],
)
def test_cascading_and_set_value_actions_require_an_index(action: str) -> None:
    source = f"CREATE TABLE child (parent_id BIGINT REFERENCES parent(id) {action});"

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("child", "indexed", "expected"),
    [
        ("app.child", "audit.child", 1),
        ("app.child", "app.child", 0),
        ('"Child"', "child", 1),
        ('"child"', "child", 0),
        ("app.child", "child", 0),
        ("child", "app.child", 0),
        ("current_db.app.child", "app.child", 0),
        ("app.child", "current_db.app.child", 0),
        ("pg_temp.child", "pg_temp_3.child", 0),
        ("pg_temp_3.child", "pg_temp.child", 0),
        ('"schema.with.dot".child', '"schema.other".child', 1),
        ("child\u00a0", "child\u00a0", 0),
        ("child\u00a0", "child", 1),
    ],
)
def test_index_coverage_preserves_relation_identity(child: str, indexed: str, expected: int) -> None:
    source = (
        f"CREATE TABLE {child}(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
        f"CREATE INDEX child_parent ON {indexed}(parent_id);\n"
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        ("FALSE", 1),
        ("((FALSE))", 1),
        ("TRUE", 0),
        ("parent_id IS NOT NULL", 0),
        ("active", 0),
        ("falſe", 0),
    ],
)
def test_only_provably_empty_partial_indexes_stop_proving_coverage(predicate: str, expected: int) -> None:
    source = (
        "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE, active bool, falſe bool);\n"
        f"CREATE INDEX child_parent ON child(parent_id) WHERE {predicate};"
    )
    assert len(_check(source)) == expected


def test_empty_index_does_not_override_another_covering_index() -> None:
    source = (
        "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
        "CREATE INDEX empty ON child(parent_id) WHERE FALSE;\n"
        "CREATE INDEX covering ON child(parent_id);\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    ("column", "indexed", "expected"),
    [
        ("Ä", "Ä", 0),
        ("Ä", "ä", 1),
        ('"ParentId"', '"ParentId"', 0),
        ('"ParentId"', "parentid", 1),
        ("parent\u00a0id", "parent\u00a0id", 0),
        ("parent\u00a0id", "parent_id", 1),
    ],
)
def test_index_key_identity_preserves_unicode_and_quoted_case(column: str, indexed: str, expected: int) -> None:
    source = (
        f"CREATE TABLE child({column} int REFERENCES parent(id) ON DELETE CASCADE);\n"
        f"CREATE INDEX child_parent ON child({indexed});\n"
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize(("indexed", "expected"), [("audit.child", 1), ("app.child", 0)])
def test_sibling_index_coverage_preserves_explicit_schema(tmp_path: Path, indexed: str, expected: int) -> None:
    root = _tree(
        tmp_path,
        {
            "001_child": "CREATE TABLE app.child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n",
            "002_index": f"CREATE INDEX child_parent ON {indexed}(parent_id);\n",
        },
    )
    target = root / "001_child" / "migration.sql"
    assert len(_check(target.read_text(), target)) == expected


@pytest.mark.parametrize(
    ("index_statement", "expected"),
    [
        ("DO $$ BEGIN CREATE INDEX child_parent ON child(parent_id); END $$;", 0),
        ("SELECT $$CREATE INDEX child_parent ON child(parent_id);$$;", 1),
        ("DO $$ BEGIN RAISE NOTICE 'CREATE INDEX child_parent ON child(parent_id);'; END $$;", 1),
    ],
)
def test_shared_index_parser_preserves_executable_body_coverage(index_statement: str, expected: int) -> None:
    source = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n" + index_statement
    assert len(_check(source)) == expected


@pytest.mark.parametrize("name", ["café_idx", "name_🐈ON"])
def test_shared_index_parser_preserves_unicode_index_names(name: str) -> None:
    source = (
        "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
        f"CREATE INDEX {name} ON child(parent_id);"
    )
    assert _check(source) == []


@pytest.mark.parametrize("change", ["create", "edit", "delete", "rename-outside", "rename-inside"])
def test_repeated_checks_observe_sibling_index_changes(tmp_path: Path, change: str) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    covering = "CREATE INDEX child_parent ON child(parent_id);\n"
    unrelated = "CREATE INDEX child_other ON child(other_id);\n"
    root = _tree(tmp_path, {"001_child": foreign_key, "002_index": unrelated if change == "create" else covering})
    target = root / "001_child" / "migration.sql"
    index = root / "002_index" / "migration.sql"
    assert len(_check(foreign_key, target)) == int(change == "create")
    if change in {"create", "edit"}:
        index.write_text(covering if change == "create" else unrelated, encoding="utf-8")
    elif change == "delete":
        index.unlink()
    else:
        destination = root / "003_renamed" / "migration.sql" if change == "rename-inside" else tmp_path / "index.sql"
        destination.parent.mkdir(parents=True, exist_ok=True)
        index.rename(destination)
    assert len(_check(foreign_key, target)) == int(change not in {"create", "rename-inside"})


def test_sibling_coverage_does_not_replace_current_source_with_stale_disk_content(tmp_path: Path) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    root = _tree(tmp_path, {"001_child": foreign_key + "CREATE INDEX child_parent ON child(parent_id);\n"})
    target = root / "001_child" / "migration.sql"
    assert len(_check(foreign_key, target)) == 1


def test_current_source_override_excludes_hardlinked_disk_proof(tmp_path: Path) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    root = _tree(tmp_path, {"001_child": foreign_key + "CREATE INDEX child_parent ON child(parent_id);\n"})
    target = root / "001_child" / "migration.sql"
    alias = root / "001_child" / "alias.sql"
    alias.hardlink_to(target)
    assert target.samefile(alias)
    assert len(_check(foreign_key, alias)) == 1


def test_current_source_override_excludes_case_alias_disk_proof(tmp_path: Path) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    root = _tree(tmp_path, {"001_child": foreign_key + "CREATE INDEX child_parent ON child(parent_id);\n"})
    target = root / "001_child" / "migration.sql"
    alias = target.with_name("MIGRATION.SQL")
    if not alias.exists() or not target.samefile(alias):
        pytest.skip("requires a case-insensitive filesystem")
    assert len(_check(foreign_key, target)) == 1
    assert len(_check(foreign_key, alias)) == 1


def test_current_source_keeps_distinct_case_named_sibling_proof(tmp_path: Path) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    root = _tree(tmp_path, {"001_child": foreign_key + "CREATE INDEX child_parent ON child(parent_id);\n"})
    target = root / "001_child" / "migration.sql"
    other = target.with_name("MIGRATION.sql")
    if other.exists() and target.samefile(other):
        pytest.skip("requires a case-sensitive filesystem")
    other.write_text(foreign_key, encoding="utf-8")
    assert not target.samefile(other)
    assert _check(foreign_key, other) == []
    with index_analysis_session():
        assert _check(foreign_key, other) == []
        replacement = other.with_suffix(".tmp")
        replacement.write_text(foreign_key, encoding="utf-8")
        replacement.replace(other)
        assert _check(foreign_key, other) == []


def test_cached_sibling_index_content_does_not_leak_between_migration_roots(tmp_path: Path) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    covered = _tree(
        tmp_path / "covered", {"001_child": foreign_key, "002_index": "CREATE INDEX i ON child(parent_id);\n"}
    )
    uncovered = _tree(tmp_path / "uncovered", {"001_child": foreign_key})
    assert _check(foreign_key, covered / "001_child" / "migration.sql") == []
    assert len(_check(foreign_key, uncovered / "001_child" / "migration.sql")) == 1


@pytest.mark.parametrize("change", ["create", "edit", "delete"])
def test_repeated_analysis_invocations_refresh_sibling_index_snapshots(tmp_path: Path, change: str) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    covering = "CREATE INDEX child_parent ON child(parent_id);\n"
    unrelated = "CREATE INDEX child_other ON child(other_id);\n"
    root = _tree(tmp_path, {"001_child": foreign_key, "002_index": unrelated if change == "create" else covering})
    target = root / "001_child" / "migration.sql"
    index = root / "002_index" / "migration.sql"
    assert len(analyze(["require-fk-index"], [target])) == int(change == "create")
    if change == "delete":
        index.unlink()
    else:
        index.write_text(covering if change == "create" else unrelated, encoding="utf-8")
    assert len(analyze(["require-fk-index"], [target])) == int(change != "create")


def test_analysis_snapshot_preserves_current_source_override(tmp_path: Path) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    root = _tree(tmp_path, {"001_child": foreign_key + "CREATE INDEX child_parent ON child(parent_id);\n"})
    target = root / "001_child" / "migration.sql"
    with index_analysis_session():
        assert len(_check(foreign_key, target)) == 1
        assert _check(target.read_text(), target) == []


@pytest.mark.parametrize(("case_alias", "file_symlink"), [(False, False), (True, False), (True, True)])
def test_current_source_overrides_atomically_replaced_snapshot_entry(
    tmp_path: Path, *, case_alias: bool, file_symlink: bool
) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    root = _tree(tmp_path, {"001_child": foreign_key + "CREATE INDEX child_parent ON child(parent_id);\n"})
    target = root / "001_child" / "migration.sql"
    active = target.with_name("MIGRATION.SQL") if case_alias else target
    if not active.exists() or not target.samefile(active):
        pytest.skip("requires a case-insensitive filesystem")
    if file_symlink:
        target.with_name("linked.sql").symlink_to(target)
    with index_analysis_session():
        assert len(_check(foreign_key, target)) == 1
        replacement = target.with_suffix(".tmp")
        replacement.write_text(foreign_key, encoding="utf-8")
        replacement.replace(target)
        assert len(_check(foreign_key, active)) == 1


def test_atomic_replacement_keeps_a_now_distinct_hardlink_as_sibling_proof(tmp_path: Path) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    root = _tree(tmp_path, {"001_child": foreign_key + "CREATE INDEX child_parent ON child(parent_id);\n"})
    target = root / "001_child" / "migration.sql"
    alias = target.with_name("alias.sql")
    alias.hardlink_to(target)
    with index_analysis_session():
        assert len(_check(foreign_key, alias)) == 1
        replacement = target.with_suffix(".tmp")
        replacement.write_text(foreign_key, encoding="utf-8")
        replacement.replace(alias)
        assert not target.samefile(alias)
        assert _check(foreign_key, alias) == []


@pytest.mark.parametrize("alias_kind", ["directory", "file"])
def test_current_source_overrides_replaced_snapshot_through_stable_symlink(tmp_path: Path, alias_kind: str) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    root = _tree(tmp_path, {"001_child": foreign_key + "CREATE INDEX child_parent ON child(parent_id);\n"})
    target = root / "001_child" / "migration.sql"
    if alias_kind == "directory":
        directory = root / "linked"
        directory.symlink_to(target.parent, target_is_directory=True)
        active = directory / target.name
    else:
        active = target.with_name("linked.sql")
        active.symlink_to(target)
    with index_analysis_session():
        assert len(_check(foreign_key, target)) == 1
        replacement = target.with_suffix(".tmp")
        replacement.write_text(foreign_key, encoding="utf-8")
        replacement.replace(target)
        assert active.samefile(target)
        assert len(_check(foreign_key, active)) == 1


def test_replaced_source_excludes_every_live_case_spelling_of_symlink_target(tmp_path: Path) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    root = _tree(tmp_path, {"001_child": foreign_key + "CREATE INDEX child_parent ON child(parent_id);\n"})
    target = root / "001_child" / "migration.sql"
    if not target.with_name("MIGRATION.SQL").exists():
        pytest.skip("requires a case-insensitive filesystem")
    for index, spelling in enumerate(("MIGRATION.SQL", "Migration.Sql")):
        target.with_name(f"alias_{index}.sql").symlink_to(target.with_name(spelling))
    with index_analysis_session():
        assert len(_check(foreign_key, target)) == 1
        replacement = target.with_suffix(".tmp")
        replacement.write_text(foreign_key, encoding="utf-8")
        replacement.replace(target)
        assert len(_check(foreign_key, target)) == 1
        assert len(_check(foreign_key, target.with_name("mIgRaTiOn.sQl"))) == 1


def test_nested_analysis_snapshot_abort_restores_outer_snapshot_and_direct_freshness(tmp_path: Path) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    root = _tree(tmp_path, {"001_child": foreign_key, "002_index": "CREATE INDEX i ON child(parent_id);\n"})
    target = root / "001_child" / "migration.sql"

    def abort_nested_analysis() -> None:
        with index_analysis_session():
            assert len(_check(foreign_key, target)) == 1
            message = "abort nested analysis"
            raise RuntimeError(message)

    with index_analysis_session():
        assert _check(foreign_key, target) == []
        (root / "002_index" / "migration.sql").unlink()
        with pytest.raises(RuntimeError, match="abort nested analysis"):
            abort_nested_analysis()
        assert _check(foreign_key, target) == []
    assert len(_check(foreign_key, target)) == 1


def test_failed_analysis_cannot_leave_a_snapshot_in_direct_rule_calls(tmp_path: Path) -> None:
    foreign_key = "CREATE TABLE child(parent_id int REFERENCES parent(id) ON DELETE CASCADE);\n"
    root = _tree(tmp_path, {"001_child": foreign_key, "002_index": "CREATE INDEX i ON child(parent_id);\n"})
    target = root / "001_child" / "migration.sql"
    with pytest.raises(SystemExit):
        analyze(["missing-rule"], [target])
    assert _check(foreign_key, target) == []
    (root / "002_index" / "migration.sql").unlink()
    assert len(_check(foreign_key, target)) == 1
