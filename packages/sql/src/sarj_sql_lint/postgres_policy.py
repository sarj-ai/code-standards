from sarj_sql_lint._aggregate_identity import aggregate_name as aggregate_name
from sarj_sql_lint._policy_source import normalize_group_comments as normalize_group_comments


def normalize_postgres_ctas(source: str) -> str:
    from sarj_sql_lint._postgres_ctas import normalize_postgres_ctas as normalize  # ruff: ignore[import-outside-top-level] -- defer SQLGlot until a candidate query requires normalization.

    return normalize(source)


def normalize_postgres_explain(source: str) -> str:
    from sarj_sql_lint._explain import normalize_postgres_explain as normalize  # ruff: ignore[import-outside-top-level] -- defer SQLGlot until a candidate EXPLAIN requires normalization.

    return normalize(source)
