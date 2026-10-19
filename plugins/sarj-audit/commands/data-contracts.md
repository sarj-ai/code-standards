# Data contracts

Audit weak or duplicated data contracts using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). This command includes Pydantic, Zod, and explicit attribute-validation concerns.

## Judgment checks

- External input used before declarative Pydantic parsing at Python HTTP, message, database, file, environment, or third-party API boundaries.
- Structured values represented by untyped dictionaries, broad objects, positional tuples, or repeated primitive parameters.
- Dictionary `get`/subscription checks used to discover a Python record's type, shape, or variant instead of parsing its declared schema.
- Manual TypeScript interfaces duplicated beside a Zod schema instead of inferred from it.
- Stringly typed finite sets and multiple optional fields that permit illegal state combinations.
- Attribute bags accessed through unchecked dynamic lookup when an explicit protocol or schema would clarify the contract.

Prefer named Pydantic models for Python runtime input and keep the parsed domain
type through its consumers. Already trusted local values, component props,
ORM-generated types, and useful generic abstractions can retain their existing
precise contracts without redundant parsing.

## Parse Python records declaratively

Treat hand-written record discovery as a missing parser. Domain code must not
use `payload.get("type") == "message"`, `isinstance(payload.get("items"), list)`,
or `match payload.get("items")` with a typed sequence pattern to establish an
open mapping's record type or shape. Equivalent subscription, membership, and
key-presence probes have the same problem. A matching tag, a present key, or a list
container does not establish the other required fields or their item types.
Parse the complete input into a named Pydantic model once, then dispatch through
the parsed variant and read typed attributes. Moving the same probes into an
`is_payload` helper, `TypeGuard`, cast, or `TypedDict` annotation does not add
runtime validation.

For known records, keep raw `object` values confined to the parser entry point. Do not use
`dict[str, object]`, `dict[str, Any]`, `Mapping[str, object]`, or an equivalent
open record as the application contract for a known set of fields. In
TypeScript, apply the same distinction to `Record<string, unknown>` and parse
external records with the owned Zod schema. Renaming an open dictionary with a
type alias or substituting `JsonValue` does not establish a fixed record schema.
Use a precise named contract for trusted internal records; use Pydantic when
runtime input needs validation.

Make parsing declarative wherever the schema can express it. Put requiredness,
defaults, nullability, aliases, nested records, collection item types, and
constraints in model fields, `Annotated`, and `Field`. Use model variants with
`Literal` tags and `Field(discriminator="type")` for alternative record shapes.
Declare exact tuple shapes for positional wire fields and strict integer fields
when the existing parser rejects booleans; preserve both item types and bounds.
For a union, list, or other collection at the root, define a named `RootModel`;
do not assemble a parser from repeated `.get` checks and `isinstance` ladders.
Use collection validation when one schema can own the per-item parsing policy.
Prefer `model_validate_json`
for raw JSON and `model_validate` for an already decoded value. The strict
preset directs application code to named models rather than `TypeAdapter`.

Custom validators are for constraints or normalization that the declarative
schema cannot express. Preserve the accepted input, coercion and strictness
policies, omitted versus null fields, extra-field handling, aliases, and error
behavior when replacing manual parsing. Collection models must state whether a
bad item rejects the batch or is intentionally omitted, and retain required
rejection reports and logging.

Keep exceptions tied to a concrete owning contract. Dynamic-key registries,
opaque extension maps, parser infrastructure, Pydantic before validators, and
callable `Discriminator` extractors can legitimately inspect dictionaries.
Prefer a field discriminator when the wire format supplies one; a callable
extractor must support the mapping and model forms used during validation and
serialization. These adapters must feed the declared schema instead of exposing
an unchecked record to domain consumers. Ordinary lookup on a precisely typed
dynamic map is valid. Explain an exceptional fixed-record boundary locally and
use an exact suppression when a deterministic rule applies; a broad annotation
or a helper's name is insufficient evidence for the exception.

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

For Pydantic migrations, discriminator extraction precedes variant defaults and
validators. Preserve omitted tags, accepted aliases, and tag normalization in an
owned input adapter when existing callers depend on them. A non-null payload can
retain an input default; non-nullability does not imply required input presence.
Preserve identity-sensitive boolean tags explicitly: `Literal[True]` can accept
`1` even with `ConfigDict(strict=True)` because [literal matching has a Python
equality fallback](https://github.com/pydantic/pydantic-core/blob/main/src/validators/literal.rs#L160).
When the current parser requires `is True`, verify that boundary and retain an
owned input adapter around the union if needed. Pydantic [rejects before, wrap
and plain validators on the discriminator field](https://pydantic.dev/docs/validation/latest/errors/usage_errors/#invalid-discriminator-validator);
validate the raw envelope before tagged dispatch instead.
Compare the parser behavior callers observe: Python versus JSON validation,
context, extra fields, `model_fields_set`, `exclude_unset`, and error locations.
Matching complete `model_dump()` output alone does not establish compatibility.
A union alias also does not preserve a public model class's construction,
subclassing, equality, or instance-revalidation behavior. Callable discriminators
must support the mappings and model instances used during validation and
serialization. A requirement shared by every tag belongs on the common field;
it does not establish a need for separate variants.

Choose where alternatives belong in a collection. `list[A | B]` admits mixed
batches; `list[A] | list[B]` describes homogeneous batches. Preserve the domain's
actual batch contract. Copy required parsing policies such as `from_attributes`
into replacement variants when callers supply attribute objects. Validation
bypasses such as `SkipValidation` do not establish a payload's annotated runtime
type; keep their separately owned trust contract visible during a union rewrite.

TypeScript object types are structural: a union can still accept extra fields
from a non-fresh value. If a proven invariant forbids a field in another branch,
consider an explicit forbidden member such as `error?: never`, with the project's
optional-property semantics accounted for. Runtime input still needs parsing;
static types, literal tags, and casts do not enforce runtime object validity.
Do not impose exactness when extra metadata is valid.

Choose identifier types from the entity or established domain role, not the
parameter's position. A transfer can take the same `AccountId` type for its
source and destination while rejecting a `WorkspaceId` in either position.
Reuse the authoritative type from its owning package; independently declaring
another `UserId` does not make it interchangeable with an existing one. Preserve
an inherited or external API's primitive representation and adapt it at an owned
domain boundary. Narrowing an override's parameter to a nominal subtype can
break callers that the base contract still accepts.

Review collection normalization as an API and ownership decision. Removing
`None` from a callable can break explicit-null callers even when its body uses
`items or []`. Replacing that expression with `list(items)` also changes a
non-empty caller-owned list from an alias to a copy. Establish whether callers
depend on mutation, identity, omission, or explicit null before choosing a
required list, an immutable empty default, or a compatible public wrapper.

For dictionary-shaped records, distinguish a closed field contract from an
extension map and from an API that requires concrete dictionary operations.
Use `TypedDict` for already trusted known fields, or a named mapping alias when
extension keys and operations such as `pop`, `update`, or `clear` are part of
the contract. Parse untrusted fixed records with Pydantic before choosing an
internal representation. A `TypedDict` alone does not prove runtime field
validity or key exactness.
A dataclass or validation model changes the runtime value; it
does not preserve dictionary behavior merely by naming the same fields. Keep
framework serialization hooks and public overrides faithful to their required
output, including wire keys and normalization.

For positional results, establish whether named fields improve an owned domain
record or whether a mathematical, tuple, or serialization protocol owns the
representation. A typed `NamedTuple` can retain tuple operations, but it changes
exact runtime type identity; a dataclass changes more of the protocol. Check
construction defaults, positional consumers, and pickling compatibility before
migrating an established record. Verify the factory's actual authority before
treating a source-visible factory name as proof of an untyped value.

Make generic outputs follow evidence supplied to the implementation. A caller
choosing `T` does not prove that a decoded value is `T`; pass a decoder or
constructor that establishes the result instead of asserting a caller-selected
return type. Review overloads against their promised input/result pairs. When
you own callback contracts, function-valued properties can preserve stricter
parameter variance than methods; keep externally required method APIs intact.

Model collection guarantees that consumers actually require. An open indexed
map can lack a requested key, and an arbitrary array can be empty. Account for
the project's indexed-access checks, use a lookup result that represents
absence, or construct a finite-key or non-empty domain value with evidence.
Do not assert totality or cardinality merely to remove a caller's check.
Likewise, optional forbidden fields depend on exact optional-property policy:
absence and a present `undefined` value need not mean the same thing.

Keep representation, units, and validation separate. A role type such as
`NewType('NonEmptyText', str)` does not reject empty input. Establish that
invariant at an owned constructor or parser. Distinct currencies or dimensions
need compatible operations and explicit conversions as well as distinct input
types. For time, distinguish an instant from a local wall time that still needs
a timezone or ambiguity choice. Validate awareness where required; a plain
`datetime` annotation does not encode it, and local wall times remain legitimate
domain values.

## Preserve the evidence after validation

Check the implementation of user-defined type predicates, including both
branches at callers. TypeScript predicates and Python `TypeIs` can exclude their
target from the false branch, so a positive-integer or non-empty-value filter is
not a total test for `number`, `int`, or the whole container type. Use Python
`TypeGuard` for intentional partial predicates and retain the remaining cases
in false-branch callers. A predicate annotation does not validate its body.

Trace why a guard is needed before adding or removing one. Keep guards where
uncertainty belongs: external input, heterogeneous collections, plugin APIs,
framework callbacks, and public contracts can require runtime narrowing. An
imported predicate or a generic protocol can also express evidence the local
implementation does not own. Do not replace these with assertions or casts.
For runtime-checkable protocols, distinguish checking that an attribute exists
from validating its value or callable signature. Preserve intentional feature
probes; show the incompatible value and the failing consumer before asking a
boundary to establish more evidence. Preserve a validator's documented failure
behavior when changing it into a boolean predicate or construction outcome.

Within owned business logic, repeated guards can expose an earlier loss of
domain information. Show the producer that widened a validated value and the
consumer forced to rediscover it. Prefer a parser returning the domain union
once, a constructor returning a validated value or explicit failure, and an
operation accepting the variant it needs. For example, pass `ReadyJob` to
`startJob` after dispatching on `Job`'s discriminant, rather than passing
`unknown` through several helpers that each assert `isReadyJob`. Keep draft,
unknown, and failure variants when they are legal states; do not make every
consumer repeat validation or force a successful construction.

When a predicate exists to select a refinement such as non-empty text, check
whether its callers need a validated refinement type, a filtered collection,
or a construction outcome. Choose the contract that carries that evidence to
the operation that needs it. Changing a predicate's annotation alone does not
construct a refined value, preserve an external callback contract, or establish
that mutable data will keep satisfying the check.

A model's construction validation does not establish that later assignments
rerun field or cross-field validators. Check its assignment policy before
relying on a persistent invariant. Assignment validation can enforce supported
field constraints, but a failing after-model validator need not roll back the
assignment. When every published state must preserve a cross-field invariant,
use a validated replacement or an atomic transition owner. Preserve intentional
intermediate mutable states and custom assignment contracts.

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

For Python parsing, `require-pydantic-for-external-json` owns proven external
JSON field access, `require-pydantic-for-structured-payload` owns nested route
payload access, and `require-pydantic-for-mapping-shape` owns type and shape
probes on open mapping contracts. `no-any-mapping-types` owns value-erasing
`Any` mappings; `named-record-at-boundaries` owns unnamed fixed-record returns.
`prefer-declarative-batch-validation` and `prefer-discriminated-model-union`
cover their proven collection and variant patterns. Review additional parsing
flows here with concrete producer and consumer evidence.

## Validation and replacement values

Check the final value a validator establishes. Pydantic after and plain field
validators can store a value outside the field annotation; a native-clean
callable signature alone does not prove that coupling. Before output is parsed
by the field schema, while wrap validators can intentionally return a valid
value without calling their handler. Account for later validators and ordered
`Annotated` metadata that repair intermediate values before reporting a final
contract violation. Serializer output has its own wire contract and can differ
legitimately from the stored field type.

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
