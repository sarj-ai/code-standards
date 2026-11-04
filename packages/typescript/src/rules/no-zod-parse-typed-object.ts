/**
 * @fileoverview no-zod-parse-typed-object — keep runtime parsing at unknown-data boundaries.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-zod-parse-typed-object.test.ts
 */

import { ASTUtils, AST_NODE_TYPES } from "@typescript-eslint/utils";
import { isTupleTypeReference } from "ts-api-utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { getTypeServices } from "./_eslint-rule.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";
import { unwrapExpression } from "./_unwrap-expression.js";

const PARSE_METHODS: ReadonlySet<string> = new Set(["parse", "parseAsync", "safeParse", "safeParseAsync"]);
const OPAQUE_FLAGS = ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.Never |
  ts.TypeFlags.TypeParameter | ts.TypeFlags.Conditional | ts.TypeFlags.IndexedAccess |
  ts.TypeFlags.Intersection | ts.TypeFlags.NonPrimitive;

export const NO_ZOD_PARSE_TYPED_OBJECT_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Reuse known object contracts instead of parsing them again with Zod.",
  rationale: "Parsing a typed service result duplicates its object contract and adds runtime validation and copying throughout trusted application code. Validate unknown data once at its boundary.",
  remediation: "Use the typed value directly. If defaults or normalization are needed, express that mapping explicitly. Keep untrusted boundary data unknown until it is validated.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Requires type information, strict null checks, and a native installed Zod parse, parseAsync, safeParse or safeParseAsync signature. Recognizes imported schemas, aliases, member access and awaited service results without guessing from names.",
    "Reports fully known object or array inputs assignable to the schema input, when schema input and output have the same value shape. Optional-to-required defaults are included; type-changing transforms, coercions, brands, incompatible contracts, primitive roots and nested any/unknown/generic contracts are excluded.",
    "Static types do not establish runtime trust or prove refinements and normalization redundant. This is an architectural warning with no automatic removal. Keep intentional validation at an unknown-data boundary or document an exact local suppression. Tests, stories and generated code are excluded.",
    "Shape comparison ignores undefined introduced by optional properties and checks tuple element types and rest positions. It is bounded to 128 object pairs, visited input objects, properties, tuple elements or primitive union alternatives; object unions have at most 16 alternatives. Opaque or larger graphs are conservatively excluded.",
  ],
  references: ["https://zod.dev/basics"],
  examples: [
    { id: "imported-schema-alias", title: "Imported schema names do not establish a new boundary", outcome: "match", files: [{ path: "src/schema.ts", source: 'import { z } from "zod"; export const RowSchema = z.object({ id: z.string() });' }, { path: "src/value.ts", source: 'import { RowSchema as schema } from "./schema.js"; export function read(row: { id: string }) { return schema.safeParse(row); }' }], focusPath: "src/value.ts", expectedCount: 1, public: false, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
    { id: "unknown-boundary", title: "Validate unknown data once", outcome: "no-match", files: [{ path: "src/value.ts", source: 'import { z } from "zod"; const RowSchema = z.object({ id: z.string() }); export function read(raw: unknown) { return RowSchema.parse(raw); }' }], focusPath: "src/value.ts", expectedCount: 0, public: true, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
    { id: "typed-service-result", title: "Reuse the typed service response", outcome: "match", files: [{ path: "src/value.ts", source: 'import { z } from "zod"; const RowSchema = z.object({ id: z.string() }); declare function load(): Promise<{ id: string }>; export async function read() { return RowSchema.parse(await load()); }' }], focusPath: "src/value.ts", expectedCount: 1, public: true, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
    { id: "typed-result-with-default", title: "Make a typed response default explicit", outcome: "match", files: [{ path: "src/value.ts", source: 'import { z } from "zod"; const RowSchema = z.object({ id: z.string(), enabled: z.boolean().default(false) }); declare function load(): Promise<{ id: string; enabled?: boolean }>; export async function read() { return RowSchema.parse(await load()); }' }], focusPath: "src/value.ts", expectedCount: 1, public: false, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], "typedObject">({
  name: "no-zod-parse-typed-object",
  documentation: NO_ZOD_PARSE_TYPED_OBJECT_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_ZOD_PARSE_TYPED_OBJECT_DOCUMENTATION.summary },
    schema: [],
    messages: { typedObject: "This object already has a compatible TypeScript contract. Reuse the typed value and make defaults or normalization explicit; reserve Zod parsing for unknown boundary data." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text) || isTestFile(context) || isStoryFile(context) || !context.sourceCode.parserServices?.program) return {};
    const services = getTypeServices(context);
    const checker = services.program.getTypeChecker();
    const options = services.program.getCompilerOptions();
    if (!(options.strictNullChecks ?? options.strict ?? false)) return {};
    return {
      CallExpression(node): void {
        const callee = unwrapExpression(node.callee);
        const argument = node.arguments[0];
        if (node.optional || argument === undefined || argument.type === AST_NODE_TYPES.SpreadElement ||
          callee.type !== AST_NODE_TYPES.MemberExpression || callee.optional || !PARSE_METHODS.has(ASTUtils.getPropertyName(callee) ?? "")) return;
        const call = services.esTreeNodeToTSNodeMap.get(node);
        const declaration = checker.getResolvedSignature(call)?.declaration?.getSourceFile();
        if (declaration?.isDeclarationFile !== true || !declaration.fileName.replaceAll("\\", "/").includes("/node_modules/zod/")) return;
        const value = services.esTreeNodeToTSNodeMap.get(unwrapExpression(argument));
        const actual = checker.getTypeAtLocation(value);
        const roots = actual.isUnion() ? actual.types : [actual];
        if (!roots.every(type => (type.flags & ts.TypeFlags.Object) !== 0) || !knownValue(checker, actual, value, new Set())) return;
        const receiver = services.esTreeNodeToTSNodeMap.get(callee.object);
        const schema = checker.getTypeAtLocation(receiver);
        const internals = schema.getProperty("_zod");
        const contracts = internals === undefined ? schema : checker.getTypeOfSymbolAtLocation(internals, receiver);
        const input = contracts.getProperty(internals === undefined ? "_input" : "input");
        const output = contracts.getProperty(internals === undefined ? "_output" : "output");
        if (input === undefined || output === undefined) return;
        const inputType = checker.getTypeOfSymbolAtLocation(input, receiver);
        const outputType = checker.getTypeOfSymbolAtLocation(output, receiver);
        if (!checker.isTypeAssignableTo(actual, inputType) || !sameShape(checker, inputType, outputType, receiver)) return;
        context.report({ node, messageId: "typedObject" });
      },
    };
  },
});

function knownValue(checker: ts.TypeChecker, type: ts.Type, location: ts.Node, seen: Set<ts.Type>): boolean {
  if ((type.flags & OPAQUE_FLAGS) !== 0) return false;
  if (type.isUnion()) return type.types.every(member => knownValue(checker, member, location, seen));
  if ((type.flags & ts.TypeFlags.Object) === 0) return true;
  if (seen.has(type)) return true;
  if (seen.size >= 128 || type.getCallSignatures().length > 0 || type.getConstructSignatures().length > 0) return false;
  seen.add(type);
  if (isTupleTypeReference(type)) {
    const elements = checker.getTypeArguments(type);
    return elements.length <= 128 && elements.every(element => knownValue(checker, element, location, seen));
  }
  if (checker.isArrayType(type)) {
    const element = type.getNumberIndexType();
    return element !== undefined && knownValue(checker, element, location, seen);
  }
  const properties = type.getProperties();
  const indexes = checker.getIndexInfosOfType(type);
  return properties.length + indexes.length > 0 && properties.length <= 128 &&
    properties.every(property => knownValue(checker, checker.getTypeOfSymbolAtLocation(property, location), location, seen)) &&
    indexes.every(index => knownValue(checker, index.type, location, seen));
}

function sameShape(checker: ts.TypeChecker, input: ts.Type, output: ts.Type, location: ts.Node): boolean {
  let remaining = 128;
  const pairs = new Map<ts.Type, Map<ts.Type, boolean>>();
  function compare(left: ts.Type, right: ts.Type): boolean {
    if (((left.flags | right.flags) & OPAQUE_FLAGS) !== 0) return false;
    if (left.isUnion() || right.isUnion()) {
      const a = (left.isUnion() ? left.types : [left]).filter(member => (member.flags & ts.TypeFlags.Undefined) === 0);
      const b = (right.isUnion() ? right.types : [right]).filter(member => (member.flags & ts.TypeFlags.Undefined) === 0);
      const limit = [...a, ...b].every(member => (member.flags & (ts.TypeFlags.Object | OPAQUE_FLAGS)) === 0) ? 128 : 16;
      return a.length > 0 && a.length === b.length && a.length <= limit &&
        a.every(member => b.some(other => compare(member, other))) &&
        b.every(member => a.some(other => compare(other, member)));
    }
    if ((left.flags & ts.TypeFlags.Object) === 0 || (right.flags & ts.TypeFlags.Object) === 0) {
      return checker.isTypeAssignableTo(left, right) && checker.isTypeAssignableTo(right, left);
    }
    const previous = pairs.get(left)?.get(right);
    if (previous !== undefined) return previous;
    if (remaining-- <= 0 || left.getCallSignatures().length > 0 || right.getCallSignatures().length > 0) return false;
    const matches = pairs.get(left) ?? new Map<ts.Type, boolean>();
    matches.set(right, true);
    pairs.set(left, matches);
    const result = sameObjectShape(left, right);
    matches.set(right, result);
    return result;
  }

  function sameObjectShape(left: ts.Type, right: ts.Type): boolean {
    const leftTuple = checker.isTupleType(left);
    const rightTuple = checker.isTupleType(right);
    if (leftTuple || rightTuple) return leftTuple && rightTuple && sameTuplePositions(left, right);
    if (checker.isArrayType(left)) {
      if (!checker.isArrayType(right)) return false;
      const a = left.getNumberIndexType();
      const b = right.getNumberIndexType();
      return a !== undefined && b !== undefined && compare(a, b);
    }
    const properties = left.getProperties();
    if (properties.length !== right.getProperties().length || properties.length > 128) return false;
    for (const property of properties) {
      const other = right.getProperty(property.name);
      if (other === undefined || !compare(checker.getTypeOfSymbolAtLocation(property, location), checker.getTypeOfSymbolAtLocation(other, location))) return false;
    }
    const a = checker.getIndexInfosOfType(left);
    const b = checker.getIndexInfosOfType(right);
    return a.length === b.length && a.every(index => b.some(other =>
      checker.isTypeAssignableTo(index.keyType, other.keyType) && checker.isTypeAssignableTo(other.keyType, index.keyType) &&
      compare(index.type, other.type)));
  }

  function sameTuplePositions(left: ts.Type, right: ts.Type): boolean {
    if (!isTupleTypeReference(left) || !isTupleTypeReference(right)) return false;
    const a = checker.getTypeArguments(left);
    const b = checker.getTypeArguments(right);
    const flags = right.target.elementFlags;
    return a.length <= 128 && a.length === b.length && left.target.elementFlags.every((flag, index) => flag === flags[index]) && a.every((element, index) => {
      const other = b[index];
      return other !== undefined && compare(element, other);
    });
  }

  return compare(input, output);
}
