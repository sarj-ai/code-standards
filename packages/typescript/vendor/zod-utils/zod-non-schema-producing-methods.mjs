//#region src/zod-non-schema-producing-methods.ts
/**
* Zod method names that consume a schema rather than return a new one — parse
* methods, validation predicates, codec helpers, and error formatters. Useful
* for filtering out terminal calls when traversing a chain (e.g. to detect the
* last "schema-shaped" node in `z.string().parse(input)`).
*/
const ZOD_NON_SCHEMA_PRODUCING_METHODS = Object.freeze([
	"parse",
	"parseAsync",
	"safeParse",
	"safeParseAsync",
	"spa",
	"encode",
	"encodeAsync",
	"decode",
	"decodeAsync",
	"safeEncode",
	"safeEncodeAsync",
	"safeDecode",
	"safeDecodeAsync",
	"validate",
	"validateAsync",
	"codec",
	"treeifyError",
	"prettifyError",
	"formatError",
	"flattenError"
]);
//#endregion
export { ZOD_NON_SCHEMA_PRODUCING_METHODS };
