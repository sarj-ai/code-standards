import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { ZOD_MUTATING_CHECK_NAMES, zodImportScope } from "../../zod-utils/index.mjs";
import { buildNoTransformInRecordKeyCreate } from "../../zod-utils/rule-builders/no-transform-in-record-key.mjs";
//#region src/rules/no-transform-in-record-key.ts
const TRANSFORM_METHODS = [
	...ZOD_MUTATING_CHECK_NAMES,
	"transform",
	"map"
];
const noTransformInRecordKey = createZodPluginRule({
	name: "no-transform-in-record-key",
	meta: {
		type: "problem",
		docs: { description: "Disallow transforms in z.record() key schemas, which can cause silent key mutations and data loss through key collisions" },
		messages: { noTransformInRecordKey: "Transforms in z.record() key schemas cause silent key mutation and potential data loss. Use validators like .min() instead of transforms like .trim() or .toLowerCase()" },
		schema: []
	},
	defaultOptions: [],
	create: buildNoTransformInRecordKeyCreate(zodImportScope, TRANSFORM_METHODS)
});
//#endregion
export { noTransformInRecordKey };
