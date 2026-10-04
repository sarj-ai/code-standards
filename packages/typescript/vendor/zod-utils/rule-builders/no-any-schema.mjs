import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/no-any-schema.ts
function buildNoAnySchemaCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "any",
			onSchema(node) {
				const { callee } = node;
				if (callee.type === AST_NODE_TYPES.Identifier) {
					context.report({
						node,
						messageId: "noZAny"
					});
					return;
				}
				if (callee.type === AST_NODE_TYPES.MemberExpression) {
					const schemaMethodCallee = collectZodChainMethods(node).at(0)?.node.callee;
					if (schemaMethodCallee?.type === AST_NODE_TYPES.MemberExpression && schemaMethodCallee.property.type === AST_NODE_TYPES.Identifier) {
						context.report({
							node,
							messageId: "noZAny",
							suggest: [{
								messageId: "useUnknown",
								fix(fixer) {
									return fixer.replaceText(schemaMethodCallee.property, "unknown");
								}
							}]
						});
						return;
					}
					context.report({
						node,
						messageId: "noZAny"
					});
				}
			}
		});
	};
}
//#endregion
export { buildNoAnySchemaCreate };
