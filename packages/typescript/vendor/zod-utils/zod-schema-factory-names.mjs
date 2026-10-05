import { getZodChainedMethodNames } from "./get-zod-chained-method-names.mjs";
import { ZOD_BASE_TYPE_NAMES } from "./get-zod-schema-base-type.mjs";
//#region src/zod-schema-factory-names.ts
/**
* Every top-level Zod export whose call evaluates to a schema, across API styles.
* `iso` and `coerce` are absent: only their members are called.
* Builds on {@link ZOD_BASE_TYPE_NAMES} rather than restating it.
*/
const ZOD_SCHEMA_FACTORY_NAMES = Object.freeze([
	...ZOD_BASE_TYPE_NAMES.filter((name) => name !== "iso"),
	"nan",
	"null",
	"symbol",
	"undefined",
	"void",
	"currencyCode",
	"stringFormat",
	"file",
	"looseRecord",
	"partialRecord",
	"record",
	"tuple",
	"discriminatedUnion",
	"enum",
	"intersection",
	"keyof",
	"nativeEnum",
	"templateLiteral",
	"union",
	"xor",
	"catch",
	"default",
	"exactOptional",
	"lazy",
	"nonoptional",
	"nullable",
	"nullish",
	"optional",
	"prefault",
	"promise",
	"readonly",
	"success",
	"codec",
	"invertCodec",
	"pipe",
	"preprocess",
	"transform",
	"catchall",
	"exactPartial",
	"extend",
	"merge",
	"omit",
	"partial",
	"pick",
	"required",
	"safeExtend",
	"custom",
	"fromJSONSchema",
	"function",
	"instanceof",
	"json"
]);
const FACTORY_NAMES = new Set(ZOD_SCHEMA_FACTORY_NAMES);
/** True when `name` is a top-level Zod factory whose call evaluates to a schema. */
function isZodSchemaFactoryName(name) {
	return FACTORY_NAMES.has(name);
}
/** Namespaces on `z` that are never called themselves — their members are the factories. */
const FACTORY_NAMESPACES = /* @__PURE__ */ new Set(["iso", "coerce"]);
/**
* True when a detected chain evaluates to a schema, i.e. its factory builds one.
* Use it to keep a rule off the top-level helpers that merely consume a schema
* (`z.toJSONSchema(schema)`, `z.prettifyError(err)`), which detection reports like any other call.
*/
function isZodSchemaFactoryCall(meta) {
	return FACTORY_NAMESPACES.has(meta.schemaType) ? getZodChainedMethodNames(meta).length > 0 : isZodSchemaFactoryName(meta.schemaType);
}
//#endregion
export { ZOD_SCHEMA_FACTORY_NAMES, isZodSchemaFactoryCall, isZodSchemaFactoryName };
