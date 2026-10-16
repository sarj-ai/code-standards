# Data contracts

Audit weak or duplicated data contracts using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). This command includes Pydantic, Zod, and explicit attribute-validation concerns.

## Judgment checks

- External input used before parsing at HTTP, message, database, file, environment, or third-party API boundaries.
- Structured values represented by untyped dictionaries, broad objects, positional tuples, or repeated primitive parameters.
- Manual TypeScript interfaces duplicated beside a Zod schema instead of inferred from it.
- Stringly typed finite sets and multiple optional fields that permit illegal state combinations.
- Attribute bags accessed through unchecked dynamic lookup when an explicit protocol or schema would clarify the contract.

Use the lightest suitable contract. Do not introduce runtime schemas for private, already-trusted local values, component props, ORM-generated types, or useful generic abstractions.

## Model the legal domain states

Establish the invariant from producers, consumers, validation, or a documented
domain contract before recommending a stronger type. Show one currently
representable invalid value and the operation it can break. A count of optional
fields, a status-like name, or several booleans alone does not prove a defect.

- When alternatives are mutually exclusive, prefer a union of complete variants
  over one record containing every variant's optional fields. Give each variant
  a stable literal discriminant and require the payload its consumers need.
  Preserve correlation: `{ kind: "email"; address: Email } | { kind: "sms";
  phone: Phone }` carries more evidence than independent unions for `kind` and
  `destination`. Shared fields can stay shared; unrelated options stay optional.
  When fields must be present together, make the complete record optional, such
  as `ping?: { at: Time; id: PingId }`, instead of making its required constituents
  independently optional.
- For a proven closed vocabulary, use literal unions, enums, or schema-derived
  alternatives and check dispatch exhaustively. Keep genuinely open external
  vocabularies open, or model an explicit unknown variant with the original value
  when forward compatibility requires it. A wildcard/default branch is not
  evidence that future variants receive deliberate handling. Reuse upstream
  TypeScript exhaustiveness checks and a helper accepting `never`, or Python's
  `assert_never`, rather than requiring one dispatch syntax.
- Distinguish domain roles whose shared primitive representation permits harmful
  substitution: identifiers, units, money with currency, and validated values.
  Reuse established nominal types and constructors. A transparent alias does not
  distinguish roles; a brand, `NewType`, or type assertion does not validate
  external data. Introduce refinements only when the invariant and affected
  consumer justify them; do not brand every primitive.
- Encode cross-field constraints at the smallest owning constructor, parser, or
  transition: ordered ranges, compatible units, non-empty collections, and state
  prerequisites need more than independently valid fields. Keep unchecked
  construction private when it would bypass that invariant. For expected,
  recoverable construction failures, prefer a typed outcome with the failure
  information callers actually need.
- Preserve established invariants through updates. Separate mutation of a tag and
  its payload, unchecked copies, and mutable aliases can recreate impossible
  combinations after valid construction. Prefer replacing the complete variant
  or a domain transition when that prevents the demonstrated defect. Readonly or
  frozen fields do not validate data or make nested mutable values immutable.
  Operations available only in one state should accept that variant or
  capability and return the next valid variant, so callers cannot invoke them
  with an unrelated state.

Stronger modeling must preserve every legitimate state. Independent feature
flags, PATCH/update objects, form drafts, partially loaded data, aggregate or
partial-success results, and externally mandated wire formats can legitimately
contain multiple optional fields. Keep omission, explicit null, and a supplied
value distinct when they mean different things. Parse a permissive wire contract
into a stronger internal model at the trust boundary when the domain requires
it; do not silently drop valid states or change the public protocol.

TypeScript object types are structural: a union can still accept extra fields
from a non-fresh value. If a proven invariant forbids a field in another branch,
consider an explicit forbidden member such as `error?: never`, with the project's
optional-property semantics accounted for. Runtime input still needs parsing;
static types, literal tags, and casts do not enforce runtime object validity.
Do not impose exactness when extra metadata is valid.

## Preserve the evidence after validation

Check the implementation of user-defined type predicates, including both
branches at callers. TypeScript predicates and Python `TypeIs` can exclude their
target from the false branch, so a positive-integer or non-empty-value filter is
not a total test for `number`, `int`, or the whole container type. Use Python
`TypeGuard` for intentional partial predicates and retain the remaining cases
in false-branch callers. A predicate annotation does not validate its body.

Look for escape hatches that can invalidate an established contract: reflective
property writes, Pydantic `model_construct`, and `model_copy(update=...)` do not
provide the same checks as ordinary typed assignment or validated construction.
Report a demonstrated incompatible value or missing required field; trusted
compatible bypasses remain valid. Revalidating an existing Pydantic instance
may return it unchanged, so validate complete input data when validation is
required.

When replacing a hand-written contract with schema output, preserve readonly
views, nested optional-property semantics, callable capabilities, and deliberate
public abstractions. Mutual assignability alone does not prove that replacing
the type preserves those guarantees.

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
