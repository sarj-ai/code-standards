from pathlib import Path

from sarj_sql_lint.rules.add_constraint_not_valid import AddConstraintNotValid
from sarj_sql_lint.rules.require_fk_index import RequireFkIndex
from sarj_sql_lint.rules.require_lock_timeout import RequireLockTimeout


P = Path("migration.sql")


def test_require_lock_timeout() -> None:
    rule = RequireLockTimeout()

    # Passes when lock_timeout is set prior to DDL in transaction block
    clean_sql = """
    SET LOCAL lock_timeout = '2s';
    CREATE UNIQUE INDEX idx_unique ON users(email);
    """
    assert rule.check(P, clean_sql) == []

    # Fails when COMMIT expires lock_timeout before second DDL
    expired_tx_sql = """
    BEGIN;
    SET LOCAL lock_timeout = '2s';
    ALTER TABLE a ADD COLUMN x INT;
    COMMIT;
    ALTER TABLE b ADD COLUMN y INT;
    """
    diags = rule.check(P, expired_tx_sql)
    assert len(diags) == 1
    assert diags[0].code == "SARJ110"


def test_add_constraint_not_valid() -> None:
    rule = AddConstraintNotValid()

    # Ignores UNIQUE constraints even if a column is named "check"
    unique_col_check_sql = "ALTER TABLE t ADD CONSTRAINT uq UNIQUE (check);"
    assert rule.check(P, unique_col_check_sql) == []

    # Fails on CHECK constraint without NOT VALID
    violating_sql = "ALTER TABLE users ADD CONSTRAINT check_age CHECK (age >= 18);"
    diags = rule.check(P, violating_sql)
    assert len(diags) == 1
    assert diags[0].code == "SARJ111"


def test_require_fk_index() -> None:
    rule = RequireFkIndex()

    # Passes with multiline INDEX ON with USING btree
    multiline_using_sql = """
    CREATE TABLE orders (user_id UUID REFERENCES users(id));
    CREATE INDEX idx_orders
      ON orders USING btree (user_id);
    """
    assert rule.check(P, multiline_using_sql) == []

    # Passes when table-level PRIMARY KEY constraint exists
    table_pk_sql = """
    CREATE TABLE profiles (
        user_id UUID,
        PRIMARY KEY (user_id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """
    assert rule.check(P, table_pk_sql) == []
