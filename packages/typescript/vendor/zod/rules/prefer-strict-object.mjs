import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildPreferDedicatedFactoryCreate } from "../../zod-utils/rule-patterns/prefer-dedicated-factory.mjs";
//#region src/rules/prefer-strict-object.ts
const preferStrictObject = createZodPluginRule({
	name: "prefer-strict-object",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: { description: "Prefer `z.strictObject()` over `z.object().strict()`" },
		messages: { preferStrictObject: "Use `z.strictObject()` instead of `.strict()`." },
		schema: []
	},
	defaultOptions: [],
	create: buildPreferDedicatedFactoryCreate({
		scope: zodImportScope,
		factoryName: "object",
		modifierMethods: ["strict"],
		replacementFactoryName: "strictObject",
		messageId: "preferStrictObject"
	})
});
//#endregion
export { preferStrictObject };
