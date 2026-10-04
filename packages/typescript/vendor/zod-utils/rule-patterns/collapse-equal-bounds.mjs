import { getZodSchemaBaseType } from "../get-zod-schema-base-type.mjs";
import { buildZodChainRemoveMethodFix } from "../build-zod-chain-remove-method-fix.mjs";
import { ZOD_MUTATING_CHECK_NAMES } from "../zod-mutating-check-names.mjs";
import { canonicalizeZodConstraintName, getZodCheckDescriptor } from "../zod-check-vocabulary.mjs";
import { readIntegerLiteralValue } from "../read-integer-literal-value.mjs";
import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-patterns/collapse-equal-bounds.ts
/** Total by type, so the lookup cannot miss. */
const EXACT_CHECK_BY_DOMAIN = {
	length: "length",
	size: "size"
};
/** The bound's count, or `null` when it is not a literal or carries a message. */
function readBoundValue(constraint) {
	const { arguments: callArguments } = constraint.node;
	if (callArguments.length !== 1) return null;
	return readIntegerLiteralValue(callArguments[0]);
}
/**
* Renames a bound call to the exact check: `.min(3)` → `.length(3)`,
* `z.minLength(3)` → `z.length(3)`, `minLength(3)` → `length(3)`.
* `null` for a computed callee, or a named import the file lacks.
*/
function buildBoundRenameFix(opts) {
	const { fixer, constraint, exactCheckName, getNamedImportLocal } = opts;
	const { callee } = constraint.node;
	if (callee.type === AST_NODE_TYPES.Identifier) {
		const localName = getNamedImportLocal(exactCheckName);
		return localName === void 0 ? null : fixer.replaceText(callee, localName);
	}
	if (callee.type !== AST_NODE_TYPES.MemberExpression || callee.computed || callee.property.type !== AST_NODE_TYPES.Identifier) return null;
	return fixer.replaceText(callee.property, exactCheckName);
}
/**
* Removes the redundant bound: a chained method,
* the whole `.check(...)` when the bound was its only argument,
* or that argument plus one separator.
*/
function buildBoundRemoveFix(opts) {
	const { fixer, methods, constraint } = opts;
	if (constraint.origin === "chained" || constraint.argumentCount === 1) return buildZodChainRemoveMethodFix({
		fixer,
		methods,
		removeIndex: constraint.chainIndex
	});
	const callArguments = constraint.checkNode.arguments;
	const { argumentIndex } = constraint;
	const target = callArguments[argumentIndex];
	return argumentIndex === 0 ? fixer.removeRange([target.range[0], callArguments[1].range[0]]) : fixer.removeRange([callArguments[argumentIndex - 1].range[1], target.range[1]]);
}
/**
* Collapses an equal lower/upper bound pair into the exact check of the same domain:
* `z.string().min(3).max(3)` → `z.string().length(3)`.
*
* Bounds are matched by meaning (`bound.kind`, `bound.domain`) through the shared check vocabulary,
* so both API styles work from one implementation.
* Stays silent — rather than reporting unfixably —
* whenever the pair is not provably the exact check: a non-literal or error-message argument,
* a bound with its value baked in (`nonempty`), a mutating check between the two,
* or more bounds than a single pair.
* Those belong to `no-conflicting-checks`.
*/
function buildCollapseEqualBoundsCreate(options) {
	const { scope, baseTypes, domain, messageId } = options;
	const exactCheckName = EXACT_CHECK_BY_DOMAIN[domain];
	return function create(context) {
		const { createSchemaVisitor, collectZodChainMethods, collectZodSchemaConstraints, getNamedImportLocal } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({ onSchema(node, zodSchemaMeta) {
			const baseType = getZodSchemaBaseType(zodSchemaMeta.schemaType);
			if (baseType === null || !baseTypes.includes(baseType)) return;
			const constraints = collectZodSchemaConstraints(node);
			const bounds = [];
			const mutatingIndexes = [];
			for (const [index, constraint] of constraints.entries()) {
				if (ZOD_MUTATING_CHECK_NAMES.includes(constraint.name)) {
					mutatingIndexes.push(index);
					continue;
				}
				const canonicalName = canonicalizeZodConstraintName(constraint, baseType);
				const bound = canonicalName === null ? void 0 : getZodCheckDescriptor(canonicalName)?.bound;
				if (bound?.domain !== domain) continue;
				if (bound.fixedValue !== void 0) return;
				bounds.push({
					index,
					kind: bound.kind,
					constraint
				});
			}
			const lowerBounds = bounds.filter((it) => it.kind === "lower");
			const upperBounds = bounds.filter((it) => it.kind === "upper");
			if (bounds.length !== 2 || lowerBounds.length !== 1 || upperBounds.length !== 1) return;
			const [lowerBound] = lowerBounds;
			const [upperBound] = upperBounds;
			const lowerValue = readBoundValue(lowerBound.constraint);
			if (lowerValue === null || lowerValue !== readBoundValue(upperBound.constraint)) return;
			const [firstBound, secondBound] = lowerBound.index < upperBound.index ? [lowerBound, upperBound] : [upperBound, lowerBound];
			if (mutatingIndexes.some((index) => index > firstBound.index && index < secondBound.index)) return;
			context.report({
				node,
				messageId,
				fix(fixer) {
					const renameFix = buildBoundRenameFix({
						fixer,
						constraint: firstBound.constraint,
						exactCheckName,
						getNamedImportLocal
					});
					if (renameFix === null) return null;
					const removeFix = buildBoundRemoveFix({
						fixer,
						methods: collectZodChainMethods(node),
						constraint: secondBound.constraint
					});
					return removeFix === null ? null : [renameFix, removeFix];
				}
			});
		} });
	};
}
//#endregion
export { buildCollapseEqualBoundsCreate };
