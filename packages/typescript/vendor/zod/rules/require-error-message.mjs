import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildRequireErrorMessageCreate } from "../../zod-utils/rule-builders/require-error-message.mjs";
//#region src/rules/require-error-message.ts
const requireErrorMessage = createZodPluginRule({
	name: "require-error-message",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: { description: "Enforce that custom refinements include an error message" },
		messages: {
			requireErrorMessage: "Custom refinements must include an error message",
			preferError: "Use the \"error\" property instead of the deprecated \"message\" property",
			removeMessage: "The \"message\" property is deprecated; use \"error\""
		},
		schema: []
	},
	defaultOptions: [],
	create: buildRequireErrorMessageCreate(zodImportScope)
});
//#endregion
export { requireErrorMessage };
