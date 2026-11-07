/**
 * @fileoverview no-json-stringify-object-equality — JSON serialization is not structural object equality.
 *
 * Port of the 18.x `no-json-stringify-object-equality` rule. Syntax
 * decides most comparisons in the walk. When it cannot, and tsrs is available,
 * the comparison waits for `Program:exit`, where tsrs types the serialized
 * values; without tsrs (or when tsrs cannot hold the file) the original's
 * untyped array check decides instead.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import type { TsrsFile, TsrsServices, TsrsSymbol, TsrsType, TsrsTypeFlags } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";
import { existingDomainComparisonFix } from "./_existing-domain-comparison-fix.js";

const NAME = "no-json-stringify-object-equality";

type Expression = ESTree.Expression;

const EQUALITY_OPERATORS: ReadonlySet<string> = new Set(["!=", "!==", "==", "==="]);

function unwrapComparisonExpression(node: Node): Node {
  let current = unwrapExpression(node);
  while (current.type === "ChainExpression") current = unwrapExpression(current.expression);
  return current;
}

function jsonStringifyArgument(node: Node, sourceCode: SourceCode): Expression | null {
  const expression = unwrapComparisonExpression(node);
  if (expression.type !== "CallExpression") return null;
  if (expression.callee.type === "Super" || !isJsonStringify(expression.callee, sourceCode)) return null;
  const argument = expression.arguments[0];
  return argument !== undefined && argument.type !== "SpreadElement" ? argument : null;
}

function isJsonStringify(node: Node, sourceCode: SourceCode): boolean {
  const expression = unwrapComparisonExpression(node);
  if (expression.type === "MemberExpression") {
    return getPropertyName(expression) === "stringify" && expression.object.type !== "Super" &&
      isGlobalJson(expression.object, sourceCode);
  }
  if (expression.type !== "Identifier") return false;
  const binding = findVariable(sourceCode.getScope(expression), expression.name);
  if (binding === null || binding.defs.length !== 1 ||
    binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
  const [definition] = binding.defs;
  if (definition?.type !== "Variable") return false;
  const declarator = definition.node as ESTree.VariableDeclarator;
  const declaration = definition.parent as ESTree.VariableDeclaration | null;
  if (declaration?.kind !== "const" || declarator.id.type !== "ObjectPattern" || declarator.init === null ||
    !isGlobalJson(declarator.init, sourceCode)) return false;
  return declarator.id.properties.some((property) =>
    property.type === "Property" && getPropertyName(property) === "stringify" &&
    property.value.type === "Identifier" &&
    findVariable(sourceCode.getScope(property.value), property.value.name) === binding);
}

function isGlobalJson(node: Node, sourceCode: SourceCode): boolean {
  const expression = unwrapComparisonExpression(node);
  if (expression.type !== "Identifier" || expression.name !== "JSON") return false;
  const binding = findVariable(sourceCode.getScope(expression), expression.name);
  return binding === null || binding.defs.length === 0;
}

function syntaxMayContainObject(node: Node): boolean | null {
  const expression = unwrapComparisonExpression(node);
  if (expression.type === "ObjectExpression") return true;
  if (expression.type === "Literal") return "regex" in expression;
  if (expression.type === "TemplateLiteral" || expression.type === "UnaryExpression") return false;
  if (expression.type !== "ArrayExpression") return null;
  let unknown = false;
  for (const element of expression.elements) {
    if (element === null) continue;
    const result = element.type === "SpreadElement" ? null : syntaxMayContainObject(element);
    if (result === true) return true;
    if (result === null) unknown = true;
  }
  return unknown ? null : false;
}

function untypedArrayMayContainObject(node: ESTree.ArrayExpression): boolean {
  return node.elements.some((element) => {
    if (element === null || element.type === "SpreadElement") return false;
    const value = unwrapComparisonExpression(element);
    return value.type === "ArrayExpression" ? untypedArrayMayContainObject(value) : syntaxMayContainObject(value) !== false;
  });
}

function untypedMayContainObject(node: Node): boolean {
  const syntax = syntaxMayContainObject(node);
  if (syntax !== null) return syntax;
  const expression = unwrapComparisonExpression(node);
  return expression.type === "ArrayExpression" && untypedArrayMayContainObject(expression);
}

// The tsrs checker and type methods this rule needs beyond the shared `TsrsChecker` view.
interface Checker {
  isArrayType(type: TsrsType): boolean;
  isTupleType(type: TsrsType): boolean;
  getTypeArguments(type: TsrsType): readonly TsrsType[];
}
interface Type extends TsrsType {
  getSymbol(): TsrsSymbol | undefined;
}

/**
 * The original's `typeMayContainObject`, on tsrs. The original recurses
 * without a guard and overflows the stack on a recursive type such as
 * `type Json = null | string | Json[] | { [key: string]: Json }`; here a type
 * already being checked adds nothing, so it counts as object-free.
 */
function typeMayContainObject(type: TsrsType, checker: Checker, flags: TsrsTypeFlags, active = new Set<number>()): boolean {
  if (active.has(type.id)) return false;
  active.add(type.id);
  try {
    const recurse = (member: TsrsType): boolean => typeMayContainObject(member, checker, flags, active);
    const primitive = flags.BigIntLike | flags.BooleanLike | flags.ESSymbolLike | flags.Never | flags.Null |
      flags.NumberLike | flags.StringLike | flags.Undefined | flags.Void;
    if (type.isUnionType() || type.isIntersectionType()) return (type.getTypes() ?? []).some(recurse);
    if ((type.flags & primitive) !== 0) return false;
    if ((type.flags & (flags.Any | flags.Unknown | flags.TypeParameter)) !== 0) return true;
    if (checker.isArrayType(type) || checker.isTupleType(type)) return checker.getTypeArguments(type).some(recurse);
    const symbolName = (type as Type).getSymbol()?.name;
    if ((symbolName === "Array" || symbolName === "ReadonlyArray") && (type.flags & flags.Object) !== 0) {
      const elements = checker.getTypeArguments(type);
      return elements.length === 0 || elements.some(recurse);
    }
    return true;
  } finally {
    active.delete(type.id);
  }
}

interface Pending {
  readonly node: ESTree.BinaryExpression;
  readonly left: Expression;
  readonly right: Expression;
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Do not use JSON serialization as structural object equality.",
      url: docsUrl(NAME),
    },
    schema: [],
    fixable: "code",
    messages: {
      serializedObjectEquality:
        "`JSON.stringify` compares serialization details, not object structure. Compare an explicit domain projection or use reviewed canonical serialization.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let pending: Pending[] = [];

    function report(node: ESTree.BinaryExpression): void {
      const fix = existingDomainComparisonFix(context.sourceCode, node);
      context.report({ node, messageId: "serializedObjectEquality", ...(fix !== null && { fix }) });
    }

    /** Typed `mayContainObject` for every pending comparison; types are fetched in one request. */
    function resolveWithTsrs(file: TsrsFile): boolean[] {
      const flags = file.flags;
      const nodes = pending.flatMap(({ left, right }) => [left, right]);
      const types = file.typesOf(nodes);
      const checker = file.checker as unknown as Checker;
      const contains = (node: Expression, i: number): boolean => {
        const syntax = syntaxMayContainObject(node);
        if (syntax !== null) return syntax;
        const type = types[i];
        // No tsrs node at this range: the original's checker would type the node; treat it as unknown.
        return type === undefined || typeMayContainObject(type, checker, flags);
      };
      return pending.map(({ left, right }, i) => contains(left, 2 * i) || contains(right, 2 * i + 1));
    }

    return {
      before() {
        tsrs = null;
        pending = [];
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return undefined;
      },
      BinaryExpression(node) {
        if (!EQUALITY_OPERATORS.has(node.operator)) return;
        if ((node.left as Node).type === "PrivateIdentifier") return;
        const sourceCode = context.sourceCode;
        const left = jsonStringifyArgument(node.left, sourceCode);
        const right = left === null ? null : jsonStringifyArgument(node.right, sourceCode);
        if (left === null || right === null) return;
        const leftSyntax = syntaxMayContainObject(left);
        const rightSyntax = syntaxMayContainObject(right);
        if (leftSyntax === true || rightSyntax === true) return report(node);
        if (leftSyntax === false && rightSyntax === false) return;
        if (tsrs !== null) {
          pending.push({ node, left, right });
          return;
        }
        if (untypedMayContainObject(left) || untypedMayContainObject(right)) report(node);
      },
      "Program:exit"() {
        if (pending.length === 0 || tsrs === null) return;
        // No program holds the file, or tsrs failed: the original's untyped check decides.
        const found = tsrs.run(resolveWithTsrs) ??
          pending.map(({ left, right }) => untypedMayContainObject(left) || untypedMayContainObject(right));
        pending.forEach((item, i) => {
          if (found[i] === true) report(item.node);
        });
      },
    };
  },
});
