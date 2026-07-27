from pathlib import Path

from sarj_sql_lint.rules.add_constraint_not_valid import AddConstraintNotValid
from sarj_sql_lint.rules.require_fk_index import RequireFkIndex
from sarj_sql_lint.rules.require_lock_timeout import RequireLockTimeout


P = Path("migration.sql")


def test_require_lock_timeout() -> None:
    rule = RequireLockTimeout()

    # Passes when lock_timeout is set
    clean_sql = """
    SET lock_timeout = '2s';
    ALTER TABLE users ADD COLUMN bio TEXT;
    """
    assert rule.check(P, clean_sql) == []

    # Fails when DDL exists without lock/statement timeout
    violating_sql = """
    ALTER TABLE users ADD COLUMN bio TEXT;
    """
    diags = rule.check(P, violating_sql)
    assert len(diags) == 1
    assert diags[0].code == "SARJ110"


def test_add_constraint_not_valid() -> None:
    rule = AddConstraintNotValid()

    # Passes with NOT VALID
    clean_sql = "ALTER TABLE users ADD CONSTRAINT check_age CHECK (age >= 18) NOT VALID;"
    assert rule.check(P, clean_sql) == []

    # Fails without NOT VALID
    violating_sql = "ALTER TABLE users ADD CONSTRAINT check_age CHECK (age >= 18);"
    diags = rule.check(P, violating_sql)
    assert len(diags) == 1
    assert diags[0].code == "SARJ111"


def test_require_fk_index() -> None:
    rule = RequireFkIndex()

    # Passes when index exists on FK column
    clean_sql = """
    ALTER TABLE orders ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id);
    CREATE INDEX idx_orders_user_id ON orders(user_id);
    """
    assert rule.check(P, clean_sql) == []

    # Fails when FK has no index
    violating_sql = """
    ALTER TABLE orders ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id);
    """
    diags = rule.check(P, violating_sql)
    assert len(diags) == 1
    assert diags[0].code == "SARJ112"
