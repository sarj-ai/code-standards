import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildRequireBrandTypeParameterCreate } from "../../zod-utils/rule-builders/require-brand-type-parameter.mjs";
//#region src/rules/require-brand-type-parameter.ts
const requireBrandTypeParameter = createZodPluginRule({
	name: "require-brand-type-parameter",
	meta: {
		hasSuggestions: true,
		type: "problem",
		docs: { description: "Require type parameter on `.brand()` functions" },
		messages: {
			missingTypeParameter: "Type parameter is required when using `.brand()`",
			removeBrandFunction: "Brand is a static-only construct. If not parameter is required consider removal"
		},
		schema: []
	},
	defaultOptions: [],
	create: buildRequireBrandTypeParameterCreate(zodImportScope)
});
//#endregion
export { requireBrandTypeParameter };
