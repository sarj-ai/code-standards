/**
 * @fileoverview no-invalid-zod-custom-parse — an unchecked custom parser must not fabricate an incompatible primitive contract.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-invalid-zod-custom-parse.test.ts
 */
import { ASTUtils, AST_NODE_TYPES, ESLintUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import { isBigIntLiteralType, isBooleanLiteralType, isNumberLiteralType, isStringLiteralType } from "ts-api-utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { importSpecifierName } from "./_import-specifier-name.js";
import { isGeneratedFile } from "./_paths.js";
import { unwrapExpression } from "./_unwrap-expression.js";

type Primitive = string | number | bigint | boolean | null;
type ImportKind = "custom" | "namespace";

export const NO_INVALID_ZOD_CUSTOM_PARSE_DOCUMENTATION = {
  summary: "Do not parse an incompatible primitive literal through an unvalidated Zod custom schema.",
  rationale: "Without a validator, z.custom<T>() returns its input unchanged while promising T. A parsed primitive outside that value domain fabricates a contract the caller may trust.",
  remediation: "Provide actual validation, use the appropriate primitive schema, or retain an honest unknown result until validation. Preserve composed validators and independently owned domain contracts.",
  category: "correctness",
  defaultLevel: "warning",
  autofix: "none",
  limitations: [
    "Requires type information and a direct inline z.custom<T>().parse(primitiveLiteral) call with no custom validator or parse options. Recognizes runtime imports from zod or zod/v4 and native installed Zod v4 declarations; schema bindings, compositions, safeParse, dynamic inputs and indirect calls are excluded.",
    "Targets must be broad primitives, finite unbranded primitive/nullish literal unions, or never. Any, unknown, void, object, enum, branded, intersection, generic and opaque targets are preserved. Membership is checked by primitive value, not nominal assignability. Null input requires strictNullChecks.",
    "The import binding must be used only by direct custom calls or type-only references. Other namespace uses, aliases, exports, mutation and escapes conservatively disable the proof for that binding. Generated files are excluded; tests remain checked. No autofix is offered.",
  ],
  references: ["https://zod.dev/api#custom"],
  examples: [
    { id: "validated-string", title: "Validate a primitive at the boundary", outcome: "no-match", files: [{ path: "src/value.ts", source: 'import { z } from "zod"; const value = z.custom<string>(value => typeof value === "string").parse(1);' }], focusPath: "src/value.ts", expectedCount: 0, public: true, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
    { id: "fabricated-string", title: "An unchecked parser returns the number unchanged", outcome: "match", files: [{ path: "src/value.ts", source: 'import { z } from "zod"; const value = z.custom<string>().parse(1);' }], focusPath: "src/value.ts", expectedCount: 1, public: true, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], "incompatibleCustomParse">({
  name: "no-invalid-zod-custom-parse",
  documentation: NO_INVALID_ZOD_CUSTOM_PARSE_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_INVALID_ZOD_CUSTOM_PARSE_DOCUMENTATION.summary },
    schema: [],
    messages: { incompatibleCustomParse: "This unvalidated z.custom parser returns the literal unchanged, outside its promised `{{target}}` domain. Validate the value or preserve an honest unknown contract." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text) || !context.sourceCode.parserServices?.program) return {};
    const services = ESLintUtils.getParserServices(context);
    const checker = services.program.getTypeChecker();
    const options = services.program.getCompilerOptions();
    return {
      CallExpression(node): void {
        const custom = inlineCustom(node);
        const argument = node.arguments[0];
        if (custom === undefined || argument === undefined || !ownedCustom(custom, context.sourceCode)) return;
        const value = primitiveLiteral(argument);
        if (value === undefined || (value === null && !(options.strictNullChecks ?? options.strict ?? false))) return;
        if (!nativeZodDeclaration(checker.getResolvedSignature(services.esTreeNodeToTSNodeMap.get(custom))) ||
          !nativeZodDeclaration(checker.getResolvedSignature(services.esTreeNodeToTSNodeMap.get(node)))) return;
        const target = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node));
        if (!primitiveDomain(target) || acceptsPrimitive(target, value)) return;
        context.report({ node, messageId: "incompatibleCustomParse", data: { target: checker.typeToString(target) } });
      },
    };
  },
});

function inlineCustom(node: TSESTree.CallExpression): TSESTree.CallExpression | undefined {
  const callee = unwrapExpression(node.callee);
  if (node.optional || node.arguments.length !== 1 || callee.type !== AST_NODE_TYPES.MemberExpression || callee.optional || ASTUtils.getPropertyName(callee) !== "parse") return undefined;
  const custom = unwrapExpression(callee.object);
  return custom.type === AST_NODE_TYPES.CallExpression && !custom.optional && custom.arguments.length === 0 && custom.typeArguments?.params.length === 1 ? custom : undefined;
}

function ownedCustom(node: TSESTree.CallExpression, sourceCode: TSESLint.SourceCode): boolean {
  const callee = unwrapExpression(node.callee);
  const identifier = callee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(callee.object) : callee;
  if (identifier.type !== AST_NODE_TYPES.Identifier) return false;
  const variable = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
  if (variable?.defs.length !== 1) return false;
  const definition = variable.defs[0];
  if (definition?.type !== "ImportBinding") return false;
  const declaration = definition.parent;
  if (declaration?.type !== AST_NODE_TYPES.ImportDeclaration || declaration.importKind === "type" || !["zod", "zod/v4"].includes(declaration.source.value)) return false;
  const kind = customImportKind(definition.node);
  if (kind === undefined || (kind === "namespace" && (callee.type !== AST_NODE_TYPES.MemberExpression || ASTUtils.getPropertyName(callee) !== "custom"))) return false;
  if (kind === "custom" && callee !== identifier) return false;
  return variable.references.every((reference) => (reference.isTypeReference && !reference.isValueReference) || directCustomUse(reference.identifier, kind));
}

function customImportKind(node: TSESTree.Node): ImportKind | undefined {
  if (node.type === AST_NODE_TYPES.ImportNamespaceSpecifier || node.type === AST_NODE_TYPES.ImportDefaultSpecifier) return "namespace";
  if (node.type !== AST_NODE_TYPES.ImportSpecifier || node.importKind === "type") return undefined;
  const name = importSpecifierName(node);
  return name === "custom" ? "custom" : name === "z" ? "namespace" : undefined;
}

function directCustomUse(identifier: TSESTree.Node, kind: ImportKind): boolean {
  const callee = kind === "namespace" ? identifier.parent : identifier;
  if (callee === undefined) return false;
  if (kind === "namespace" && (callee.type !== AST_NODE_TYPES.MemberExpression || callee.object !== identifier || callee.optional || ASTUtils.getPropertyName(callee) !== "custom")) return false;
  return callee.parent?.type === AST_NODE_TYPES.CallExpression && callee.parent.callee === callee && !callee.parent.optional;
}

function nativeZodDeclaration(signature: ts.Signature | undefined): boolean {
  const source = signature?.declaration?.getSourceFile();
  return source?.isDeclarationFile === true && source.fileName.replaceAll("\\", "/").includes("/node_modules/zod/v4/");
}

function primitiveDomain(type: ts.Type): boolean {
  if (type.isUnion()) return type.types.every(primitiveDomain);
  if ((type.flags & (ts.TypeFlags.Enum | ts.TypeFlags.EnumLiteral)) !== 0) return false;
  const flags = ts.TypeFlags.String | ts.TypeFlags.Number | ts.TypeFlags.BigInt | ts.TypeFlags.BooleanLiteral |
    ts.TypeFlags.StringLiteral | ts.TypeFlags.NumberLiteral | ts.TypeFlags.BigIntLiteral | ts.TypeFlags.Null | ts.TypeFlags.Undefined | ts.TypeFlags.Never;
  return (type.flags & flags) !== 0;
}

function acceptsPrimitive(type: ts.Type, value: Primitive): boolean {
  if (type.isUnion()) return type.types.some((member) => acceptsPrimitive(member, value));
  if (value === null) return (type.flags & ts.TypeFlags.Null) !== 0;
  if (typeof value === "string") return (type.flags & ts.TypeFlags.String) !== 0 || (isStringLiteralType(type) && type.value === value);
  if (typeof value === "number") return (type.flags & ts.TypeFlags.Number) !== 0 || (isNumberLiteralType(type) && type.value === value);
  if (typeof value === "boolean") return isBooleanLiteralType(type) && type.intrinsicName === String(value);
  return (type.flags & ts.TypeFlags.BigInt) !== 0 || (isBigIntLiteralType(type) && bigintValue(type) === value);
}

function bigintValue(type: ts.BigIntLiteralType): bigint {
  return BigInt(`${type.value.negative ? "-" : ""}${type.value.base10Value}`);
}

function primitiveLiteral(node: TSESTree.Node): Primitive | undefined {
  const value = unwrapExpression(node);
  if (value.type === AST_NODE_TYPES.Literal && (value.value === null || typeof value.value === "string" ||
    typeof value.value === "number" || typeof value.value === "bigint" || typeof value.value === "boolean")) return value.value;
  if (value.type !== AST_NODE_TYPES.UnaryExpression || (value.operator !== "-" && value.operator !== "+")) return undefined;
  const operand = unwrapExpression(value.argument);
  if (operand.type !== AST_NODE_TYPES.Literal) return undefined;
  if (typeof operand.value === "number") return value.operator === "-" ? -operand.value : operand.value;
  return typeof operand.value === "bigint" && value.operator === "-" ? -operand.value : undefined;
}
