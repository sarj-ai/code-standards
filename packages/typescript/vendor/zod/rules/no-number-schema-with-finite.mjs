import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { buildZodChainRemoveMethodFix, getZodChainedMethodNames, zodImportScope } from "../../zod-utils/index.mjs";
//#region src/rules/no-number-schema-with-finite.ts
const noNumberSchemaWithFinite = createZodPluginRule({
	name: "no-number-schema-with-finite",
	meta: {
		fixable: "code",
		type: "problem",
		docs: { description: "Disallow deprecated `z.number().finite()`. In Zod 4+ number schemas do not allow infinite values by default, so it is a no-op." },
		messages: { removeFinite: "`.finite()` is deprecated. In Zod 4+ `z.number()` does not allow infinite values by default. Remove this call." },
		schema: []
	},
	defaultOptions: [],
	create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = zodImportScope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "number",
			onSchema(node, zodSchemaMeta) {
				if (!getZodChainedMethodNames(zodSchemaMeta).includes("finite")) return;
				const methods = collectZodChainMethods(node);
				const finiteIndex = methods.findIndex((m, index) => index > 0 && m.name === "finite");
				context.report({
					node,
					messageId: "removeFinite",
					fix(fixer) {
						if (finiteIndex === -1) return null;
						return buildZodChainRemoveMethodFix({
							fixer,
							methods,
							removeIndex: finiteIndex
						});
					}
				});
			}
		});
	}
});
//#endregion
export { noNumberSchemaWithFinite };
