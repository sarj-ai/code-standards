# Data contracts

Audit weak or duplicated data contracts using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). This command includes Pydantic, Zod, and explicit attribute-validation concerns.

## Judgment checks

- External input used before parsing at HTTP, message, database, file, environment, or third-party API boundaries.
- Structured values represented by untyped dictionaries, broad objects, positional tuples, or repeated primitive parameters.
- Manual TypeScript interfaces duplicated beside a Zod schema instead of inferred from it.
- Stringly typed finite sets and multiple optional fields that permit illegal state combinations.
- Attribute bags accessed through unchecked dynamic lookup when an explicit protocol or schema would clarify the contract.

Use the lightest suitable contract. Do not introduce runtime schemas for private, already-trusted local values, component props, ORM-generated types, or useful generic abstractions.

## Preserve known evidence

Check whether a populated fixed-key map is widened to an open dictionary, or a
known domain value is erased to `unknown`, `object`, or an untyped bag before
its fields are rediscovered. Preserve inference or use `satisfies` when exact
keys matter. Keep explicit domain contracts, dynamic-key registries, and empty
accumulators; show the lost information and affected consumer before reporting.
The `no-known-value-widening` rule owns typed identifier-to-broad local bindings;
report only additional flows here.

## Automated contract checks

`no-broad-return-type` owns implemented functions whose explicit broad return
annotation erases a known value. `prefer-typed-reflection` owns reflection over
proven property and callable contracts. Do not duplicate their diagnostics.
Keep unparsed input, opaque boundaries, and generic abstractions when reviewing
flows outside the deterministic rules.

## Validation and replacement values

Preserve caller-owned raw input during normalization, including when validation
fails. Return normalized mappings or collections and copy modified nested values
explicitly. The before-validator input-mutation rule owns deterministic findings;
review additional flows using concrete evidence of changed caller data.

Pydantic `model_copy(update=...)` applies updates without validation. Use it only
when replacements already satisfy the complete updated model contract. Validate
external or uncertain values through a constructor or domain factory before
creating the replacement; a trusted field type alone does not prove cross-field
invariants. Neither deep copying nor frozen fields adds validation.

Do not prescribe serialization-based reconstruction universally: excluded fields,
aliases, private state, and validators can make `model_dump()`/`model_validate()`
round trips lose information or change behavior. Use the smallest replacement
that preserves the model's contract, and keep intentional stateful boundaries
explicit.
