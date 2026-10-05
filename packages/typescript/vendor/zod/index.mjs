import { PLUGIN_NAME, PLUGIN_VERSION } from "./meta.mjs";
import { arrayStyle } from "./rules/array-style.mjs";
import { consistentImportSource } from "./rules/consistent-import-source.mjs";
import { consistentImport } from "./rules/consistent-import.mjs";
import { consistentObjectSchemaType } from "./rules/consistent-object-schema-type.mjs";
import { consistentSchemaOutputTypeStyle } from "./rules/consistent-schema-output-type-style.mjs";
import { consistentSchemaVarName } from "./rules/consistent-schema-var-name.mjs";
import { noAnySchema } from "./rules/no-any-schema.mjs";
import { noCoerceBoolean } from "./rules/no-coerce-boolean.mjs";
import { noConflictingChecks } from "./rules/no-conflicting-checks.mjs";
import { noDuplicateSchemaMethods } from "./rules/no-duplicate-schema-methods.mjs";
import { noDynamicSchemaValue } from "./rules/no-dynamic-schema-value.mjs";
import { noEmptyCustomSchema } from "./rules/no-empty-custom-schema.mjs";
import { noFunctionScopedSchema } from "./rules/no-function-scoped-schema.mjs";
import { noNativeEnum } from "./rules/no-native-enum.mjs";
import { noNumberSchemaWithFinite } from "./rules/no-number-schema-with-finite.mjs";
import { noNumberSchemaWithInt } from "./rules/no-number-schema-with-int.mjs";
import { noNumberSchemaWithIsFinite } from "./rules/no-number-schema-with-is-finite.mjs";
import { noNumberSchemaWithIsInt } from "./rules/no-number-schema-with-is-int.mjs";
import { noNumberSchemaWithSafe } from "./rules/no-number-schema-with-safe.mjs";
import { noNumberSchemaWithStep } from "./rules/no-number-schema-with-step.mjs";
import { noOptionalAndDefaultTogether } from "./rules/no-optional-and-default-together.mjs";
import { noPromiseSchema } from "./rules/no-promise-schema.mjs";
import { noSchemaWithIsNullable } from "./rules/no-schema-with-is-nullable.mjs";
import { noSchemaWithIsOptional } from "./rules/no-schema-with-is-optional.mjs";
import { noThrowInRefine } from "./rules/no-throw-in-refine.mjs";
import { noTransformInRecordKey } from "./rules/no-transform-in-record-key.mjs";
import { noUnknownSchema } from "./rules/no-unknown-schema.mjs";
import { noUnnecessaryReadonly } from "./rules/no-unnecessary-readonly.mjs";
import { preferEnumOverLiteralUnion } from "./rules/prefer-enum-over-literal-union.mjs";
import { preferLooseObject } from "./rules/prefer-loose-object.mjs";
import { preferMapSetSizeOverMinMax } from "./rules/prefer-map-set-size-over-min-max.mjs";
import { preferMetaLast } from "./rules/prefer-meta-last.mjs";
import { preferMeta } from "./rules/prefer-meta.mjs";
import { preferNullish } from "./rules/prefer-nullish.mjs";
import { preferStrictObject } from "./rules/prefer-strict-object.mjs";
import { preferStringLengthOverMinMax } from "./rules/prefer-string-length-over-min-max.mjs";
import { preferStringSchemaWithTrim } from "./rules/prefer-string-schema-with-trim.mjs";
import { preferTopLevelStringFormats } from "./rules/prefer-top-level-string-formats.mjs";
import { preferTrimBeforeStringLengthChecks } from "./rules/prefer-trim-before-string-length-checks.mjs";
import { preferTupleOverArrayLength } from "./rules/prefer-tuple-over-array-length.mjs";
import { preferValidate } from "./rules/prefer-validate.mjs";
import { requireBrandTypeParameter } from "./rules/require-brand-type-parameter.mjs";
import { requireErrorMessage } from "./rules/require-error-message.mjs";
import { schemaErrorPropertyStyle } from "./rules/schema-error-property-style.mjs";
//#region src/index.ts
const eslintPluginZod = {
	meta: {
		name: PLUGIN_NAME,
		version: PLUGIN_VERSION
	},
	rules: {
		"array-style": arrayStyle,
		"consistent-import-source": consistentImportSource,
		"consistent-import": consistentImport,
		"consistent-object-schema-type": consistentObjectSchemaType,
		"consistent-schema-var-name": consistentSchemaVarName,
		"consistent-schema-output-type-style": consistentSchemaOutputTypeStyle,
		"no-any-schema": noAnySchema,
		"no-coerce-boolean": noCoerceBoolean,
		"no-conflicting-checks": noConflictingChecks,
		"no-duplicate-schema-methods": noDuplicateSchemaMethods,
		"no-dynamic-schema-value": noDynamicSchemaValue,
		"no-empty-custom-schema": noEmptyCustomSchema,
		"no-function-scoped-schema": noFunctionScopedSchema,
		"no-native-enum": noNativeEnum,
		"no-number-schema-with-finite": noNumberSchemaWithFinite,
		"no-number-schema-with-int": noNumberSchemaWithInt,
		"no-number-schema-with-is-finite": noNumberSchemaWithIsFinite,
		"no-number-schema-with-is-int": noNumberSchemaWithIsInt,
		"no-number-schema-with-safe": noNumberSchemaWithSafe,
		"no-number-schema-with-step": noNumberSchemaWithStep,
		"no-optional-and-default-together": noOptionalAndDefaultTogether,
		"no-promise-schema": noPromiseSchema,
		"no-schema-with-is-nullable": noSchemaWithIsNullable,
		"no-schema-with-is-optional": noSchemaWithIsOptional,
		"no-throw-in-refine": noThrowInRefine,
		"no-transform-in-record-key": noTransformInRecordKey,
		"no-unknown-schema": noUnknownSchema,
		"no-unnecessary-readonly": noUnnecessaryReadonly,
		"prefer-enum-over-literal-union": preferEnumOverLiteralUnion,
		"prefer-loose-object": preferLooseObject,
		"prefer-map-set-size-over-min-max": preferMapSetSizeOverMinMax,
		"prefer-meta": preferMeta,
		"prefer-meta-last": preferMetaLast,
		"prefer-nullish": preferNullish,
		"prefer-strict-object": preferStrictObject,
		"prefer-string-length-over-min-max": preferStringLengthOverMinMax,
		"prefer-top-level-string-formats": preferTopLevelStringFormats,
		"prefer-string-schema-with-trim": preferStringSchemaWithTrim,
		"prefer-trim-before-string-length-checks": preferTrimBeforeStringLengthChecks,
		"prefer-tuple-over-array-length": preferTupleOverArrayLength,
		"prefer-validate": preferValidate,
		"require-brand-type-parameter": requireBrandTypeParameter,
		"require-error-message": requireErrorMessage,
		"schema-error-property-style": schemaErrorPropertyStyle
	}
};
function createConfig(name, rules) {
	return {
		name: `${PLUGIN_NAME}/${name}`,
		files: ["**/*.{js,mjs,cjs,jsx,mjsx,ts,tsx,mtsx}"],
		plugins: { zod: eslintPluginZod },
		rules
	};
}
const recommendedRules = {
	"zod/consistent-import": "error",
	"zod/consistent-schema-var-name": "error",
	"zod/no-any-schema": "error",
	"zod/no-coerce-boolean": "error",
	"zod/no-conflicting-checks": "error",
	"zod/no-duplicate-schema-methods": "error",
	"zod/no-empty-custom-schema": "error",
	"zod/no-native-enum": "error",
	"zod/no-number-schema-with-finite": "error",
	"zod/no-number-schema-with-int": "error",
	"zod/no-number-schema-with-is-finite": "error",
	"zod/no-number-schema-with-is-int": "error",
	"zod/no-number-schema-with-safe": "error",
	"zod/no-number-schema-with-step": "error",
	"zod/no-optional-and-default-together": "error",
	"zod/no-promise-schema": "error",
	"zod/no-schema-with-is-nullable": "error",
	"zod/no-schema-with-is-optional": "error",
	"zod/no-throw-in-refine": "error",
	"zod/no-transform-in-record-key": "error",
	"zod/prefer-top-level-string-formats": "error",
	"zod/require-brand-type-parameter": "error",
	"zod/require-error-message": "error"
};
const strictRules = {
	...recommendedRules,
	"zod/no-dynamic-schema-value": "error",
	"zod/no-function-scoped-schema": "error",
	"zod/no-unknown-schema": "error",
	"zod/no-unnecessary-readonly": "error",
	"zod/prefer-trim-before-string-length-checks": "error"
};
const stylisticRules = {
	"zod/array-style": "error",
	"zod/consistent-import-source": "error",
	"zod/consistent-object-schema-type": "error",
	"zod/consistent-schema-output-type-style": "error",
	"zod/prefer-enum-over-literal-union": "error",
	"zod/prefer-loose-object": "error",
	"zod/prefer-map-set-size-over-min-max": "error",
	"zod/prefer-meta": "error",
	"zod/prefer-meta-last": "error",
	"zod/prefer-nullish": "error",
	"zod/prefer-strict-object": "error",
	"zod/prefer-string-length-over-min-max": "error",
	"zod/prefer-string-schema-with-trim": "error",
	"zod/prefer-tuple-over-array-length": "error",
	"zod/prefer-validate": "error",
	"zod/schema-error-property-style": "error"
};
var src_default = {
	...eslintPluginZod,
	configs: {
		recommended: createConfig("recommended", recommendedRules),
		strict: createConfig("strict", strictRules),
		stylistic: createConfig("stylistic", stylisticRules),
		all: createConfig("all", {
			...strictRules,
			...stylisticRules
		})
	}
};
/**
* why `satisfies`?
* @see https://github.com/marcalexiei/eslint-zod/issues/49
*/
//#endregion
export { src_default as default };
