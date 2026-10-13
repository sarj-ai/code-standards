/**
 * @fileoverview no-impossible-zod-literal-bounds — literal Zod bounds must admit at least one value.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-impossible-zod-literal-bounds.test.ts
 */

import {
  ASTUtils,
  AST_NODE_TYPES,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "impossibleBounds";
type Options = readonly [{ readonly delegateRealContradictions?: boolean }?];
type SchemaKind =
  "array" | "number" | "string" | "integer" | "int32" | "uint32";

export const NO_IMPOSSIBLE_ZOD_LITERAL_BOUNDS_DOCUMENTATION = {
  summary:
    "Disallow same-chain literal Zod bounds whose accepted set is mathematically empty.",
  rationale:
    "A schema with contradictory literal bounds rejects every input, turning validation into an unreachable contract that usually reflects a typo.",
  remediation:
    "Choose compatible lower and upper bounds, or remove the constraint that does not express the intended domain.",
  category: "correctness",
  limitations: [
    "Only finite numeric literals in a single schema chain are compared; number().int(), int(), int32(), uint32(), strings and arrays require an admitted integer value or length.",
    "int32() and uint32() include their intrinsic ranges. The managed preset delegates explicit real-bound conflicts to upstream zod/no-conflicting-checks to avoid duplicate findings.",
    "Integer-domain comparisons abstain near the JavaScript safe-integer boundary.",
    "Chains with dynamic bounds, non-bound validators, transforms, pipes, or preprocessors are skipped.",
    "Test and generated files are excluded.",
  ],
  examples: [
    {
      id: "compatible-number-bounds",
      title: "Allow a number admitted by both bounds",
      outcome: "no-match",
      files: [
        {
          path: "src/schema.ts",
          source:
            'import { z } from "zod"; const S = z.number().gte(3).lte(3);',
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "contradictory-number-bounds",
      title: "Reject an empty numeric interval",
      outcome: "match",
      files: [
        {
          path: "src/schema.ts",
          source:
            'import { z } from "zod"; const S = z.number().min(5).max(4);',
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

type Bound = {
  readonly exclusive: boolean;
  readonly label: string;
  readonly value: number;
};

type ChainBounds = {
  readonly integer: boolean;
  readonly lower: Bound | null;
  readonly numeric: boolean;
  readonly upper: Bound | null;
};

type Chain = {
  readonly calls: readonly { method: string; node: TSESTree.CallExpression }[];
  readonly kind: SchemaKind;
};

const KINDS: ReadonlyMap<string, SchemaKind> = new Map([
  ["array", "array"],
  ["number", "number"],
  ["string", "string"],
  ["int", "integer"],
  ["int32", "int32"],
  ["uint32", "uint32"],
]);
const NUMBER_METHODS: ReadonlySet<string> = new Set([
  "gt",
  "gte",
  "int",
  "lt",
  "lte",
  "max",
  "min",
  "negative",
  "nonnegative",
  "nonpositive",
  "positive",
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

function finiteNumber(
  node: TSESTree.CallExpressionArgument | undefined,
): number | null {
  node = node === undefined ? undefined : unwrapExpression(node);
  if (node?.type === AST_NODE_TYPES.Literal && typeof node.value === "number") {
    return Number.isFinite(node.value) ? node.value : null;
  }
  if (
    node?.type === AST_NODE_TYPES.UnaryExpression &&
    (node.operator === "-" || node.operator === "+") &&
    node.argument.type === AST_NODE_TYPES.Literal &&
    typeof node.argument.value === "number"
  ) {
    const value =
      node.operator === "-" ? -node.argument.value : node.argument.value;
    return Number.isFinite(value) ? value : null;
  }
  return null;
}

function strongerLower(current: Bound | null, candidate: Bound): Bound {
  if (
    current === null ||
    candidate.value > current.value ||
    (candidate.value === current.value &&
      candidate.exclusive &&
      !current.exclusive)
  ) {
    return candidate;
  }
  return current;
}

function strongerUpper(current: Bound | null, candidate: Bound): Bound {
  if (
    current === null ||
    candidate.value < current.value ||
    (candidate.value === current.value &&
      candidate.exclusive &&
      !current.exclusive)
  ) {
    return candidate;
  }
  return current;
}

function isRealEmpty(lower: Bound | null, upper: Bound | null): boolean {
  if (lower === null || upper === null) return false;
  return (
    lower.value > upper.value ||
    (lower.value === upper.value && (lower.exclusive || upper.exclusive))
  );
}

function isEmpty(
  lower: Bound | null,
  upper: Bound | null,
  integer: boolean,
): boolean {
  if (lower === null || upper === null) return false;
  if (isRealEmpty(lower, upper)) return true;
  if (integer) {
    const safeMargin = Number.MAX_SAFE_INTEGER - 1;
    if (
      Math.abs(lower.value) >= safeMargin ||
      Math.abs(upper.value) >= safeMargin
    ) {
      return false;
    }
    const minimum = lower.exclusive
      ? Math.floor(lower.value) + 1
      : Math.ceil(lower.value);
    const maximum = upper.exclusive
      ? Math.ceil(upper.value) - 1
      : Math.floor(upper.value);
    return minimum > maximum;
  }
  return false;
}

function isOutermostCall(node: TSESTree.CallExpression): boolean {
  const expression = outerExpression(node);
  const parent = expression.parent;
  return !(
    parent?.type === AST_NODE_TYPES.MemberExpression &&
    parent.object === expression &&
    parent.parent?.type === AST_NODE_TYPES.CallExpression &&
    parent.parent.callee === parent
  );
}

export default createRule<Options, MessageIds>({
  name: "no-impossible-zod-literal-bounds",
  documentation: NO_IMPOSSIBLE_ZOD_LITERAL_BOUNDS_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow same-chain literal Zod bounds whose accepted set is mathematically empty.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          delegateRealContradictions: {
            type: "boolean",
            description:
              "Let enabled upstream zod/no-conflicting-checks own explicit real-bound contradictions.",
          },
        },
      },
    ],
    messages: {
      impossibleBounds:
        "This Zod {{kind}} schema accepts no values: {{lower}} conflicts with {{upper}}.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
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
        const variable = scope.variables.find(
          (candidate) => candidate.name === node.name,
        );
        if (variable !== undefined) {
          return variable.defs.some(
            (definition) => definition.name === binding,
          );
        }
        scope = scope.upper;
      }
      return false;
    }

    function readChain(node: TSESTree.CallExpression): Chain | null {
      const calls: { method: string; node: TSESTree.CallExpression }[] = [];
      let current = node;
      while (true) {
        const kind = baseKind(current);
        if (kind !== null) return { calls, kind };
        const callee = unwrapExpression(current.callee);
        const calleeReceiver =
          callee.type === AST_NODE_TYPES.MemberExpression
            ? unwrapExpression(callee.object)
            : callee;
        if (
          callee.type !== AST_NODE_TYPES.MemberExpression ||
          calleeReceiver.type !== AST_NODE_TYPES.CallExpression
        ) {
          return null;
        }
        const method = ASTUtils.getPropertyName(callee);
        if (method === null) return null;
        calls.push({ method, node: current });
        current = calleeReceiver;
      }
    }

    function baseKind(node: TSESTree.CallExpression): SchemaKind | null {
      const callee = unwrapExpression(node.callee);

      const calleeReceiver =
        callee.type === AST_NODE_TYPES.MemberExpression
          ? unwrapExpression(callee.object)
          : callee;
      if (callee.type === AST_NODE_TYPES.Identifier) {
        return resolvesToTrackedImport(callee)
          ? (constructors.get(callee.name) ?? null)
          : null;
      }
      if (
        callee.type !== AST_NODE_TYPES.MemberExpression ||
        calleeReceiver.type !== AST_NODE_TYPES.Identifier ||
        !namespaces.has(calleeReceiver.name) ||
        !resolvesToTrackedImport(calleeReceiver)
      ) {
        return null;
      }
      const name = ASTUtils.getPropertyName(callee);
      return name === null ? null : (KINDS.get(name) ?? null);
    }

    function isInsideReshapingCall(node: TSESTree.CallExpression): boolean {
      let child: TSESTree.Node = node;
      let parent = child.parent;
      while (parent !== undefined && parent.type !== AST_NODE_TYPES.Program) {
        if (parent.type === AST_NODE_TYPES.CallExpression) {
          const callee = unwrapExpression(parent.callee);
          const calleeReceiver =
            callee.type === AST_NODE_TYPES.MemberExpression
              ? unwrapExpression(callee.object)
              : callee;
          if (
            callee.type === AST_NODE_TYPES.MemberExpression &&
            RESHAPING_METHODS.has(ASTUtils.getPropertyName(callee) ?? "") &&
            (calleeReceiver.type === AST_NODE_TYPES.CallExpression ||
              (calleeReceiver.type === AST_NODE_TYPES.Identifier &&
                namespaces.has(calleeReceiver.name) &&
                resolvesToTrackedImport(calleeReceiver)))
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

    function contradiction(
      chain: Chain,
    ): { lower: Bound; upper: Bound } | null {
      const bounds = readConstraints(chain);
      if (bounds === null) return null;
      let { lower, upper } = bounds;
      const { integer, numeric } = bounds;
      if (
        isRealEmpty(lower, upper) &&
        ((numeric && integer) || options?.delegateRealContradictions === true)
      ) {
        return null;
      }
      if (chain.kind === "int32" || chain.kind === "uint32") {
        lower = strongerLower(lower, {
          exclusive: false,
          label: `${chain.kind}() minimum`,
          value: chain.kind === "int32" ? -(2 ** 31) : 0,
        });
        upper = strongerUpper(upper, {
          exclusive: false,
          label: `${chain.kind}() maximum`,
          value: chain.kind === "int32" ? 2 ** 31 - 1 : 2 ** 32 - 1,
        });
      }
      return isEmpty(lower, upper, integer) && lower !== null && upper !== null
        ? { lower, upper }
        : null;
    }

    function readConstraints(chain: Chain): ChainBounds | null {
      const numeric = chain.kind !== "string" && chain.kind !== "array";
      const allowed = numeric ? NUMBER_METHODS : LENGTH_METHODS;
      let lower: Bound | null = null;
      let upper: Bound | null = null;
      let integer = chain.kind !== "number";

      function addBound(
        method: string,
        semantic: ReturnType<typeof zeroBoundSemantic>,
        value: number,
      ): void {
        const label = `${method}(${String(value)})`;
        if (semantic !== null) {
          if (semantic.lower) {
            lower = strongerLower(lower, {
              exclusive: semantic.exclusive,
              label: `${method}()`,
              value,
            });
          } else {
            upper = strongerUpper(upper, {
              exclusive: semantic.exclusive,
              label: `${method}()`,
              value,
            });
          }
        } else if (method === "length") {
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

      for (const { method, node } of chain.calls) {
        if (!allowed.has(method)) return null;
        if (method === "int") {
          if (node.arguments.length !== 0) return null;
          integer = true;
          continue;
        }
        const semantic = zeroBoundSemantic(method);
        const value = semantic?.value ?? finiteNumber(node.arguments[0]);
        if (value === null) return null;
        if (!numeric && value < 0) {
          return null;
        }
        if (semantic !== null && node.arguments.length !== 0) return null;
        addBound(method, semantic, value);
      }
      return { integer, lower, numeric, upper };
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
          } else if (imported !== null && KINDS.has(imported)) {
            const kind = KINDS.get(imported);
            if (kind !== undefined)
              constructors.set(specifier.local.name, kind);
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

function zeroBoundSemantic(
  method: string,
): { exclusive: boolean; lower: boolean; value: number } | null {
  return method === "positive"
    ? { exclusive: true, lower: true, value: 0 }
    : method === "nonnegative"
      ? { exclusive: false, lower: true, value: 0 }
      : method === "negative"
        ? { exclusive: true, lower: false, value: 0 }
        : method === "nonpositive"
          ? { exclusive: false, lower: false, value: 0 }
          : null;
}
