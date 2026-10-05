import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/no-native-enum.ts
/**
* Builds the `create` function for the `no-native-enum` rule.
*
* `nativeEnum` is a plain namespace factory in both `zod` and `zod/mini`,
* so the same detection and rename fix serve both plugins unchanged.
*/
function buildNoNativeEnumCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "nativeEnum",
			onSchema(node) {
				const rootMethodNode = collectZodChainMethods(node).at(0)?.node;
				context.report({
					node,
					messageId: "useEnum",
					fix(fixer) {
						if (rootMethodNode?.callee.type !== AST_NODE_TYPES.MemberExpression) return null;
						return fixer.replaceText(rootMethodNode.callee.property, "enum");
					}
				});
			}
		});
	};
}
//#endregion
export { buildNoNativeEnumCreate };
