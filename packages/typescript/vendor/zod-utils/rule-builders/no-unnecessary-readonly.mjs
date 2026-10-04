import { buildZodConstraintsRemoveFix } from "../build-zod-constraints-remove-fix.mjs";
import { buildZodWrapperUnwrapFix } from "../build-zod-wrapper-unwrap-fix.mjs";
import { ZOD_IMMUTABLE_SCHEMA_TYPES } from "../zod-immutable-schema-types.mjs";
import { ZOD_TYPE_CHANGING_METHODS } from "../zod-type-changing-methods.mjs";
import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/no-unnecessary-readonly.ts
/**
* Wrapper factories whose output immutability equals their first argument's (e.g. `z.optional(z.string())` is as immutable as `z.string()`).
*/
const PASSTHROUGH_WRAPPERS = [
	"_default",
	"catch",
	"default",
	"nonoptional",
	"nullable",
	"nullish",
	"optional"
];
/**
* Builds the `create` function for the `no-unnecessary-readonly` rule.
*
* Handles both API spellings with the same logic:
* the chained `.readonly()` method (`zod`) is found via `collectZodSchemaConstraints`,
* and the `z.readonly(inner)` wrapper (`zod/mini`) via the schema root's factory.
* A `readonly` is reported when the schema it wraps is already immutable —
* its base type is a primitive/scalar (`ZOD_IMMUTABLE_SCHEMA_TYPES`, looked up through passthrough wrappers such as `optional`) or it is itself already `readonly`.
*/
function buildNoUnnecessaryReadonlyCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, detectZodSchemaRootNode, collectZodChainMethods, collectZodSchemaConstraints } = scope.createTracker({ kind: "value" });
		/** Immutability of the schema produced by `chain[0..endIndex)`. */
		function classifyChain(schemaType, chain, endIndex) {
			const precedingNames = chain.slice(1, endIndex).map((it) => it.name);
			if (precedingNames.some((name) => ZOD_TYPE_CHANGING_METHODS.includes(name))) return "unknown";
			if (precedingNames.includes("readonly") || schemaType === "readonly") return "readonly";
			if (ZOD_IMMUTABLE_SCHEMA_TYPES.includes(schemaType)) return "immutable";
			if (PASSTHROUGH_WRAPPERS.includes(schemaType)) {
				const argument = chain.at(0)?.node.arguments.at(0);
				if (argument?.type !== AST_NODE_TYPES.CallExpression) return "unknown";
				const argumentMeta = detectZodSchemaRootNode(argument);
				if (!argumentMeta) return "unknown";
				const argumentChain = collectZodChainMethods(argument);
				return classifyChain(argumentMeta.schemaType, argumentChain, argumentChain.length);
			}
			return "unknown";
		}
		/** Immutability of an arbitrary expression (e.g. a wrapper argument). */
		function classifyExpression(node) {
			if (node?.type !== AST_NODE_TYPES.CallExpression) return "unknown";
			const meta = detectZodSchemaRootNode(node);
			if (!meta) return "unknown";
			const chain = collectZodChainMethods(node);
			return classifyChain(meta.schemaType, chain, chain.length);
		}
		return createSchemaVisitor({ onSchema(node, zodSchemaMeta) {
			const methods = collectZodChainMethods(node);
			if (zodSchemaMeta.schemaType === "readonly") {
				const wrapperCall = methods.at(0)?.node;
				const immutability = classifyExpression(wrapperCall?.arguments.length === 1 ? wrapperCall.arguments.at(0) : void 0);
				if (wrapperCall && immutability !== "unknown") context.report({
					node: wrapperCall,
					messageId: "unnecessaryReadonly",
					fix: (fixer) => buildZodWrapperUnwrapFix({
						fixer,
						sourceCode: context.sourceCode,
						wrapperCall
					})
				});
			}
			const readonlyConstraints = collectZodSchemaConstraints(node).filter((it) => it.origin === "chained" && it.name === "readonly");
			for (const constraint of readonlyConstraints) if (classifyChain(zodSchemaMeta.schemaType, methods, constraint.chainIndex) !== "unknown") context.report({
				node: constraint.node,
				messageId: "unnecessaryReadonly",
				fix: (fixer) => buildZodConstraintsRemoveFix({
					fixer,
					methods,
					constraints: [constraint]
				})
			});
		} });
	};
}
//#endregion
export { buildNoUnnecessaryReadonlyCreate };
