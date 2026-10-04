import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { hasZodRuntimeImportRoot } from "../utils/has-zod-runtime-import-root.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { AST_NODE_TYPES } from "@typescript-eslint/utils";
const arrayStyle = createZodPluginRule({
	name: "array-style",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: { description: "Enforce consistent Zod array style" },
		messages: {
			useFunction: "Use z.array(schema) instead of schema.array().",
			useMethod: "Use schema.array() instead of z.array(schema)."
		},
		schema: [{
			type: "object",
			properties: { style: {
				description: "Decides which style for zod array function",
				type: "string",
				enum: ["function", "method"]
			} },
			additionalProperties: false
		}]
	},
	defaultOptions: [{ style: "function" }],
	create(context, [{ style }]) {
		const { sourceCode } = context;
		const { createSchemaVisitor, collectZodChainMethods } = zodImportScope.createTracker({ kind: "value" });
		return createSchemaVisitor({ onSchema(node, zodSchemaMeta) {
			if (!hasZodRuntimeImportRoot(node, sourceCode)) return;
			const { schemaDecl, schemaType } = zodSchemaMeta;
			if (style === "method") {
				if (schemaType === "array") {
					if (schemaDecl === "namespace") {
						context.report({
							node,
							messageId: "useMethod",
							fix(fixer) {
								const arrayCall = collectZodChainMethods(node).find((c) => c.name === "array");
								if (arrayCall?.node.arguments.length !== 1 || arrayCall.node.typeArguments || arrayCall.node.optional || arrayCall.node.callee.type === AST_NODE_TYPES.MemberExpression && arrayCall.node.callee.optional) return null;
								const [arg] = arrayCall.node.arguments;
								if (arg.type !== AST_NODE_TYPES.Identifier && arg.type !== AST_NODE_TYPES.MemberExpression && arg.type !== AST_NODE_TYPES.CallExpression) return null;
								if (sourceCode.getCommentsInside(arrayCall.node).some((comment) => comment.range[0] < arg.range[0] || comment.range[1] > arg.range[1])) return null;
								const argText = sourceCode.getText(arg);
								return fixer.replaceText(arrayCall.node, `${argText}.array()`);
							}
						});
						return;
					}
					context.report({
						node,
						messageId: "useMethod"
					});
				}
				return;
			}
			const arrayMethod = collectZodChainMethods(node).find((it) => it.name === "array" && it.node.arguments.length === 0);
			if (arrayMethod) {
				const arrayNode = arrayMethod.node;
				if (schemaDecl === "namespace") {
					context.report({
						node,
						messageId: "useFunction",
						fix(fixer) {
							const callee = arrayNode.callee;
							const objText = sourceCode.getText(callee.object);
							return fixer.replaceText(arrayNode, `z.array(${objText})`);
						}
					});
					return;
				}
				context.report({
					node,
					messageId: "useFunction"
				});
			}
		} });
	}
});
//#endregion
export { arrayStyle };
