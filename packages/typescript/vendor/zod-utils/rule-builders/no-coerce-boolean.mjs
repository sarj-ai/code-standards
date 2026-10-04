import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/no-coerce-boolean.ts
function buildNoCoerceBooleanCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "coerce",
			onSchema(node, zodSchemaMeta) {
				const coerceIndex = zodSchemaMeta.methods.indexOf("coerce");
				if (zodSchemaMeta.methods[coerceIndex + 1] !== "boolean") return;
				const factoryCallee = collectZodChainMethods(node).at(0)?.node.callee;
				if (zodSchemaMeta.schemaDecl !== "namespace" || factoryCallee?.type !== AST_NODE_TYPES.MemberExpression || factoryCallee.object.type !== AST_NODE_TYPES.MemberExpression) {
					context.report({
						node,
						messageId: "noCoerceBoolean"
					});
					return;
				}
				const namespaceNode = factoryCallee.object.object;
				context.report({
					node,
					messageId: "noCoerceBoolean",
					suggest: [{
						messageId: "useStringbool",
						fix(fixer) {
							const namespaceText = context.sourceCode.getText(namespaceNode);
							return fixer.replaceText(factoryCallee, `${namespaceText}.stringbool`);
						}
					}]
				});
			}
		});
	};
}
//#endregion
export { buildNoCoerceBooleanCreate };
