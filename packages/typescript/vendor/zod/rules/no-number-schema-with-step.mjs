import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { getZodChainedMethodNames, zodImportScope } from "../../zod-utils/index.mjs";
//#region src/rules/no-number-schema-with-step.ts
const noNumberSchemaWithStep = createZodPluginRule({
	name: "no-number-schema-with-step",
	meta: {
		fixable: "code",
		type: "problem",
		docs: { description: "Disallow deprecated `z.number().step()`. Use `.multipleOf()` instead." },
		messages: { useMultipleOf: "`.step()` is deprecated. Use `.multipleOf()` with the same argument instead." },
		schema: []
	},
	defaultOptions: [],
	create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = zodImportScope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "number",
			onSchema(node, zodSchemaMeta) {
				if (!getZodChainedMethodNames(zodSchemaMeta).includes("step")) return;
				const methods = collectZodChainMethods(node);
				const stepIndex = methods.findIndex((m, index) => index > 0 && m.name === "step");
				const property = stepIndex === -1 ? null : methods[stepIndex].node.callee.property;
				context.report({
					node,
					messageId: "useMultipleOf",
					fix(fixer) {
						return property === null ? null : fixer.replaceText(property, "multipleOf");
					}
				});
			}
		});
	}
});
//#endregion
export { noNumberSchemaWithStep };
