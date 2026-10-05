import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildConsistentImportSourceCreate } from "../../zod-utils/rule-builders/consistent-import-source.mjs";
//#region src/rules/consistent-import-source.ts
const consistentImportSource = createZodPluginRule({
	name: "consistent-import-source",
	meta: {
		hasSuggestions: true,
		type: "suggestion",
		docs: { description: "Enforce consistent source from Zod imports" },
		messages: {
			sourceNotAllowed: "\"{{source}}\" is not allowed. Available values are: {{sources}}",
			replaceSource: "Replace \"{{invalid}}\" with \"{{valid}}\""
		},
		schema: [{
			type: "object",
			properties: { sources: {
				type: "array",
				description: "An array of allowed Zod import sources.",
				items: {
					type: "string",
					enum: [...zodImportScope.sources]
				},
				minItems: 1,
				uniqueItems: true
			} },
			additionalProperties: false
		}]
	},
	defaultOptions: [{ sources: ["zod"] }],
	create: buildConsistentImportSourceCreate(zodImportScope)
});
//#endregion
export { consistentImportSource };
