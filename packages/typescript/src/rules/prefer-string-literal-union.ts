/**
 * @fileoverview prefer-string-literal-union — a raw `string` field with a closed set of values accepts every value outside it.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-string-literal-union.test.ts
 */

import { createRule } from "./_docs.js";
import {
  ESLintUtils,
  type TSESTree,
  type ParserServicesWithTypeInformation,
  AST_NODE_TYPES,
} from "@typescript-eslint/utils";
import * as ts from "typescript";

type MessageIds = "bareChoiceField" | "comparisonCluster";
type Options = readonly [
  {
    ignoreFields?: readonly string[];
  }?,
];

type FunctionNode =
  | TSESTree.FunctionDeclaration
  | TSESTree.FunctionExpression
  | TSESTree.ArrowFunctionExpression;

const CHOICE_TOKENS: ReadonlySet<string> = new Set([
  "status",
  "state",
  "kind",
  "role",
  "priority",
  "severity",
  "direction",
  "tier",
  "stage",
  "type",
  "mode",
  "level",
]);

const LOWER_TOKEN_RE = /^[a-z][a-z0-9_-]{0,30}$/;
const MIN_CLUSTER_SIZE = 2;

const BOOLEANISH: ReadonlySet<string> = new Set(["true", "false"]);

/**
 * An enum-shaped token worth a string-literal union: a short lowercase word of
 * 2+ chars that isn't a boolean-string. Single characters (`'a'`), file
 * paths/URLs/i18n keys (contain `/`, `:`, `.`), and `'true'`/`'false'` are NOT
 * closed-enum members — comparing against them is a flag/path/boolean guard.
 */

function isEnumToken(lit: string): boolean {
  return LOWER_TOKEN_RE.test(lit) && lit.length >= 2 && !BOOLEANISH.has(lit);
}

const IGNORE_PATTERNS: readonly RegExp[] = [
  /[\\/]generated[\\/]/,
  /\.gen\.tsx?$/,
  /\.generated\.tsx?$/,
  /\.d\.ts$/,
];

function isIgnoredFile(filename: string, sourceText: string): boolean {
  if (IGNORE_PATTERNS.some((re) => re.test(filename))) {
    return true;
  }
  return /@generated\b/.test(sourceText.slice(0, 1024));
}

/**
 * The trailing word of a camelCase / snake_case identifier, lowercased.
 * `callStatus` -> `status`, `user_role` -> `role`, `estate` -> `estate`.
 */
function lastWord(name: string): string {
  const words = name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[_\s]+/)
    .filter((w) => w.length > 0);
  const last = words[words.length - 1] ?? name;
  return last.toLowerCase();
}

function isChoiceLikeName(name: string): boolean {
  return CHOICE_TOKENS.has(lastWord(name));
}

function keyName(
  key: TSESTree.PropertyDefinition["key"] | TSESTree.PropertyName,
): string | null {
  if (key.type === AST_NODE_TYPES.Identifier) {
    return key.name;
  }
  if (key.type === AST_NODE_TYPES.Literal && typeof key.value === "string") {
    return key.value;
  }
  return null;
}

function isStringLiteralMember(t: TSESTree.TypeNode): boolean {
  return (
    t.type === AST_NODE_TYPES.TSLiteralType &&
    t.literal.type === AST_NODE_TYPES.Literal &&
    typeof t.literal.value === "string"
  );
}

/** Whether a type node is a union of 2+ string-literal types. */
function isStringLiteralUnion(node: TSESTree.TypeNode | undefined): boolean {
  if (node?.type !== AST_NODE_TYPES.TSUnionType) {
    return false;
  }
  return node.types.filter(isStringLiteralMember).length >= MIN_CLUSTER_SIZE;
}

/**
 * Whether a resolved TS type includes the general `string` type — as opposed to
 * being (a union of) string-literal types. `CallStatus = "a" | "b"` has no
 * general-string member and is already the target state; a raw `string` (or
 * `string | undefined`) does, and a comparison cluster on it should become a
 * union. Requires type information; the comparison-cluster path is inert
 * without it.
 */
function typeHasRawString(type: ts.Type): boolean {
  const parts = type.isUnion() ? type.types : [type];
  return parts.some((t) => (t.flags & ts.TypeFlags.String) !== 0);
}

function isExternalSourceFile(sf: ts.SourceFile | undefined): boolean {
  if (sf === undefined) {
    return false;
  }
  return sf.isDeclarationFile || sf.fileName.includes("/node_modules/");
}

function symbolIsExternallyDeclared(sym: ts.Symbol | undefined): boolean {
  return (
    sym?.declarations?.some((d) => isExternalSourceFile(d.getSourceFile())) ??
    false
  );
}

/**
 * The iterable expression a destructuring binding element draws its value from,
 * e.g. `Object.entries(x)` for `key` in `for (const [key] of Object.entries(x))`
 * or the RHS of `const { a } = rhs`.
 */
function bindingSourceExpression(
  decl: ts.BindingElement,
): ts.Expression | undefined {
  let node: ts.Node = decl.parent;
  while (
    !ts.isForOfStatement(node) &&
    !(ts.isVariableDeclaration(node) && node.initializer !== undefined)
  ) {
    if (node.parent === undefined) {
      return undefined;
    }
    node = node.parent;
  }
  return ts.isForOfStatement(node) ? node.expression : node.initializer;
}

/** A stable key for a plain identifier or non-computed member chain, else null. */
function refKey(node: TSESTree.Node): string | null {
  if (node.type === AST_NODE_TYPES.Identifier) {
    return node.name;
  }
  if (node.type === AST_NODE_TYPES.MemberExpression && !node.computed) {
    const inner = refKey(node.object);
    if (inner === null || node.property.type !== AST_NODE_TYPES.Identifier) {
      return null;
    }
    return `${inner}.${node.property.name}`;
  }
  return null;
}

function strLiteral(node: TSESTree.Node): string | null {
  if (node.type === AST_NODE_TYPES.Literal && typeof node.value === "string") {
    return node.value;
  }
  return null;
}

interface ClusterEntry {
  node: TSESTree.Node;
  literals: Set<string>;
  allTokens: boolean;
}

interface Scope {
  clusters: Map<string, ClusterEntry>;
  /** The function this scope belongs to; null at file scope. */
  fn: FunctionNode | null;
}

interface CollectedProperty {
  name: string;
  container: TSESTree.Node;
  node: TSESTree.Node;
}

export default createRule<Options, MessageIds>({
  name: "prefer-string-literal-union",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag raw `string` choice fields and string-literal comparison clusters; prefer a string-literal union type.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          ignoreFields: {
            type: "array",
            items: { type: "string" },
          },
        },
      },
    ],
    messages: {
      bareChoiceField:
        '`{{name}}: string` looks like a choice field — prefer a string-literal union type (e.g. `type X = "a" | "b"`). Enums are banned by `no-enum`; use a union.',
      comparisonCluster:
        '`{{key}}` is compared against a closed set of string literals — define a string-literal union type (e.g. `type X = "a" | "b"`).',
    },
  },
  defaultOptions: [{}],
  create(context, [optionsArg]) {
    const filename = context.filename;
    const sourceText = context.sourceCode.getText();
    if (isIgnoredFile(filename, sourceText)) {
      return {};
    }

    const ignoredFields = new Set(
      (optionsArg?.ignoreFields ?? []).map((name) => name.toLowerCase()),
    );

    let services: ParserServicesWithTypeInformation | null;
    try {
      services = ESLintUtils.getParserServices(context);
    } catch {
      services = null;
    }

    const scopeStack: Scope[] = [];
    const validClusters: TSESTree.Node[] = [];
    const bareChoiceProps: CollectedProperty[] = [];
    const containersWithUnion = new Set<TSESTree.Node>();

    function operandIsRawString(node: TSESTree.Node): boolean {
      if (services === null) {
        return false;
      }
      return typeHasRawString(services.getTypeAtLocation(node));
    }

    /**
     * Whether the compared value provably originates from a type we don't own —
     * a property of a `.d.ts` / node_modules type (DOM `getComputedStyle().overflowY`,
     * `Task.status` from another package), the return of such a method
     * (`URLSearchParams.get()`, `str.toLowerCase()`), or a destructuring of one
     * (`Object.entries()` keys). A string-literal union is not an available fix
     * for these, so the cluster shape must not flag them.
     */
    function originIsExternal(node: ts.Node | undefined, depth: number): boolean {
      if (node === undefined || services === null || depth > 6) {
        return false;
      }
      const checker = services.program.getTypeChecker();
      if (
        ts.isParenthesizedExpression(node) ||
        ts.isNonNullExpression(node) ||
        ts.isAsExpression(node)
      ) {
        return originIsExternal(node.expression, depth + 1);
      }
      if (ts.isPropertyAccessExpression(node)) {
        return symbolIsExternallyDeclared(checker.getSymbolAtLocation(node.name));
      }
      if (ts.isCallExpression(node)) {
        return originIsExternal(node.expression, depth + 1);
      }
      if (ts.isIdentifier(node)) {
        const decl = checker.getSymbolAtLocation(node)?.valueDeclaration;
        if (decl === undefined) {
          return false;
        }
        if (ts.isVariableDeclaration(decl) && decl.initializer !== undefined) {
          return originIsExternal(decl.initializer, depth + 1);
        }
        if (ts.isBindingElement(decl)) {
          return originIsExternal(bindingSourceExpression(decl), depth + 1);
        }
      }
      return false;
    }

    function operandIsFlaggable(node: TSESTree.Node): boolean {
      return (
        operandIsRawString(node) &&
        !originIsExternal(services?.esTreeNodeToTSNodeMap.get(node), 0)
      );
    }

    /**
     * The string-literal members of a function's DECLARED return type, resolved
     * through named aliases and `Promise<...>`. Null when the function has no
     * annotation, type information is unavailable, or the type is not a
     * string-literal union. Computed lazily — only for a function that actually
     * accumulated a cluster — since it costs a type resolution.
     */
    function declaredReturnLiterals(fn: FunctionNode): ReadonlySet<string> | null {
      const annotation = fn.returnType?.typeAnnotation;
      if (annotation === undefined || services === null) {
        return null;
      }
      const tsNode = services.esTreeNodeToTSNodeMap.get(annotation);
      if (!ts.isTypeNode(tsNode)) {
        return null;
      }
      const checker = services.program.getTypeChecker();
      const declared = checker.getTypeFromTypeNode(tsNode);
      const type = checker.getAwaitedType(declared) ?? declared;
      const literals = new Set<string>();
      for (const part of type.isUnion() ? type.types : [type]) {
        if (part.isStringLiteral()) {
          literals.add(part.value);
        }
      }
      return literals.size >= MIN_CLUSTER_SIZE ? literals : null;
    }

    function pushScope(node: FunctionNode): void {
      scopeStack.push({ clusters: new Map(), fn: node });
    }

    function popScope(): void {
      const scope = scopeStack.pop();
      if (scope === undefined) {
        return;
      }
      const candidates = [...scope.clusters.values()].filter(
        (entry) => entry.allTokens && entry.literals.size >= MIN_CLUSTER_SIZE,
      );
      if (candidates.length === 0) {
        return;
      }
      const returnLiterals =
        scope.fn === null ? null : declaredReturnLiterals(scope.fn);
      for (const entry of candidates) {
        // The enclosing function declares the very union being compared against:
        // this is the narrowing boundary that produces it, so the `string`
        // operand is required, not a defect.
        if (
          returnLiterals !== null &&
          [...entry.literals].every((lit) => returnLiterals.has(lit))
        ) {
          continue;
        }
        validClusters.push(entry.node);
      }
    }

    function accumulate(
      key: string,
      literals: string[],
      node: TSESTree.Node,
    ): void {
      const scope = scopeStack[scopeStack.length - 1];
      if (scope === undefined) {
        return;
      }
      const allTokens = literals.every((lit) => isEnumToken(lit));
      const existing = scope.clusters.get(key);
      if (existing === undefined) {
        scope.clusters.set(key, {
          node,
          literals: new Set(literals),
          allTokens,
        });
        return;
      }
      for (const lit of literals) {
        existing.literals.add(lit);
      }
      existing.allTokens = existing.allTokens && allTokens;
    }

    function collectProperty(
      key: TSESTree.PropertyDefinition["key"] | TSESTree.PropertyName,
      typeNode: TSESTree.TypeNode | undefined,
      container: TSESTree.Node,
      node: TSESTree.Node,
    ): void {
      if (isStringLiteralUnion(typeNode)) {
        containersWithUnion.add(container);
        return;
      }
      if (typeNode?.type !== AST_NODE_TYPES.TSStringKeyword) {
        return;
      }
      const name = keyName(key);
      if (
        name === null ||
        !isChoiceLikeName(name) ||
        ignoredFields.has(name.toLowerCase())
      ) {
        return;
      }
      bareChoiceProps.push({ name, container, node });
    }

    return {
      FunctionDeclaration: pushScope,
      "FunctionDeclaration:exit": popScope,
      FunctionExpression: pushScope,
      "FunctionExpression:exit": popScope,
      ArrowFunctionExpression: pushScope,
      "ArrowFunctionExpression:exit": popScope,

      BinaryExpression(node: TSESTree.BinaryExpression): void {
        if (
          node.operator !== "===" &&
          node.operator !== "!==" &&
          node.operator !== "==" &&
          node.operator !== "!="
        ) {
          return;
        }
        const leftKey = refKey(node.left);
        const rightLit = strLiteral(node.right);
        const rightKey = refKey(node.right);
        const leftLit = strLiteral(node.left);
        if (leftKey !== null && rightLit !== null) {
          if (operandIsFlaggable(node.left)) {
            accumulate(leftKey, [rightLit], node);
          }
        } else if (rightKey !== null && leftLit !== null) {
          if (operandIsFlaggable(node.right)) {
            accumulate(rightKey, [leftLit], node);
          }
        }
      },

      SwitchStatement(node: TSESTree.SwitchStatement): void {
        const key = refKey(node.discriminant);
        if (key === null || !operandIsFlaggable(node.discriminant)) {
          return;
        }
        const literals: string[] = [];
        for (const c of node.cases) {
          if (c.test !== null) {
            const lit = strLiteral(c.test);
            if (lit !== null) {
              literals.push(lit);
            }
          }
        }
        if (literals.length > 0) {
          accumulate(key, literals, node);
        }
      },

      TSPropertySignature(node: TSESTree.TSPropertySignature): void {
        collectProperty(
          node.key,
          node.typeAnnotation?.typeAnnotation,
          node.parent,
          node,
        );
      },

      PropertyDefinition(node: TSESTree.PropertyDefinition): void {
        collectProperty(
          node.key,
          node.typeAnnotation?.typeAnnotation,
          node.parent,
          node,
        );
      },

      "Program:exit"(): void {
        for (const clusterNode of validClusters) {
          context.report({
            node: clusterNode,
            messageId: "comparisonCluster",
            data: { key: refKeyText(clusterNode) },
          });
        }
        for (const prop of bareChoiceProps) {
          if (containersWithUnion.has(prop.container)) {
            context.report({
              node: prop.node,
              messageId: "bareChoiceField",
              data: { name: prop.name },
            });
          }
        }
      },
    };

    function refKeyText(node: TSESTree.Node): string {
      if (node.type === AST_NODE_TYPES.BinaryExpression) {
        return refKey(node.left) ?? refKey(node.right) ?? "value";
      }
      if (node.type === AST_NODE_TYPES.SwitchStatement) {
        return refKey(node.discriminant) ?? "value";
      }
      return "value";
    }
  },
});
