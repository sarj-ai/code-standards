import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildCollapseEqualBoundsCreate } from "../../zod-utils/rule-patterns/collapse-equal-bounds.mjs";
//#region src/rules/prefer-string-length-over-min-max.ts
const preferStringLengthOverMinMax = createZodPluginRule({
	name: "prefer-string-length-over-min-max",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: { description: "Prefer `.length(n)` over `.min(n).max(n)` with the same value on a string schema" },
		messages: { preferStringLength: "Use `.length(n)` instead of `.min(n)` and `.max(n)` with the same value." },
		schema: []
	},
	defaultOptions: [],
	create: buildCollapseEqualBoundsCreate({
		scope: zodImportScope,
		baseTypes: ["string"],
		domain: "length",
		messageId: "preferStringLength"
	})
});
//#endregion
export { preferStringLengthOverMinMax };
