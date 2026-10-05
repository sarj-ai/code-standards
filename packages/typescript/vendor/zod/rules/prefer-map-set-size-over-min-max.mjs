import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildCollapseEqualBoundsCreate } from "../../zod-utils/rule-patterns/collapse-equal-bounds.mjs";
//#region src/rules/prefer-map-set-size-over-min-max.ts
const preferMapSetSizeOverMinMax = createZodPluginRule({
	name: "prefer-map-set-size-over-min-max",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: { description: "Prefer `.size(n)` over `.min(n).max(n)` with the same value on a set or map schema" },
		messages: { preferMapSetSize: "Use `.size(n)` instead of `.min(n)` and `.max(n)` with the same value." },
		schema: []
	},
	defaultOptions: [],
	create: buildCollapseEqualBoundsCreate({
		scope: zodImportScope,
		baseTypes: ["set", "map"],
		domain: "size",
		messageId: "preferMapSetSize"
	})
});
//#endregion
export { preferMapSetSizeOverMinMax };
