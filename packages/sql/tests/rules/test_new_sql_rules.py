from pathlib import Path

from sarj_sql_lint.rules.add_constraint_not_valid import AddConstraintNotValid
from sarj_sql_lint.rules.require_fk_index import RequireFkIndex
from sarj_sql_lint.rules.require_lock_timeout import RequireLockTimeout


P = Path("migration.sql")


def test_require_lock_timeout() -> None:
    rule = RequireLockTimeout()

    # Passes with SET LOCAL lock_timeout before DDL
    clean_sql = """
    SET LOCAL lock_timeout = '2s';
    CREATE UNIQUE INDEX idx_unique ON users(email);
    """
    assert rule.check(P, clean_sql) == []

    # Fails when CREATE UNIQUE INDEX lacks timeout
    violating_sql = """
    CREATE UNIQUE INDEX idx_unique ON users(email);
    """
    diags = rule.check(P, violating_sql)
    assert len(diags) == 1
    assert diags[0].code == "SARJ110"


def test_add_constraint_not_valid() -> None:
    rule = AddConstraintNotValid()

    # Passes with NOT VALID on CHECK / FK
    clean_sql = """
    ALTER TABLE users
      ADD CONSTRAINT check_age CHECK (age >= 18) NOT VALID;
    """
    assert rule.check(P, clean_sql) == []

    # Ignores UNIQUE constraints (Postgres does not support NOT VALID on UNIQUE)
    unique_sql = "ALTER TABLE users ADD CONSTRAINT uq_email UNIQUE (email);"
    assert rule.check(P, unique_sql) == []

    # Validates multiple clauses independently when commas exist inside parameters
    multi_clause_sql = """
    ALTER TABLE users
      ADD CONSTRAINT c1 CHECK (fn(a, b)) NOT VALID,
      ADD CONSTRAINT c2 CHECK (score > 0);
    """
    diags = rule.check(P, multi_clause_sql)
    assert len(diags) == 1
    assert diags[0].code == "SARJ111"


def test_require_fk_index() -> None:
    rule = RequireFkIndex()

    # Passes with quoted identifiers
    quoted_sql = """
    CREATE TABLE "orders" ("user_id" UUID REFERENCES "users"("id"));
    CREATE INDEX idx_orders_user_id ON "orders"("user_id");
    """
    assert rule.check(P, quoted_sql) == []

    # Passes when FK column is PRIMARY KEY
    pk_fk_sql = """
    CREATE TABLE profiles (
        user_id UUID PRIMARY KEY REFERENCES users(id)
    );
    """
    assert rule.check(P, pk_fk_sql) == []

    # Fails when composite FK leading column is unindexed
    composite_unindexed = """
    CREATE TABLE tenant_users (
        tenant_id UUID,
        user_id UUID,
        FOREIGN KEY (tenant_id, user_id) REFERENCES users(id)
    );
    """
    diags = rule.check(P, composite_unindexed)
    assert len(diags) == 1
    assert diags[0].code == "SARJ112"
