# Data contracts

Audit weak or duplicated data contracts using the shared [audit protocol](../README.md#audit-protocol). This command includes Pydantic, Zod, and explicit attribute-validation concerns.

## Automated baseline

Run applicable rules including `pydantic-at-boundaries`, `prefer-schema-for-api-payload`, `prefer-module-level-schema`, `prefer-zod-infer`, `prefer-zod-enum`, `no-zod-native-enum`, `prefer-discriminated-union`, `prefer-nominal-id-types`, and unsafe-`Any`/`any` checks.

## Judgment checks

- External input used before parsing at HTTP, message, database, file, environment, or third-party API boundaries.
- Structured values represented by untyped dictionaries, broad objects, positional tuples, or repeated primitive parameters.
- Manual TypeScript interfaces duplicated beside a Zod schema instead of inferred from it.
- Stringly typed finite sets and multiple optional fields that permit illegal state combinations.
- Attribute bags accessed through unchecked dynamic lookup when an explicit protocol or schema would clarify the contract.

Use the lightest suitable contract. Do not introduce runtime schemas for private, already-trusted local values, component props, ORM-generated types, or useful generic abstractions.
