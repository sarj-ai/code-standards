import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { ZOD_STRING_FORMAT_METHODS, zodImportScope } from "../../zod-utils/index.mjs";
import { buildPreferTopLevelFactoryCreate } from "../../zod-utils/rule-patterns/prefer-top-level-factory.mjs";
//#region src/rules/prefer-top-level-string-formats.ts
const TOP_LEVEL_STRING_FORMATS_URL = "https://zod.dev/v4?id=top-level-string-formats";
const ZOD_STRING_FORMAT_METHOD_NAMES = ZOD_STRING_FORMAT_METHODS.map(({ sourceMethodName }) => sourceMethodName);
const preferTopLevelStringFormats = createZodPluginRule({
	name: "prefer-top-level-string-formats",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: {
			description: "Prefer top-level string format schemas over deprecated `z.string().<format>()` methods",
			url: TOP_LEVEL_STRING_FORMATS_URL
		},
		messages: { preferTopLevelStringFormat: "Use `z.{{replacementMethod}}()` instead of `z.string().{{sourceMethod}}()`." },
		schema: [{
			type: "object",
			properties: { ignore: {
				type: "array",
				description: "Top-level string format methods to ignore for this rule.",
				items: {
					type: "string",
					enum: [...ZOD_STRING_FORMAT_METHOD_NAMES]
				},
				uniqueItems: true
			} },
			additionalProperties: false
		}]
	},
	defaultOptions: [{}],
	create(context, [{ ignore = [] }]) {
		return buildPreferTopLevelFactoryCreate({
			scope: zodImportScope,
			factoryName: "string",
			replacements: ZOD_STRING_FORMAT_METHODS,
			messageId: "preferTopLevelStringFormat",
			ignore
		})(context);
	}
});
//#endregion
export { preferTopLevelStringFormats };
