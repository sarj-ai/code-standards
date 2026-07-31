# SARJ082 `prefer-non-nullable-collection` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_non_nullable_collection.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Nullable list fields create two representations of an empty collection: ``None``
and ``[]``. When the project convention is that absence means empty, every
consumer inherits an unnecessary nullable type and null guard.

    # flagged
    class CallSettings(BaseModel):
        organization_ids: list[OrganizationId] | None = None

    # preferred when omission means "empty"
    class CallSettings(BaseModel):
        organization_ids: list[OrganizationId] = Field(default_factory=list)

The rule applies to annotated fields on every class data shape, including
Pydantic models, dataclasses, attrs classes, and ordinary typed classes. It does
not inspect function defaults: ``None`` is the safe Python idiom there because
``[]`` would be shared mutable state. Tests and generated sources are exempt.
``Optional[list[T]]`` and ``Union[list[T], None]`` are recognized alongside PEP
604 unions. A field is reported whether it defaults to ``None``, uses
``Field(default=None)``, or has no default at all.

This is an opinionated application convention, not a Python type-system fact.
When ``None`` is a meaningful third state (for example, "inherit this
constraint" rather than "allow no values"), keep the union and suppress the
line with ``# sarj-noqa: SARJ082 — None means ...``.

Corpus sweep (2026-07-27): FastAPI, Pydantic, SQLModel, Zod, and React Router;
2,901 Python/TypeScript files total. The final rule reported 30 explicit Python
nullable-list fields. Every match had the advertised AST shape; the sweep also
confirmed the meaningful-third-state suppression boundary on public framework
contracts such as Pydantic's ``UrlConstraints.allowed_schemes``.
