import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/no-throw-in-refine.ts
function buildNoThrowInRefineCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		function checkNode(node) {
			switch (node.type) {
				case AST_NODE_TYPES.ThrowStatement:
					context.report({
						node,
						messageId: "noThrowInRefine"
					});
					break;
				case AST_NODE_TYPES.BlockStatement:
					node.body.forEach(checkNode);
					break;
				case AST_NODE_TYPES.IfStatement:
					checkNode(node.consequent);
					if (node.alternate) checkNode(node.alternate);
					break;
				case AST_NODE_TYPES.ForStatement:
				case AST_NODE_TYPES.ForInStatement:
				case AST_NODE_TYPES.ForOfStatement:
				case AST_NODE_TYPES.WhileStatement:
				case AST_NODE_TYPES.DoWhileStatement:
					checkNode(node.body);
					break;
				case AST_NODE_TYPES.TryStatement:
					checkNode(node.block);
					if (node.handler) checkNode(node.handler.body);
					if (node.finalizer) checkNode(node.finalizer);
					break;
				case AST_NODE_TYPES.FunctionExpression:
				case AST_NODE_TYPES.ArrowFunctionExpression:
				case AST_NODE_TYPES.FunctionDeclaration:
			}
		}
		return createSchemaVisitor({ onSchema(node) {
			const refineMethod = collectZodChainMethods(node).find((it) => it.name === "refine");
			if (!refineMethod) return;
			const callback = refineMethod.node.arguments.at(0);
			if (callback?.type === AST_NODE_TYPES.ArrowFunctionExpression || callback?.type === AST_NODE_TYPES.FunctionExpression) checkNode(callback.body);
		} });
	};
}
//#endregion
export { buildNoThrowInRefineCreate };
