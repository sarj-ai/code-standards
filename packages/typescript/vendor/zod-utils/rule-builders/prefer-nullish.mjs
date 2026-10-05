import { buildZodWrapperUnwrapFix } from "../build-zod-wrapper-unwrap-fix.mjs";
import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/prefer-nullish.ts
/**
* Builds the `create` function for the `prefer-nullish` rule.
*
* Handles both API spellings with the same logic:
* - chained methods (`zod`): `schema.optional().nullable()` /
* `schema.nullable().optional()`, found via `collectZodChainMethods` —
* the two methods must be directly adjacent in the chain.
* - wrapper factories (`zod/mini`): `z.optional(z.nullable(inner))` /
* `z.nullable(z.optional(inner))`,
* where the outer wrapper's single argument is the other bare wrapper (no intervening chain, no extra arguments).
*
* Both cases are equivalent to `nullish` and are autofixed to it.
*/
function buildPreferNullishCreate(scope) {
	return function create(context) {
		const { sourceCode } = context;
		const { createSchemaVisitor, detectZodSchemaRootNode, collectZodChainMethods, getNamedImportLocal } = scope.createTracker({ kind: "value" });
		/**
		* Fixer that renames the factory of a wrapper call to `nullish`.
		* Namespace style renames the member property (`z.optional` → `z.nullish`);
		* named style renames the callee identifier to `nullish`'s local name and returns `null` when `nullish` was not imported (an unsafe fix).
		*/
		function renameWrapperFactory(fixer, wrapperCall, schemaDecl) {
			const { callee } = wrapperCall;
			if (schemaDecl === "namespace") {
				const { property } = callee;
				return fixer.replaceText(property, "nullish");
			}
			if (callee.type !== AST_NODE_TYPES.Identifier) return null;
			const nullishLocalName = getNamedImportLocal("nullish");
			if (!nullishLocalName) return null;
			return fixer.replaceText(callee, nullishLocalName);
		}
		/** Wrapper form (`zod/mini`): `z.optional(z.nullable(inner))`. */
		function handleWrapper(node, meta) {
			const wrapperCall = collectZodChainMethods(node).at(0)?.node;
			if (wrapperCall?.arguments.length !== 1) return;
			const [inner] = wrapperCall.arguments;
			if (inner.type !== AST_NODE_TYPES.CallExpression) return;
			const other = meta.schemaType === "optional" ? "nullable" : "optional";
			if (detectZodSchemaRootNode(inner)?.schemaType !== other || collectZodChainMethods(inner).length !== 1 || inner.arguments.length !== 1 || inner.arguments[0].type === AST_NODE_TYPES.SpreadElement) return;
			context.report({
				node: wrapperCall,
				messageId: "preferNullish",
				fix(fixer) {
					const renameFix = renameWrapperFactory(fixer, wrapperCall, meta.schemaDecl);
					if (!renameFix) return null;
					const unwrapFix = buildZodWrapperUnwrapFix({
						fixer,
						sourceCode,
						wrapperCall: inner
					});
					if (!unwrapFix) return null;
					return [renameFix, unwrapFix];
				}
			});
		}
		/** Chained form (`zod`): `schema.optional().nullable()`. */
		function handleChained(node) {
			const methods = collectZodChainMethods(node);
			const optionalIndex = methods.findIndex((it) => it.name === "optional");
			const nullableIndex = methods.findIndex((it) => it.name === "nullable");
			if (optionalIndex === -1 || nullableIndex === -1) return;
			if (Math.abs(optionalIndex - nullableIndex) !== 1) return;
			const earlier = methods[Math.min(optionalIndex, nullableIndex)];
			const later = methods[Math.max(optionalIndex, nullableIndex)];
			context.report({
				node: later.node,
				messageId: "preferNullish",
				fix(fixer) {
					const earlierCallee = earlier.node.callee;
					const laterCallee = later.node.callee;
					if (earlierCallee.type !== AST_NODE_TYPES.MemberExpression || laterCallee.type !== AST_NODE_TYPES.MemberExpression || laterCallee.property.type !== AST_NODE_TYPES.Identifier) return null;
					return [fixer.replaceText(earlier.node, sourceCode.getText(earlierCallee.object)), fixer.replaceText(laterCallee.property, "nullish")];
				}
			});
		}
		return createSchemaVisitor({ onSchema(node, meta) {
			if (meta.schemaType === "optional" || meta.schemaType === "nullable") {
				handleWrapper(node, meta);
				return;
			}
			handleChained(node);
		} });
	};
}
//#endregion
export { buildPreferNullishCreate };
