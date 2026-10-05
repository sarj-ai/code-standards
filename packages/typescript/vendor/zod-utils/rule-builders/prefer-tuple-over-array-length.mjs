import { buildZodConstraintsRemoveFix } from "../build-zod-constraints-remove-fix.mjs";
import { canonicalizeZodConstraintName } from "../zod-check-vocabulary.mjs";
import { readIntegerLiteralValue } from "../read-integer-literal-value.mjs";
import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/prefer-tuple-over-array-length.ts
/**
* Length constraints by canonical name.
* Both API styles reduce to these via `canonicalizeZodConstraintName`,
* so chained methods `.length()` / `.min()` / `.max()`, `zod`)
* and standalone checks (`z.length()` / `z.minLength()` / `z.maxLength()`, `zod/mini`)
* are matched by the same three entries.
*/
const LENGTH_CONSTRAINT_KINDS = /* @__PURE__ */ new Map([
	["length", "length"],
	["minLength", "min"],
	["maxLength", "max"]
]);
/**
* Builds the `create` function for the `prefer-tuple-over-array-length` rule.
*
* Detection is API-style agnostic:
* length constraints are collected via `collectZodSchemaConstraints`,
* so chained methods (`.length()` / `.min()` / `.max()`, `zod`)
* and standalone checks passed to `.check(...)` (`z.length()` / `z.minLength()` / `z.maxLength()`, `zod/mini`)
* are recognized by the same logic, whichever style the plugin's API uses.
*/
function buildPreferTupleOverArrayLengthCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, collectZodChainMethods, collectZodSchemaConstraints } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "array",
			onSchema(node, zodSchemaMeta) {
				const methods = collectZodChainMethods(node);
				const constraints = collectZodSchemaConstraints(node);
				const candidates = [];
				for (const constraint of constraints) {
					const canonical = canonicalizeZodConstraintName(constraint, "array");
					const candidateKind = canonical === null ? void 0 : LENGTH_CONSTRAINT_KINDS.get(canonical);
					if (candidateKind) candidates.push({
						kind: candidateKind,
						constraint,
						countArgument: constraint.node.arguments.at(0) ?? null
					});
				}
				if (candidates.length === 0) return;
				const hasNonempty = constraints.some((it) => it.name === "nonempty");
				const lengthCandidates = candidates.filter((it) => it.kind === "length");
				const minCandidates = candidates.filter((it) => it.kind === "min");
				const maxCandidates = candidates.filter((it) => it.kind === "max");
				let kind;
				let countArgument;
				let removable;
				if (candidates.length === 1 && lengthCandidates.length === 1 && !hasNonempty) {
					const [only] = lengthCandidates;
					kind = "length";
					countArgument = only.countArgument;
					removable = [only.constraint];
				} else if (candidates.length === 2 && minCandidates.length === 1 && maxCandidates.length === 1 && !hasNonempty) {
					const [min] = minCandidates;
					const [max] = maxCandidates;
					const minValue = readIntegerLiteralValue(min.countArgument);
					const maxValue = readIntegerLiteralValue(max.countArgument);
					kind = "length";
					countArgument = min.countArgument;
					removable = minValue !== null && minValue === maxValue ? [min.constraint, max.constraint] : null;
				} else if (candidates.length === 1 && minCandidates.length === 1 && !hasNonempty) {
					const [only] = minCandidates;
					kind = "min";
					countArgument = only.countArgument;
					removable = [only.constraint];
				} else {
					const chosen = lengthCandidates.at(0) ?? candidates[0];
					kind = chosen.kind;
					countArgument = chosen.countArgument;
					removable = null;
				}
				context.report({
					node,
					messageId: "preferTuple",
					fix(fixer) {
						if (kind === "max" || removable === null) return null;
						const count = readIntegerLiteralValue(countArgument);
						if (count === null) return null;
						if (zodSchemaMeta.schemaDecl === "named") return null;
						const arrayNode = methods.find((it) => it.name === "array")?.node;
						if (arrayNode?.arguments.length !== 1) return null;
						const [element] = arrayNode.arguments;
						if (element.type === AST_NODE_TYPES.SpreadElement) return null;
						const arrayCallee = arrayNode.callee;
						const removeFixes = buildZodConstraintsRemoveFix({
							fixer,
							methods,
							constraints: removable
						});
						if (removeFixes === null) return null;
						const elementText = context.sourceCode.getText(element);
						const items = Array.from({ length: count }, () => elementText).join(", ");
						const tupleArguments = kind === "min" ? `[${items}], ${elementText}` : `[${items}]`;
						return [
							fixer.replaceText(arrayCallee.property, "tuple"),
							fixer.replaceText(element, tupleArguments),
							...removeFixes
						];
					}
				});
			}
		});
	};
}
//#endregion
export { buildPreferTupleOverArrayLengthCreate };
