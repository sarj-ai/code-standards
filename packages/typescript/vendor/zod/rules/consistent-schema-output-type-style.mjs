import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildConsistentSchemaOutputTypeStyleCreate } from "../../zod-utils/rule-builders/consistent-schema-output-type-style.mjs";
const consistentSchemaOutputTypeStyle = createZodPluginRule({
	name: "consistent-schema-output-type-style",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: { description: "Enforce consistent use of z.infer or z.output for schema type inference" },
		messages: {
			useInfer: "Use infer instead of output.",
			useOutput: "Use output instead of infer."
		},
		schema: [{
			type: "object",
			properties: { style: {
				description: "Decides which style to use for schema type inference",
				type: "string",
				enum: [...["infer", "output"]]
			} },
			additionalProperties: false
		}]
	},
	defaultOptions: [{ style: "output" }],
	create: buildConsistentSchemaOutputTypeStyleCreate(zodImportScope)
});
//#endregion
export { consistentSchemaOutputTypeStyle };
