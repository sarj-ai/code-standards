# `prefer-non-nullable-collection` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-non-nullable-collection.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Prefer non-null arrays in declared TypeScript data shapes.

An array type such as `OrganizationId[] | null` gives an empty collection two
representations: nullish and `[]`. Requiring an array removes null checks
from the call chain and makes the project-wide contract explicit.

The rule checks declared data shapes: interface/class properties, properties
in object type aliases, and direct array type aliases. An optional property
(`items?: T[]`) does not fire unless its written type also explicitly includes
`null` or `undefined`: omission is API input syntax, not a nullable collection
value. Mixed scalar-or-array unions do not fire because they model more than
an empty collection. Function-local annotations, tests, and generated
declarations are exempt.

This is an opinionated application convention, not a TypeScript type-system
fact. When null is a meaningful third state (for example React Router uses
`matches: Match[] | null` to distinguish "no match" from an empty match set),
retain the union with an inline ESLint disable and its reason.

Corpus sweep (2026-07-27): FastAPI, Pydantic, SQLModel, Zod, and React Router;
2,901 Python/TypeScript files total. The final TypeScript rule reported 13
explicit nullable-array declarations. Every match had the advertised AST
shape; optional-only properties, tests, generated files, and vendor code
produced no reports.
