import { getZodSchemaBaseType } from "../get-zod-schema-base-type.mjs";
import { ZOD_TYPE_CHANGING_METHODS } from "../zod-type-changing-methods.mjs";
import { canonicalizeZodConstraintName, getZodCheckDescriptor } from "../zod-check-vocabulary.mjs";
import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/no-conflicting-checks.ts
/** Length range `[min, max]` of well-known fixed-shape formats. */
const FORMAT_LENGTH_RANGES = /* @__PURE__ */ new Map([
	["uuid", [36, 36]],
	["uuidv4", [36, 36]],
	["uuidv6", [36, 36]],
	["uuidv7", [36, 36]],
	["guid", [36, 36]],
	["ulid", [26, 26]],
	["nanoid", [21, 21]],
	["ksuid", [27, 27]],
	["xid", [20, 20]],
	["mac", [17, 17]],
	["ipv4", [7, 15]],
	["ipv6", [2, 45]],
	["e164", [8, 16]],
	["creditCard", [12, 37]],
	["jwt", [8, Number.POSITIVE_INFINITY]],
	["iso.date", [10, 10]]
]);
/**
* String formats that are narrowings of another format:
* every value matching the key also matches each listed name.
* Combining two of them is a valid refinement (`z.string().uuid().uuidv4()`), not a contradiction,
* so {@link areFormatsCompatible} exempts these pairs.
*
* Only the GUID/UUID family overlaps — `guid` accepts any `8-4-4-4-12` hex shape,
* `uuid` additionally requires a valid variant/version nibble,
* and `uuidv4`/`uuidv6`/`uuidv7` pin that version.
* Every other format pair is mutually exclusive.
*/
const FORMAT_SUPERSETS = /* @__PURE__ */ new Map([
	["uuid", ["guid"]],
	["uuidv4", ["uuid", "guid"]],
	["uuidv6", ["uuid", "guid"]],
	["uuidv7", ["uuid", "guid"]]
]);
/** True when two format checks can both hold for the same value. */
function areFormatsCompatible(a, b) {
	return a === b || (FORMAT_SUPERSETS.get(a)?.includes(b) ?? false) || (FORMAT_SUPERSETS.get(b)?.includes(a) ?? false);
}
function asNumeric(value) {
	return typeof value === "number" || typeof value === "bigint" ? value : void 0;
}
/**
* Equality across `number` and `bigint`, e.g. `5` and `5n`.
* Strict `===` is always `false` between the two types, but `<`/`>` compare them mathematically,
* so `!(a < b) && !(a > b)` means "equal in value".
* Needed because the plugin lints plain JS,
* where a schema's bounds can mix literal types (`z.bigint().gt(5n).lte(5)`).
*/
function numericEqual(a, b) {
	return !(a < b) && !(a > b);
}
/** `lower`/`upper` bounds that cannot both hold leave the range empty. */
function boundsConflict(lower, upper) {
	if (lower.value > upper.value) return true;
	return numericEqual(lower.value, upper.value) && !(lower.inclusive && upper.inclusive);
}
function strongestLower(bounds) {
	let strongest;
	for (const bound of bounds) if (!strongest || bound.value > strongest.value || numericEqual(bound.value, strongest.value) && !bound.inclusive && strongest.inclusive) strongest = bound;
	return strongest;
}
function strongestUpper(bounds) {
	let strongest;
	for (const bound of bounds) if (!strongest || bound.value < strongest.value || numericEqual(bound.value, strongest.value) && !bound.inclusive && strongest.inclusive) strongest = bound;
	return strongest;
}
/**
* Builds the `create` function for the `no-conflicting-checks` rule.
*
* All detection is written against `collectZodSchemaConstraints`,
* so chained methods (`zod`) and `.check(...)` arguments (`zod/mini`) —
* including multi-argument and repeated `.check()` calls —
* are analyzed by the same engine in both plugins.
* Only literal arguments are analyzed;
* constraints with non-literal arguments are excluded from value reasoning.
*/
function buildNoConflictingChecksCreate(scope) {
	return function create(context) {
		const options = {
			checkImpossibleCases: true,
			checkConfusingCases: true,
			checkInapplicableChecks: true,
			...context.options.at(0)
		};
		const { createSchemaVisitor, collectZodChainMethods, collectZodSchemaConstraints } = scope.createTracker({ kind: "value" });
		function describe(check) {
			const args = check.node.arguments.map((argument) => context.sourceCode.getText(argument)).join(", ");
			return `${check.rawName}(${args})`;
		}
		function reportImpossiblePair(a, b) {
			if (!options.checkImpossibleCases) return;
			const [first, second] = a.index <= b.index ? [a, b] : [b, a];
			context.report({
				node: second.node,
				messageId: "impossibleCase",
				data: {
					first: describe(first),
					second: describe(second)
				}
			});
		}
		function reportRedundant(redundant, by) {
			if (!options.checkConfusingCases) return;
			context.report({
				node: redundant.node,
				messageId: "redundantCheck",
				data: {
					redundant: describe(redundant),
					by: describe(by)
				}
			});
		}
		function reportPointless(check, reason) {
			if (!options.checkConfusingCases) return;
			context.report({
				node: check.node,
				messageId: "pointlessCheck",
				data: {
					check: describe(check),
					reason
				}
			});
		}
		function reportInapplicable(check, baseType) {
			if (!options.checkInapplicableChecks) return;
			context.report({
				node: check.node,
				messageId: "inapplicableCheck",
				data: {
					check: describe(check),
					baseType
				}
			});
		}
		function readLiteralArgument(node) {
			const argument = node.arguments.at(0);
			if (argument?.type !== AST_NODE_TYPES.Literal) return;
			const { value } = argument;
			if (typeof value === "string" || typeof value === "number" || typeof value === "bigint" || typeof value === "boolean") return value;
		}
		/** Bounds reasoning: empty ranges (impossible) and implied bounds (redundant). */
		function analyzeBounds(checks, domain) {
			const lowers = [];
			const uppers = [];
			const exacts = [];
			let impliedLower;
			let impliedUpper;
			for (const check of checks) {
				const { bound, content, format } = check.descriptor;
				if (bound?.domain === domain) {
					const value = bound.fixedValue ?? asNumeric(check.literalValue);
					if (value !== void 0) {
						const entry = {
							value,
							inclusive: bound.inclusive ?? true,
							check
						};
						if (bound.kind === "lower") lowers.push(entry);
						else if (bound.kind === "upper") uppers.push(entry);
						else exacts.push(entry);
					}
				}
				if (domain !== "length") continue;
				if (content && typeof check.literalValue === "string") {
					const needed = check.literalValue.length;
					if (!impliedLower || needed > impliedLower.value) impliedLower = {
						value: needed,
						inclusive: true,
						check
					};
				}
				if (format) {
					const range = FORMAT_LENGTH_RANGES.get(check.canonical);
					if (range) {
						const [formatMin, formatMax] = range;
						if (!impliedLower || formatMin > impliedLower.value) impliedLower = {
							value: formatMin,
							inclusive: true,
							check
						};
						if (Number.isFinite(formatMax) && (!impliedUpper || formatMax < impliedUpper.value)) impliedUpper = {
							value: formatMax,
							inclusive: true,
							check
						};
					}
				}
			}
			const lower = strongestLower(lowers);
			const upper = strongestUpper(uppers);
			if (lower && upper && boundsConflict(lower, upper)) reportImpossiblePair(lower.check, upper.check);
			for (const exact of exacts) {
				for (const low of [lower, impliedLower]) if (low && boundsConflict(low, exact)) reportImpossiblePair(low.check, exact.check);
				for (const high of [upper, impliedUpper]) if (high && boundsConflict(exact, high)) reportImpossiblePair(exact.check, high.check);
			}
			const [firstExact] = exacts;
			for (const exact of exacts.slice(1)) if (numericEqual(exact.value, firstExact.value)) reportRedundant(exact.check, firstExact.check);
			else reportImpossiblePair(firstExact.check, exact.check);
			if (impliedLower && upper && boundsConflict(impliedLower, upper)) reportImpossiblePair(impliedLower.check, upper.check);
			if (impliedUpper && lower && boundsConflict(lower, impliedUpper)) reportImpossiblePair(lower.check, impliedUpper.check);
			for (const bound of lowers) if (lower && bound !== lower) reportRedundant(bound.check, lower.check);
			for (const bound of uppers) if (upper && bound !== upper) reportRedundant(bound.check, upper.check);
		}
		/** Any two mutually exclusive string formats can never both match. */
		function analyzeFormats(checks) {
			const formats = checks.filter((check) => check.descriptor.format);
			const [first] = formats;
			for (const format of formats.slice(1)) if (!areFormatsCompatible(first.canonical, format.canonical)) reportImpossiblePair(first, format);
		}
		/** Reports each check another one already guarantees; of two identical ones, only the later. */
		function reportImplied(entries, implies) {
			for (const weaker of entries) {
				let strongest;
				for (const candidate of entries) {
					if (candidate === weaker || !implies(candidate, weaker)) continue;
					if (implies(weaker, candidate) && candidate.index > weaker.index) continue;
					if (!strongest || implies(candidate, strongest)) strongest = candidate;
				}
				if (strongest) reportRedundant(weaker, strongest);
			}
		}
		/** Anchored content checks are compatible only when one extends the other. */
		function reportAnchorConflicts(entries, holds) {
			for (const [index, a] of entries.entries()) for (const b of entries.slice(index + 1)) if (!holds(a, b) && !holds(b, a)) reportImpossiblePair(a, b);
		}
		/** Prefixes/suffixes that cannot coexist, and content checks another one already covers. */
		function analyzeContent(checks) {
			for (const kind of [
				"startsWith",
				"endsWith",
				"includes"
			]) {
				const entries = checks.filter((check) => check.descriptor.content === kind && typeof check.literalValue === "string");
				const holds = (stronger, weaker) => stronger.literalValue[kind](weaker.literalValue);
				if (kind !== "includes") reportAnchorConflicts(entries, holds);
				reportImplied(entries, holds);
			}
		}
		/** Repeated `regex(...)`, compared by source text: two spellings of one pattern stay distinct. */
		function analyzeRegex(checks) {
			const entries = checks.filter((check) => check.canonical === "regex" && check.node.arguments.length > 0 && check.node.arguments[0].type !== AST_NODE_TYPES.SpreadElement);
			const pattern = (check) => context.sourceCode.getText(check.node.arguments[0]);
			reportImplied(entries, (stronger, weaker) => pattern(stronger) === pattern(weaker));
		}
		/** `lowercase` + `uppercase` only matches strings without case distinctions. */
		function analyzeCasing(checks) {
			if (!options.checkConfusingCases) return;
			const lower = checks.find((check) => check.descriptor.casing === "lowercase");
			const upper = checks.find((check) => check.descriptor.casing === "uppercase");
			if (lower && upper) {
				const [first, second] = lower.index <= upper.index ? [lower, upper] : [upper, lower];
				context.report({
					node: second.node,
					messageId: "confusingCombination",
					data: {
						first: describe(first),
						second: describe(second)
					}
				});
			}
		}
		/** `multipleOf` values where one implies the other, and `int` + `multipleOf(1)`. */
		function analyzeMultiples(checks) {
			const multiples = checks.filter((check) => check.descriptor.multipleOf && asNumeric(check.literalValue) !== void 0);
			const intMarker = checks.find((check) => check.descriptor.intMarker);
			for (const [index, a] of multiples.entries()) {
				const left = asNumeric(a.literalValue);
				for (const b of multiples.slice(index + 1)) {
					const right = asNumeric(b.literalValue);
					if (typeof left !== typeof right) continue;
					if (left === right) reportRedundant(b, a);
					else if (typeof left === "number" && typeof right === "number") {
						if (right % left === 0) reportRedundant(a, b);
						else if (left % right === 0) reportRedundant(b, a);
					} else if (typeof left === "bigint" && typeof right === "bigint") {
						if (right % left === BigInt(0)) reportRedundant(a, b);
						else if (left % right === BigInt(0)) reportRedundant(b, a);
					}
				}
				if (intMarker && (left === 1 || left === BigInt(1))) reportRedundant(a, intMarker);
			}
		}
		/** Evaluates a check against a literal value: `true`, `false`, or not decidable. */
		function evaluateOnLiteral(check, literal) {
			const { bound, content, casing, multipleOf, intMarker } = check.descriptor;
			if (bound) {
				let subject;
				if (bound.domain === "length") subject = typeof literal === "string" ? literal.length : void 0;
				else subject = asNumeric(literal);
				const value = bound.fixedValue ?? asNumeric(check.literalValue);
				if (subject === void 0 || value === void 0) return;
				if (bound.kind === "exact") return numericEqual(subject, value);
				if (bound.kind === "lower") return subject > value || numericEqual(subject, value) && (bound.inclusive ?? true);
				return subject < value || numericEqual(subject, value) && (bound.inclusive ?? true);
			}
			if (content && typeof literal === "string" && typeof check.literalValue === "string") return literal[content](check.literalValue);
			if (casing && typeof literal === "string") return casing === "lowercase" ? literal === literal.toLowerCase() : literal === literal.toUpperCase();
			if (multipleOf) {
				const divisor = asNumeric(check.literalValue);
				if (typeof literal === "number" && typeof divisor === "number") return literal % divisor === 0;
				if (typeof literal === "bigint" && typeof divisor === "bigint") return literal % divisor === BigInt(0);
				return;
			}
			if (intMarker) return typeof literal === "number" ? Number.isInteger(literal) : void 0;
		}
		/** A literal either already satisfies a check (pointless) or never can (impossible). */
		function analyzeLiteral(chain, checks) {
			const literal = readLiteralArgument(chain[0].node);
			if (literal === void 0) return;
			let literalBase;
			if (typeof literal === "string") literalBase = "string";
			else if (typeof literal === "number") literalBase = "number";
			else if (typeof literal === "bigint") literalBase = "bigint";
			else literalBase = "boolean";
			const literalDisplay = {
				canonical: "literal",
				descriptor: { appliesTo: [] },
				node: chain[0].node,
				rawName: "literal",
				index: -1,
				origin: "chained"
			};
			for (const check of checks) {
				if (!check.descriptor.appliesTo.includes(literalBase)) {
					reportInapplicable(check, literalBase);
					continue;
				}
				const verdict = evaluateOnLiteral(check, literal);
				if (verdict === true) reportPointless(check, "the literal already satisfies it");
				else if (verdict === false) reportImpossiblePair(literalDisplay, check);
			}
		}
		return createSchemaVisitor({ onSchema(node, zodSchemaMeta) {
			const chain = collectZodChainMethods(node);
			if (chain.length === 0) return;
			if (chain.slice(1).some((item) => ZOD_TYPE_CHANGING_METHODS.includes(item.name))) return;
			const baseType = getZodSchemaBaseType(zodSchemaMeta.schemaType);
			if (!baseType) return;
			const checks = [];
			const baseDescriptor = getZodCheckDescriptor(zodSchemaMeta.schemaType);
			if (baseDescriptor?.format) checks.push({
				canonical: zodSchemaMeta.schemaType,
				descriptor: baseDescriptor,
				node: chain[0].node,
				rawName: zodSchemaMeta.schemaType,
				index: 0,
				origin: "chained"
			});
			for (const [index, constraint] of collectZodSchemaConstraints(node).entries()) {
				const canonical = canonicalizeZodConstraintName(constraint, baseType);
				if (canonical === null) continue;
				const descriptor = getZodCheckDescriptor(canonical);
				if (descriptor === null) continue;
				checks.push({
					canonical,
					descriptor,
					node: constraint.node,
					rawName: constraint.name,
					literalValue: readLiteralArgument(constraint.node),
					index: index + 1,
					origin: constraint.origin
				});
			}
			if (checks.length === 0) return;
			if (baseType === "literal") {
				analyzeLiteral(chain, checks);
				return;
			}
			if (baseType === "any" || baseType === "unknown" || baseType === "never") {
				const reason = baseType === "never" ? "`never` already matches nothing" : `it constrains \`${baseType}\` — use a typed schema instead`;
				for (const check of checks) reportPointless(check, reason);
				return;
			}
			const applicable = [];
			for (const check of checks) {
				if (check.descriptor.appliesTo.includes(baseType)) {
					applicable.push(check);
					continue;
				}
				if (check.origin === "check-argument") reportInapplicable(check, baseType);
			}
			analyzeBounds(applicable, "length");
			analyzeBounds(applicable, "size");
			analyzeBounds(applicable, "value");
			analyzeFormats(applicable);
			analyzeContent(applicable);
			analyzeRegex(applicable);
			analyzeCasing(applicable);
			analyzeMultiples(applicable);
		} });
	};
}
//#endregion
export { buildNoConflictingChecksCreate };
