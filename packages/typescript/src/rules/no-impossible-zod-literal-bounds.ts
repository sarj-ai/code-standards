/**
 * @fileoverview no-impossible-zod-literal-bounds — literal Zod bounds must admit at least one value.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-impossible-zod-literal-bounds.test.ts
 */

import {
  AST_NODE_TYPES,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "impossibleBounds";
type Options = readonly [];
type SchemaKind = "array" | "number" | "string";

type Bound = {
  readonly exclusive: boolean;
  readonly label: string;
  readonly value: number;
};

type Chain = {
  readonly calls: readonly { method: string; node: TSESTree.CallExpression }[];
  readonly kind: SchemaKind;
};

const KINDS: ReadonlySet<SchemaKind> = new Set(["array", "number", "string"]);
const NUMBER_METHODS: ReadonlySet<string> = new Set([
  "gt",
  "gte",
  "lt",
  "lte",
  "max",
  "min",
]);
const LENGTH_METHODS: ReadonlySet<string> = new Set(["length", "max", "min"]);
const RESHAPING_METHODS: ReadonlySet<string> = new Set([
  "pipe",
  "preprocess",
  "transform",
]);

function importedName(specifier: TSESTree.ImportSpecifier): string | null {
  return specifier.imported.type === AST_NODE_TYPES.Identifier
    ? specifier.imported.name
    : typeof specifier.imported.value === "string"
      ? specifier.imported.value
      : null;
}

function memberName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) {
    return node.property.name;
  }
  if (
    node.computed &&
    node.property.type === AST_NODE_TYPES.Literal &&
    typeof node.property.value === "string"
  ) {
    return node.property.value;
  }
  return null;
}

function finiteNumber(node: TSESTree.CallExpressionArgument | undefined): number | null {
  if (node?.type === AST_NODE_TYPES.Literal && typeof node.value === "number") {
    return Number.isFinite(node.value) ? node.value : null;
  }
  if (
    node?.type === AST_NODE_TYPES.UnaryExpression &&
    (node.operator === "-" || node.operator === "+") &&
    node.argument.type === AST_NODE_TYPES.Literal &&
    typeof node.argument.value === "number"
  ) {
    const value = node.operator === "-" ? -node.argument.value : node.argument.value;
    return Number.isFinite(value) ? value : null;
  }
  return null;
}

function strongerLower(current: Bound | null, candidate: Bound): Bound {
  if (
    current === null ||
    candidate.value > current.value ||
    (candidate.value === current.value && candidate.exclusive && !current.exclusive)
  ) {
    return candidate;
  }
  return current;
}

function strongerUpper(current: Bound | null, candidate: Bound): Bound {
  if (
    current === null ||
    candidate.value < current.value ||
    (candidate.value === current.value && candidate.exclusive && !current.exclusive)
  ) {
    return candidate;
  }
  return current;
}

function isEmpty(lower: Bound | null, upper: Bound | null): boolean {
  if (lower === null || upper === null) return false;
  return (
    lower.value > upper.value ||
    (lower.value === upper.value && (lower.exclusive || upper.exclusive))
  );
}

function isOutermostCall(node: TSESTree.CallExpression): boolean {
  const parent = node.parent;
  return !(
    parent?.type === AST_NODE_TYPES.MemberExpression &&
    parent.object === node &&
    parent.parent?.type === AST_NODE_TYPES.CallExpression &&
    parent.parent.callee === parent
  );
}

export default createRule<Options, MessageIds>({
  name: "no-impossible-zod-literal-bounds",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow same-chain literal Zod bounds whose accepted set is mathematically empty.",
    },
    schema: [],
    messages: {
      impossibleBounds:
        "This Zod {{kind}} schema accepts no values: {{lower}} conflicts with {{upper}}.",
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, sourceCode.getText())
    ) {
      return {};
    }

    const namespaces = new Set<string>();
    const constructors = new Map<string, SchemaKind>();
    const preprocessors = new Set<string>();
    const importBindings = new Map<string, TSESTree.Identifier>();

    function resolvesToTrackedImport(node: TSESTree.Identifier): boolean {
      const binding = importBindings.get(node.name);
      if (binding === undefined) return false;
      let scope: TSESLint.Scope.Scope | null = sourceCode.getScope(node);
      while (scope !== null) {
        const variable = scope.variables.find((candidate) => candidate.name === node.name);
        if (variable !== undefined) {
          return variable.defs.some((definition) => definition.name === binding);
        }
        scope = scope.upper;
      }
      return false;
    }

    function baseKind(node: TSESTree.CallExpression): SchemaKind | null {
      const callee = node.callee;
      if (callee.type === AST_NODE_TYPES.Identifier) {
        return resolvesToTrackedImport(callee)
          ? constructors.get(callee.name) ?? null
          : null;
      }
      if (
        callee.type !== AST_NODE_TYPES.MemberExpression ||
        callee.object.type !== AST_NODE_TYPES.Identifier ||
        !namespaces.has(callee.object.name) ||
        !resolvesToTrackedImport(callee.object)
      ) {
        return null;
      }
      const name = memberName(callee);
      return name !== null && KINDS.has(name as SchemaKind)
        ? (name as SchemaKind)
        : null;
    }

    function readChain(node: TSESTree.CallExpression): Chain | null {
      const calls: { method: string; node: TSESTree.CallExpression }[] = [];
      let current = node;
      while (true) {
        const kind = baseKind(current);
        if (kind !== null) return { calls, kind };
        const callee = current.callee;
        if (
          callee.type !== AST_NODE_TYPES.MemberExpression ||
          callee.object.type !== AST_NODE_TYPES.CallExpression
        ) {
          return null;
        }
        const method = memberName(callee);
        if (method === null) return null;
        calls.push({ method, node: current });
        current = callee.object;
      }
    }

    function isInsideReshapingCall(node: TSESTree.CallExpression): boolean {
      let child: TSESTree.Node = node;
      let parent = child.parent;
      while (parent !== undefined && parent.type !== AST_NODE_TYPES.Program) {
        if (parent.type === AST_NODE_TYPES.CallExpression) {
          const callee = parent.callee;
          if (
            callee.type === AST_NODE_TYPES.MemberExpression &&
            RESHAPING_METHODS.has(memberName(callee) ?? "") &&
            (callee.object.type === AST_NODE_TYPES.CallExpression ||
              (callee.object.type === AST_NODE_TYPES.Identifier &&
                namespaces.has(callee.object.name) &&
                resolvesToTrackedImport(callee.object)))
          ) {
            return true;
          }
          if (
            callee.type === AST_NODE_TYPES.Identifier &&
            preprocessors.has(callee.name) &&
            resolvesToTrackedImport(callee)
          ) {
            return true;
          }
        }
        child = parent;
        parent = child.parent;
      }
      return false;
    }

    function contradiction(chain: Chain): { lower: Bound; upper: Bound } | null {
      const allowed = chain.kind === "number" ? NUMBER_METHODS : LENGTH_METHODS;
      let lower: Bound | null = null;
      let upper: Bound | null = null;

      for (const { method, node } of chain.calls) {
        if (!allowed.has(method)) return null;
        const value = finiteNumber(node.arguments[0]);
        if (value === null) return null;
        if (chain.kind !== "number" && (!Number.isInteger(value) || value < 0)) {
          return null;
        }
        const label = `${method}(${String(value)})`;
        if (method === "length") {
          lower = strongerLower(lower, { exclusive: false, label, value });
          upper = strongerUpper(upper, { exclusive: false, label, value });
        } else if (method === "gt" || method === "gte" || method === "min") {
          lower = strongerLower(lower, {
            exclusive: method === "gt",
            label,
            value,
          });
        } else {
          upper = strongerUpper(upper, {
            exclusive: method === "lt",
            label,
            value,
          });
        }
      }
      return isEmpty(lower, upper) && lower !== null && upper !== null
        ? { lower, upper }
        : null;
    }

    return {
      ImportDeclaration(node: TSESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier
          ) {
            namespaces.add(specifier.local.name);
            importBindings.set(specifier.local.name, specifier.local);
            continue;
          }
          const imported = importedName(specifier);
          if (imported === "z") {
            namespaces.add(specifier.local.name);
            importBindings.set(specifier.local.name, specifier.local);
          } else if (imported !== null && KINDS.has(imported as SchemaKind)) {
            constructors.set(specifier.local.name, imported as SchemaKind);
            importBindings.set(specifier.local.name, specifier.local);
          } else if (imported === "preprocess") {
            preprocessors.add(specifier.local.name);
            importBindings.set(specifier.local.name, specifier.local);
          }
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        if (!isOutermostCall(node) || isInsideReshapingCall(node)) return;
        const chain = readChain(node);
        if (chain === null) return;
        const conflict = contradiction(chain);
        if (conflict === null) return;
        context.report({
          node,
          messageId: "impossibleBounds",
          data: {
            kind: chain.kind,
            lower: conflict.lower.label,
            upper: conflict.upper.label,
          },
        });
      },
    };
  },
});
