import { ZOD_STRING_FORMAT_NAMES } from "./zod-string-format-names.mjs";
import { ZOD_STRING_FORMAT_METHODS } from "./zod-string-format-methods.mjs";
import { AST_NODE_TYPES } from "../ast-node-types/index.cjs";
//#region src/zod-check-vocabulary.ts
const STRING = ["string"];
const STRING_OR_ARRAY = ["string", "array"];
const NUMERIC = ["number", "bigint"];
const COMPARABLE = [
	"number",
	"bigint",
	"date"
];
const SIZED = ["set", "map"];
/**
* The `iso.*` member formats (`z.iso.date()`, …). Their factory resolves to the
* `iso` namespace, so they are named with a dotted canonical name and are
* deliberately absent from {@link ZOD_STRING_FORMAT_NAMES}.
*/
const ISO_FORMAT_NAMES = ZOD_STRING_FORMAT_METHODS.map(({ replacementMethodName }) => replacementMethodName).filter((name) => name.startsWith("iso."));
/**
* Every known check by canonical name — the standalone `$ZodCheck` vocabulary
* (`minLength`, `gte`, …) plus the string formats, which behave like checks
* whether they are written as a factory (`z.uuid()`) or chained on a string.
*/
const CHECK_DESCRIPTORS = new Map([
	["minLength", {
		appliesTo: STRING_OR_ARRAY,
		bound: {
			kind: "lower",
			domain: "length",
			inclusive: true
		}
	}],
	["maxLength", {
		appliesTo: STRING_OR_ARRAY,
		bound: {
			kind: "upper",
			domain: "length",
			inclusive: true
		}
	}],
	["length", {
		appliesTo: STRING_OR_ARRAY,
		bound: {
			kind: "exact",
			domain: "length"
		}
	}],
	["nonempty", {
		appliesTo: STRING_OR_ARRAY,
		bound: {
			kind: "lower",
			domain: "length",
			inclusive: true,
			fixedValue: 1
		}
	}],
	["minSize", {
		appliesTo: SIZED,
		bound: {
			kind: "lower",
			domain: "size",
			inclusive: true
		}
	}],
	["maxSize", {
		appliesTo: SIZED,
		bound: {
			kind: "upper",
			domain: "size",
			inclusive: true
		}
	}],
	["size", {
		appliesTo: SIZED,
		bound: {
			kind: "exact",
			domain: "size"
		}
	}],
	["gt", {
		appliesTo: COMPARABLE,
		bound: {
			kind: "lower",
			domain: "value",
			inclusive: false
		}
	}],
	["gte", {
		appliesTo: COMPARABLE,
		bound: {
			kind: "lower",
			domain: "value",
			inclusive: true
		}
	}],
	["lt", {
		appliesTo: COMPARABLE,
		bound: {
			kind: "upper",
			domain: "value",
			inclusive: false
		}
	}],
	["lte", {
		appliesTo: COMPARABLE,
		bound: {
			kind: "upper",
			domain: "value",
			inclusive: true
		}
	}],
	["positive", {
		appliesTo: NUMERIC,
		bound: {
			kind: "lower",
			domain: "value",
			inclusive: false,
			fixedValue: 0
		}
	}],
	["negative", {
		appliesTo: NUMERIC,
		bound: {
			kind: "upper",
			domain: "value",
			inclusive: false,
			fixedValue: 0
		}
	}],
	["nonnegative", {
		appliesTo: NUMERIC,
		bound: {
			kind: "lower",
			domain: "value",
			inclusive: true,
			fixedValue: 0
		}
	}],
	["nonpositive", {
		appliesTo: NUMERIC,
		bound: {
			kind: "upper",
			domain: "value",
			inclusive: true,
			fixedValue: 0
		}
	}],
	["multipleOf", {
		appliesTo: NUMERIC,
		multipleOf: true
	}],
	["int", {
		appliesTo: ["number"],
		intMarker: true
	}],
	["includes", {
		appliesTo: STRING,
		content: "includes"
	}],
	["startsWith", {
		appliesTo: STRING,
		content: "startsWith"
	}],
	["endsWith", {
		appliesTo: STRING,
		content: "endsWith"
	}],
	["lowercase", {
		appliesTo: STRING,
		casing: "lowercase"
	}],
	["uppercase", {
		appliesTo: STRING,
		casing: "uppercase"
	}],
	["regex", { appliesTo: STRING }],
	...[...ZOD_STRING_FORMAT_NAMES, ...ISO_FORMAT_NAMES].map((name) => [name, {
		appliesTo: STRING,
		format: true
	}])
]);
/**
* Chained (`zod`) spellings whose canonical name does not depend on the base
* type. `step` is the deprecated spelling of `multipleOf`; the rest are spelled
* the same either way.
*/
const CHAINED_COMMON = [...[
	"gt",
	"gte",
	"lt",
	"lte",
	"positive",
	"negative",
	"nonnegative",
	"nonpositive",
	"multipleOf",
	"int",
	"includes",
	"startsWith",
	"endsWith",
	"lowercase",
	"uppercase",
	"regex",
	"nonempty"
].map((name) => [name, name]), ["step", "multipleOf"]];
/**
* Chained string formats (`z.string().email()`, …) reduce to the top-level
* factory that replaced them, so a chained format and a top-level one compare
* as the same check.
*/
const CHAINED_STRING_FORMATS = ZOD_STRING_FORMAT_METHODS.map(({ sourceMethodName, replacementMethodName }) => [sourceMethodName, replacementMethodName]);
/**
* Chained spellings → canonical check names, per base type. `.min()`/`.max()`
* are type-dependent: length bounds on strings/arrays, value bounds on
* numbers/bigints/dates, size bounds on sets/maps.
*/
const CHAINED_CANONICAL = /* @__PURE__ */ new Map([
	["string", new Map([
		...CHAINED_COMMON,
		...CHAINED_STRING_FORMATS,
		["min", "minLength"],
		["max", "maxLength"],
		["length", "length"]
	])],
	["array", new Map([
		...CHAINED_COMMON,
		["min", "minLength"],
		["max", "maxLength"],
		["length", "length"]
	])],
	["number", new Map([
		...CHAINED_COMMON,
		["min", "gte"],
		["max", "lte"]
	])],
	["bigint", new Map([
		...CHAINED_COMMON,
		["min", "gte"],
		["max", "lte"]
	])],
	["date", new Map([
		...CHAINED_COMMON,
		["min", "gte"],
		["max", "lte"]
	])],
	["set", new Map([
		...CHAINED_COMMON,
		["min", "minSize"],
		["max", "maxSize"],
		["size", "size"]
	])],
	["map", new Map([
		...CHAINED_COMMON,
		["min", "minSize"],
		["max", "maxSize"],
		["size", "size"]
	])]
]);
/**
* Looks up what a check means by its canonical name (see
* {@link canonicalizeZodConstraintName}). Returns `null` for names the
* vocabulary does not model — callers should skip those rather than guess.
*/
function getZodCheckDescriptor(canonicalName) {
	return CHECK_DESCRIPTORS.get(canonicalName) ?? null;
}
/**
* Reduces a constraint's source spelling to the canonical check name shared by
* both API styles, so rule logic can compare `zod`'s `z.string().min(2)` with
* `zod/mini`'s `z.string().check(z.minLength(2))` as the same constraint.
*
* Chained names are type-dependent, hence the `baseType` argument: `.min()` is
* `minLength` on a string, `gte` on a number and `minSize` on a set.
* `.check(...)` arguments are already canonical, except the `iso.*` formats,
* whose factory resolves to the `iso` namespace and is read from the callee.
*
* Returns `null` when the spelling has no canonical form for that base type —
* an unknown method, or one that does not constrain the value.
*
* @example
* ```ts
* canonicalizeZodConstraintName(minConstraint, 'string'); // 'minLength'
* canonicalizeZodConstraintName(minConstraint, 'number'); // 'gte'
* canonicalizeZodConstraintName(emailConstraint, 'string'); // 'email'
* ```
*/
function canonicalizeZodConstraintName(constraint, baseType) {
	if (constraint.origin === "check-argument") {
		if (constraint.name !== "iso") return constraint.name;
		const { callee } = constraint.node;
		if (callee.type === AST_NODE_TYPES.MemberExpression && callee.property.type === AST_NODE_TYPES.Identifier) return `iso.${callee.property.name}`;
		return null;
	}
	return CHAINED_CANONICAL.get(baseType)?.get(constraint.name) ?? null;
}
//#endregion
export { canonicalizeZodConstraintName, getZodCheckDescriptor };
