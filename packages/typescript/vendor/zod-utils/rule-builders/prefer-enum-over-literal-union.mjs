import { AST_NODE_TYPES } from "../../ast-node-types/index.cjs";
//#region src/rule-builders/prefer-enum-over-literal-union.ts
function buildPreferEnumOverLiteralUnionCreate(scope) {
	return function create(context) {
		const { createSchemaVisitor, detectZodSchemaRootNode, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "union",
			onSchema(node, zodSchemaMeta) {
				const union = collectZodChainMethods(node).find((it) => it.name === "union");
				if (!union) return;
				const unionNode = union.node;
				const unionArgument = unionNode.arguments.at(0);
				if (unionArgument?.type !== AST_NODE_TYPES.ArrayExpression) return;
				const zodLiteralStrings = unionArgument.elements.map((s) => {
					if (!s) return null;
					if (s.type !== AST_NODE_TYPES.CallExpression) return null;
					if (detectZodSchemaRootNode(s)?.schemaType !== "literal") return null;
					const literalArgument = s.arguments.at(0);
					if (literalArgument?.type === AST_NODE_TYPES.Literal && typeof literalArgument.value === "string") return literalArgument.raw;
					return null;
				});
				if (zodLiteralStrings.some((it) => it === null)) return;
				context.report({
					node,
					messageId: "useEnum",
					fix(fixer) {
						if (zodSchemaMeta.schemaDecl === "named") return null;
						return [fixer.replaceText(unionNode.callee.property, "enum"), fixer.replaceText(unionNode.arguments[0], `[${zodLiteralStrings.join(", ")}]`)];
					}
				});
			}
		});
	};
}
//#endregion
export { buildPreferEnumOverLiteralUnionCreate };
