/**
 * @fileoverview no-invalid-zod-custom-parse — an unchecked custom parser must not fabricate an incompatible primitive contract.
 *
 * Port of the 18.x `no-invalid-zod-custom-parse` rule. Typed: the
 * original returns no visitors without a program. Types come from tsrs only;
 * when `tsrsServices` is null `before()` skips the file.
 *
 * The walk applies every untyped condition and keeps the calls that pass;
 * `Program:exit` resolves both signatures of every candidate in one batch, then
 * the parsed types, their union members and the reported type names in a few
 * more. The original's checks are pure, so running the untyped ones first does
 * not change the reports.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import type { TsrsFile, TsrsNode, TsrsNodeHandle, TsrsRequest, TsrsServices, TsrsType, TsrsTypeFlags } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";

const NAME = "no-invalid-zod-custom-parse";

type Primitive = string | number | bigint | boolean | null;
type ImportKind = "custom" | "namespace";

interface Candidate {
  readonly node: ESTree.CallExpression;
  readonly custom: ESTree.CallExpression;
  readonly value: Primitive;
}

interface SignatureChecker {
  readonly getResolvedSignature: { gen(node: TsrsNode): TsrsRequest<{ readonly declaration?: TsrsNodeHandle | undefined } | undefined> };
}

const ZOD_MODULES: ReadonlySet<string> = new Set(["zod", "zod/v4"]);

// `SourceFile.isDeclarationFile`: TypeScript decides it from the extension (`.d.ts`, `.d.mts`, `.d.cts`, `.d.<ext>.ts`).
const DECLARATION_FILE_RE = /\.d\.(?:[cm]?ts|[^/.]+\.ts)$/;

/** The declaring file is an installed Zod v4 declaration; tsrs handle paths are canonical (lower-cased on macOS). */
function nativeZodDeclaration(declaration: TsrsNodeHandle | undefined): boolean {
  if (declaration === undefined) return false;
  const path = declaration.path.replaceAll("\\", "/");
  return DECLARATION_FILE_RE.test(path) && path.includes("/node_modules/zod/v4/");
}

function inlineCustom(node: ESTree.CallExpression): ESTree.CallExpression | undefined {
  const callee = unwrapExpression(node.callee);
  if (node.optional || node.arguments.length !== 1 || callee.type !== "MemberExpression" || callee.optional ||
    getPropertyName(callee) !== "parse") return undefined;
  const custom = unwrapExpression(callee.object);
  return custom.type === "CallExpression" && !custom.optional && custom.arguments.length === 0 &&
    custom.typeArguments?.params.length === 1 ? custom : undefined;
}

function ownedCustom(node: ESTree.CallExpression, sourceCode: SourceCode): boolean {
  const callee = unwrapExpression(node.callee);
  const identifier = callee.type === "MemberExpression" ? unwrapExpression(callee.object) : callee;
  if (identifier.type !== "Identifier") return false;
  const variable = findVariable(sourceCode.getScope(identifier), identifier.name);
  if (variable === null) return false;
  const kind = zodCustomImportKind(variable);
  if (kind === undefined || !calleeNamesCustom(callee, identifier, kind)) return false;
  return variable.references.every((reference) =>
    (reference.isTypeReference && !reference.isValueReference) || directCustomUse(reference.identifier, kind));
}

/** How the binding's only declaration, a value import from Zod, provides `custom`. */
function zodCustomImportKind(variable: TsVariable): ImportKind | undefined {
  const definition = variable.defs.length === 1 ? variable.defs[0] : undefined;
  if (definition?.type !== "ImportBinding") return undefined;
  const declaration = definition.parent;
  if (declaration?.type !== "ImportDeclaration" || declaration.importKind === "type" ||
    !ZOD_MODULES.has(declaration.source.value)) return undefined;
  return customImportKind(definition.node);
}

function calleeNamesCustom(callee: Node, identifier: Node, kind: ImportKind): boolean {
  if (kind === "custom") return callee === identifier;
  return callee.type === "MemberExpression" && getPropertyName(callee) === "custom";
}

function customImportKind(node: Node): ImportKind | undefined {
  if (node.type === "ImportNamespaceSpecifier" || node.type === "ImportDefaultSpecifier") return "namespace";
  if (node.type !== "ImportSpecifier" || node.importKind === "type") return undefined;
  const name = importSpecifierName(node);
  return name === "custom" ? "custom" : name === "z" ? "namespace" : undefined;
}

function directCustomUse(identifier: Node, kind: ImportKind): boolean {
  const callee = kind === "namespace" ? parentOf(identifier) : identifier;
  if (callee === null) return false;
  if (kind === "namespace" && (callee.type !== "MemberExpression" || callee.object !== identifier || callee.optional ||
    getPropertyName(callee) !== "custom")) return false;
  const call = parentOf(callee);
  return call?.type === "CallExpression" && call.callee === callee && !call.optional;
}

function primitiveLiteral(node: Node): Primitive | undefined {
  const value = unwrapExpression(node);
  if (value.type === "Literal" && (value.value === null || typeof value.value === "string" ||
    typeof value.value === "number" || typeof value.value === "bigint" || typeof value.value === "boolean")) return value.value;
  if (value.type !== "UnaryExpression" || (value.operator !== "-" && value.operator !== "+")) return undefined;
  const operand = unwrapExpression(value.argument);
  if (operand.type !== "Literal") return undefined;
  if (typeof operand.value === "number") return value.operator === "-" ? -operand.value : operand.value;
  return typeof operand.value === "bigint" && value.operator === "-" ? -operand.value : undefined;
}

/** A type and, for a union, its members (TypeScript flattens unions, so one level is complete). */
interface View {
  readonly type: TsrsType;
  readonly members: readonly TsrsType[] | undefined;
}

function primitiveDomain(view: View, flags: TsrsTypeFlags): boolean {
  if (view.members !== undefined) return view.members.every((member) => primitiveDomain({ type: member, members: undefined }, flags));
  const type = view.type;
  if ((type.flags & (flags.Enum | flags.EnumLiteral)) !== 0) return false;
  const domain = flags.String | flags.Number | flags.BigInt | flags.BooleanLiteral | flags.StringLiteral | flags.NumberLiteral |
    flags.BigIntLiteral | flags.Null | flags.Undefined | flags.Never;
  return (type.flags & domain) !== 0;
}

function acceptsPrimitive(view: View, value: Primitive, flags: TsrsTypeFlags): boolean {
  if (view.members !== undefined) return view.members.some((member) => acceptsPrimitive({ type: member, members: undefined }, value, flags));
  const type = view.type;
  if (value === null) return (type.flags & flags.Null) !== 0;
  if (typeof value === "string") return (type.flags & flags.String) !== 0 || ((type.flags & flags.StringLiteral) !== 0 && type.value === value);
  if (typeof value === "number") return (type.flags & flags.Number) !== 0 || ((type.flags & flags.NumberLiteral) !== 0 && type.value === value);
  // TypeScript names boolean literals by intrinsicName; tsrs leaves it unset and gives the value.
  if (typeof value === "boolean") return (type.flags & flags.BooleanLiteral) !== 0 && type.value === value;
  return (type.flags & flags.BigInt) !== 0 ||
    ((type.flags & flags.BigIntLiteral) !== 0 && BigInt(type.value) === value);
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Do not parse an incompatible primitive literal through an unvalidated Zod custom schema.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      incompatibleCustomParse:
        "This unvalidated z.custom parser returns the literal unchanged, outside its promised `{{target}}` domain. Validate the value or preserve an honest unknown contract.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let strictNullChecks = false;
    let candidates: Candidate[] = [];

    function resolve(file: TsrsFile): { node: ESTree.CallExpression; target: string }[] {
      const flags = file.flags;
      const checker = file.checker as unknown as SignatureChecker;
      const pairs = candidates.map((candidate) => [file.tsNode(candidate.custom), file.tsNode(candidate.node)] as const);
      const present = pairs.flatMap((pair) => pair[0] !== undefined && pair[1] !== undefined ? [pair as readonly [TsrsNode, TsrsNode]] : []);
      const signatures = file.batch(present.flatMap(([custom, node]) =>
        [checker.getResolvedSignature.gen(custom), checker.getResolvedSignature.gen(node)]));
      let next = 0;
      const native = pairs.map((pair) => {
        if (pair[0] === undefined || pair[1] === undefined) return false;
        const custom = signatures[next++];
        const call = signatures[next++];
        return nativeZodDeclaration(custom?.declaration) && nativeZodDeclaration(call?.declaration);
      });
      const kept = candidates.filter((_candidate, i) => native[i]);
      const types = file.typesOf(kept.map((candidate) => candidate.node));
      const unions = [...new Set(types.flatMap((type) => type?.isUnionType() === true ? [type] : []))];
      const unionMembers = file.batch(unions.map((union) => union.getTypes.gen()));
      const membersOf = new Map(unions.map((union, i) => [union, unionMembers[i] ?? []]));
      const reported = kept.flatMap((candidate, i) => {
        const type = types[i];
        if (type === undefined) return [];
        const view = { type, members: membersOf.get(type) };
        return !primitiveDomain(view, flags) || acceptsPrimitive(view, candidate.value, flags) ? [] : [{ node: candidate.node, type }];
      });
      const names = file.batch(reported.map((entry) => file.checker.typeToString.gen(entry.type)));
      return reported.map((entry, i) => ({ node: entry.node, target: names[i] ?? "" }));
    }

    return {
      before() {
        tsrs = null;
        candidates = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        if (tsrs === null) return false;
        const options = tsrs.compilerOptions;
        strictNullChecks = Boolean(options.strictNullChecks ?? options.strict ?? false);
        return true;
      },
      CallExpression(node) {
        const custom = inlineCustom(node);
        const argument = node.arguments[0];
        if (custom === undefined || argument === undefined || !ownedCustom(custom, context.sourceCode)) return;
        const value = primitiveLiteral(argument);
        if (value === undefined || (value === null && !strictNullChecks)) return;
        candidates.push({ node, custom, value });
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        const reports = tsrs.run(resolve);
        if (reports === null) return;
        for (const { node, target } of reports) context.report({ node, messageId: "incompatibleCustomParse", data: { target } });
      },
    };
  },
});
