import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildConsistentSchemaVarNameCreate } from "../../zod-utils/rule-builders/consistent-schema-var-name.mjs";
//#region src/rules/consistent-schema-var-name.ts
const consistentSchemaVarName = createZodPluginRule({
	name: "consistent-schema-var-name",
	meta: {
		type: "suggestion",
		docs: { description: "Enforce a consistent naming convention for Zod schema variables" },
		messages: { invalidName: "Rename this Zod schema to \"{{expected}}\"" },
		schema: [{
			type: "object",
			properties: {
				before: {
					type: "string",
					description: "The required prefix for Zod schema variables"
				},
				after: {
					type: "string",
					description: "The required suffix for Zod schema variables"
				}
			},
			additionalProperties: false
		}]
	},
	defaultOptions: [{ after: "Schema" }],
	create: buildConsistentSchemaVarNameCreate(zodImportScope)
});
//#endregion
export { consistentSchemaVarName };
