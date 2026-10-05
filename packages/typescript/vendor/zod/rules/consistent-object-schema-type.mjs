import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildConsistentObjectSchemaTypeCreate } from "../../zod-utils/rule-builders/consistent-object-schema-type.mjs";
//#region src/rules/consistent-object-schema-type.ts
const ZOD_OBJECT_METHODS = [
	"object",
	"looseObject",
	"strictObject"
];
const defaultOptions = { allow: ["object"] };
const consistentObjectSchemaType = createZodPluginRule({
	name: "consistent-object-schema-type",
	meta: {
		hasSuggestions: true,
		type: "suggestion",
		docs: { description: "Enforce consistent usage of Zod schema methods" },
		messages: {
			consistentMethod: "Inconsistent Zod object schema method '{{actual}}'. Allowed: {{allowedList}}.",
			useMethod: "Replace with '{{expected}}'."
		},
		schema: [{
			type: "object",
			properties: { allow: {
				type: "array",
				description: "Decides which object methods are allowed",
				items: {
					type: "string",
					enum: [...ZOD_OBJECT_METHODS]
				},
				minItems: 1,
				uniqueItems: true
			} },
			additionalProperties: false
		}]
	},
	defaultOptions: [defaultOptions],
	create: buildConsistentObjectSchemaTypeCreate(zodImportScope)
});
//#endregion
export { consistentObjectSchemaType };
