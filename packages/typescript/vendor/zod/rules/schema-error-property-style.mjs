import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildSchemaErrorPropertyStyleCreate } from "../../zod-utils/rule-builders/schema-error-property-style.mjs";
//#region src/rules/schema-error-property-style.ts
const schemaErrorPropertyStyle = createZodPluginRule({
	name: "schema-error-property-style",
	meta: {
		type: "suggestion",
		docs: { description: "Enforce consistent style for error messages in Zod schema validation (using ESQuery patterns)" },
		messages: {
			invalidSelector: "Invalid ESQuery selector: \"{{selector}}\"",
			invalidStyle: "Error message must follow the pattern \"{{selector}}\" (e.g., {{example}}). Found: {{actual}}."
		},
		schema: [{
			type: "object",
			properties: {
				selector: {
					description: "An ESQuery string to match the required pattern",
					type: "string"
				},
				example: {
					description: "Example code to help the user understand the required pattern",
					type: "string"
				}
			},
			additionalProperties: false
		}]
	},
	defaultOptions: [{
		selector: "Literal,TemplateLiteral",
		example: "'error message'"
	}],
	create: buildSchemaErrorPropertyStyleCreate(zodImportScope)
});
//#endregion
export { schemaErrorPropertyStyle };
