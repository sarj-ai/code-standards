/**
 * @fileoverview prefer-nominal-id-types — distinguish identifier roles at callable boundaries.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-nominal-id-types.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Context } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "preferNominalIds";
type Options = [];
type Carrier = "string" | "number" | "string[]" | "number[]";
type Boundary = ESTree.Node & { readonly params: readonly ESTree.ParamPattern[] };

const OPERATIONAL_ROLES: ReadonlySet<string> = new Set([
  "request", "trace", "span", "correlation", "process", "thread", "timeout", "interval",
]);
const MAX_ALIAS_DEPTH = 16;

export const PREFER_NOMINAL_ID_TYPES_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Distinguish identifier roles sharing primitive types at callable boundaries.",
  rationale: "Two identifier roles represented by the same primitive accept each other's values, so swapped arguments survive type checking. Transparent aliases do not prevent this.",
  remediation: "Introduce distinct branded identifier types at a validated domain boundary and use them in the callable contract. Keep wire representations primitive until validation; suppress a required external signature locally with a reason.",
  category: "correctness",
  limitations: [
    "Requires two distinct Id/Ids or _id/_ids parameter roles with the same proven string, number, or homogeneous array carrier. Plural names require array carriers. Scalars and arrays remain distinct; object fields, destructuring, tuples, inferred types and generic aliases are not checked.",
    "Resolves only scope-correct file-local transparent aliases, up to 16 levels. Intersections, imported types, ambiguous declarations and mixed branded/raw pairs are deliberately skipped.",
    "Generated files and request, trace, span, correlation, process, thread, timeout and interval identifiers are excluded. Raw wire object schemas are not callable boundaries; required external callable signatures need a local suppression. API and adapter paths are not blanket-excluded.",
  ],
  examples: [
    { id: "raw-identifiers", title: "Do not accept interchangeable identifiers", outcome: "match", files: [{ path: "src/store.ts", source: "function load(accountId: string, invoiceId: string): void {}" }], focusPath: "src/store.ts", expectedCount: 1, public: true },
    { id: "branded-identifiers", title: "Distinguish domain identifiers", outcome: "no-match", files: [{ path: "src/store.ts", source: "type AccountId = string & { readonly account: unique symbol }; type InvoiceId = string & { readonly invoice: unique symbol }; function load(accountId: AccountId, invoiceId: InvoiceId): void {}" }], focusPath: "src/store.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function arrayCarrier(carrier: Carrier | undefined): Carrier | undefined {
  if (carrier === "string") return "string[]";
  if (carrier === "number") return "number[]";
  return undefined;
}

function isNullish(node: ESTree.TSType): boolean {
  return node.type === "TSUndefinedKeyword" || node.type === "TSNullKeyword" ||
    (node.type === "TSLiteralType" && node.literal.type === "Literal" && node.literal.value === null);
}

function referenceCarrier(node: ESTree.TSTypeReference, context: Context, depth: number): Carrier | undefined {
  if (node.typeName.type !== "Identifier") return undefined;
  const variable = findVariable(context.sourceCode.getScope(node), node.typeName.name);
  const definitions = variable?.defs ?? [];
  const args = node.typeArguments?.params;
  if (definitions.length === 0 && ["Array", "ReadonlyArray"].includes(node.typeName.name) && args?.length === 1) {
    return arrayCarrier(rawCarrier(args[0], context, depth + 1));
  }
  if (args != null || definitions.length !== 1) return undefined;
  const declaration = definitions[0]?.node;
  if (declaration?.type !== "TSTypeAliasDeclaration" || declaration.typeParameters != null) return undefined;
  return rawCarrier(declaration.typeAnnotation, context, depth + 1);
}

function rawCarrier(node: ESTree.TSType | undefined, context: Context, depth = 0): Carrier | undefined {
  if (node == null || depth >= MAX_ALIAS_DEPTH) return undefined;
  switch (node.type) {
    case "TSStringKeyword": return "string";
    case "TSNumberKeyword": return "number";
    case "TSArrayType": return arrayCarrier(rawCarrier(node.elementType, context, depth + 1));
    case "TSTypeOperator":
      return node.operator === "readonly" ? rawCarrier(node.typeAnnotation, context, depth + 1) : undefined;
    case "TSUnionType": {
      const members = node.types.filter((member) => !isNullish(member));
      if (members.length !== 1) return undefined;
      return rawCarrier(members[0], context, depth + 1);
    }
    case "TSTypeReference": return referenceCarrier(node, context, depth);
    default: return undefined;
  }
}

function checkBoundary(node: Boundary, context: Context): void {
  const roles = new Map<Carrier, string>();
  for (const parameter of node.params) {
    const identifier = parameterIdentifier(parameter);
    if (identifier?.typeAnnotation == null) continue;
    const role = identifierRole(identifier.name);
    if (role === undefined) continue;
    const carrier = rawCarrier(identifier.typeAnnotation.typeAnnotation, context);
    if (carrier === undefined || (/(?:Ids|_ids)$/u.test(identifier.name) && !carrier.endsWith("[]"))) continue;
    const previous = roles.get(carrier);
    if (previous !== undefined && previous !== role) {
      context.report({ node: identifier, messageId: "preferNominalIds" });
      return;
    }
    roles.set(carrier, role);
  }
}

function identifierRole(name: string): string | undefined {
  const match = /^(.*?)(?:Ids?|_ids?)$/u.exec(name);
  const stem = match?.[1];
  if (stem === undefined || stem.length === 0) return undefined;
  const role = stem.replaceAll("_", "").toLowerCase();
  return OPERATIONAL_ROLES.has(role) ? undefined : role;
}

function parameterIdentifier(parameter: ESTree.ParamPattern): ESTree.BindingIdentifier | undefined {
  if (parameter.type === "Identifier") return parameter;
  if (parameter.type === "AssignmentPattern" && parameter.left.type === "Identifier") return parameter.left;
  if (parameter.type === "TSParameterProperty") return parameterIdentifier(parameter.parameter);
  return undefined;
}

export default createRule<Options, MessageIds>({
  name: "prefer-nominal-id-types",
  documentation: PREFER_NOMINAL_ID_TYPES_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Distinguish identifier roles sharing primitive types at callable boundaries." },
    schema: [],
    messages: { preferNominalIds: "Distinct identifier roles share an interchangeable primitive type. Use distinct branded identifier types at this callable boundary." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) return {};
    return {
      ArrowFunctionExpression: (node): void => checkBoundary(node, context),
      FunctionDeclaration: (node): void => checkBoundary(node, context),
      FunctionExpression: (node): void => checkBoundary(node, context),
      TSDeclareFunction: (node): void => checkBoundary(node, context),
      TSEmptyBodyFunctionExpression: (node): void => checkBoundary(node, context),
      TSFunctionType: (node): void => checkBoundary(node, context),
      TSMethodSignature: (node): void => checkBoundary(node, context),
    };
  },
});
