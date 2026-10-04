import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
//#region src/rules/no-optional-and-default-together.ts
const preferredMethods = [
	"none",
	"default",
	"optional"
];
const defaultOptions = { preferredMethod: "none" };
const noOptionalAndDefaultTogether = createZodPluginRule({
	name: "no-optional-and-default-together",
	meta: {
		type: "problem",
		fixable: "code",
		docs: { description: "Disallow using both `.optional()` and `.default()` on the same Zod schema" },
		messages: {
			noOptionalAndDefaultTogether: "Using both `.optional()` and `.default()` is redundant. A schema with a default value is already optional.",
			noOptionalAndDefaultTogetherRemoveMethod: "Using both `.optional()` and `.default()` is redundant. Remove the `.{{method}}()` method to avoid redundancy."
		},
		schema: [{
			type: "object",
			properties: { preferredMethod: {
				description: "Determines which method to keep when both are present",
				type: "string",
				enum: [...preferredMethods]
			} },
			additionalProperties: false
		}]
	},
	defaultOptions: [defaultOptions],
	create(context, [{ preferredMethod }]) {
		const { sourceCode } = context;
		const { createSchemaVisitor, collectZodChainMethods } = zodImportScope.createTracker({ kind: "value" });
		return createSchemaVisitor({ onSchema(node) {
			const methods = collectZodChainMethods(node);
			if (methods.length === 0) return;
			const optionalMethod = methods.find((m) => m.name === "optional");
			const defaultMethod = methods.find((m) => m.name === "default");
			if (!optionalMethod || !defaultMethod) return;
			const reportNode = methods.indexOf(optionalMethod) > methods.indexOf(defaultMethod) ? optionalMethod.node : defaultMethod.node;
			if (preferredMethod === "none") {
				context.report({
					node: reportNode,
					messageId: "noOptionalAndDefaultTogether"
				});
				return;
			}
			const methodToRemoveName = preferredMethod === "default" ? "optional" : "default";
			context.report({
				node: reportNode,
				messageId: "noOptionalAndDefaultTogetherRemoveMethod",
				data: { method: methodToRemoveName },
				fix(fixer) {
					const nodeToRemove = preferredMethod === "default" ? optionalMethod.node : defaultMethod.node;
					const calleeToRemove = nodeToRemove.callee;
					return fixer.replaceText(nodeToRemove, sourceCode.getText(calleeToRemove.object));
				}
			});
		} });
	}
});
//#endregion
export { noOptionalAndDefaultTogether };
