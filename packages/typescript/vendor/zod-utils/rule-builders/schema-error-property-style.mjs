import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
import esquery from "esquery";
//#region src/rule-builders/schema-error-property-style.ts
function buildSchemaErrorPropertyStyleCreate(scope) {
	return function create(context, [{ selector, example }]) {
		const { createSchemaVisitor, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		let parsedSelector;
		/**
		* Parsing `selector` to ensure it is valid,
		* if not report an error and return empty rule listener
		*/
		try {
			parsedSelector = esquery.parse(selector);
		} catch {
			context.report({
				loc: {
					line: 1,
					column: 0
				},
				messageId: "invalidSelector",
				data: { selector }
			});
			return {};
		}
		return createSchemaVisitor({ onSchema(node, zodSchemaMeta) {
			if (zodSchemaMeta.schemaType !== "custom" && !collectZodChainMethods(node).some((it) => it.name === "refine")) return;
			if (node.arguments.length < 2) return;
			let errorMessageNode;
			const [, params] = node.arguments;
			switch (params.type) {
				case AST_NODE_TYPES.Literal:
				case AST_NODE_TYPES.TemplateLiteral:
					errorMessageNode = params;
					break;
				case AST_NODE_TYPES.ObjectExpression: for (const property of params.properties) if (property.type === AST_NODE_TYPES.Property && property.key.type === AST_NODE_TYPES.Identifier && property.key.name === "error") {
					errorMessageNode = property.value;
					break;
				}
			}
			if (!errorMessageNode) return;
			if (esquery.matches(errorMessageNode, parsedSelector, errorMessageNode)) return;
			context.report({
				node,
				messageId: "invalidStyle",
				data: {
					selector,
					example,
					actual: context.sourceCode.getText(errorMessageNode)
				}
			});
		} });
	};
}
//#endregion
export { buildSchemaErrorPropertyStyleCreate };
