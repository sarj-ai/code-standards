import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildPreferTupleOverArrayLengthCreate } from "../../zod-utils/rule-builders/prefer-tuple-over-array-length.mjs";
//#region src/rules/prefer-tuple-over-array-length.ts
const preferTupleOverArrayLength = createZodPluginRule({
	name: "prefer-tuple-over-array-length",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: { description: "Prefer `z.tuple()` over a length-constrained `z.array()` so the length is preserved in the inferred type." },
		messages: { preferTuple: "Prefer `z.tuple()` over a length-constrained `z.array()` so the length is preserved in the inferred type." },
		schema: []
	},
	defaultOptions: [],
	create: buildPreferTupleOverArrayLengthCreate(zodImportScope)
});
//#endregion
export { preferTupleOverArrayLength };
