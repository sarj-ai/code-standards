import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/require-error-message.ts
function buildRequireErrorMessageCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({ onSchema(node) {
			const refines = collectZodChainMethods(node).filter((it) => it.name === "refine" || it.name === "custom");
			if (refines.length === 0) return;
			for (const refine of refines) {
				const refineNode = refine.node;
				if (refineNode.arguments.length < 2) {
					context.report({
						messageId: "requireErrorMessage",
						node: refineNode
					});
					continue;
				}
				const [, params] = refineNode.arguments;
				if (params.type === AST_NODE_TYPES.Literal) continue;
				if (params.type !== AST_NODE_TYPES.ObjectExpression) continue;
				let errorPropertyNode;
				let messagePropertyNode;
				for (const property of params.properties) if (property.type === AST_NODE_TYPES.Property && property.key.type === AST_NODE_TYPES.Identifier) {
					if (property.key.name === "error") errorPropertyNode = property;
					if (property.key.name === "message") messagePropertyNode = property;
					if (errorPropertyNode && messagePropertyNode) break;
				}
				if (errorPropertyNode && messagePropertyNode) {
					context.report({
						messageId: "removeMessage",
						node: messagePropertyNode,
						fix(fixer) {
							const { sourceCode } = context;
							const nextToken = sourceCode.getTokenAfter(messagePropertyNode);
							let [, end] = messagePropertyNode.range;
							if (nextToken?.value === ",") end = nextToken.range[1];
							return fixer.removeRange([messagePropertyNode.range[0], end]);
						}
					});
					continue;
				}
				if (messagePropertyNode && !errorPropertyNode) {
					context.report({
						messageId: "preferError",
						node: params,
						fix(fixer) {
							return fixer.replaceTextRange(messagePropertyNode.key.range, "error");
						}
					});
					continue;
				}
				if (!errorPropertyNode) context.report({
					messageId: "requireErrorMessage",
					node: params
				});
			}
		} });
	};
}
//#endregion
export { buildRequireErrorMessageCreate };
