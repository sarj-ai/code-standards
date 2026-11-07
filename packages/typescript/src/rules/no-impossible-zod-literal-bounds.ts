/**
 * @fileoverview no-impossible-zod-literal-bounds — literal Zod bounds must admit at least one value.
 *
 * Port of the 18.x `no-impossible-zod-literal-bounds` rule. Untyped.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";

const NAME = "no-impossible-zod-literal-bounds";

type Identifier = Extract<Node, { type: "Identifier" }>;
type Options = readonly [{ readonly delegateRealContradictions?: boolean }?];
type SchemaKind = "array" | "number" | "string" | "integer" | "int32" | "uint32";

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
  readonly calls: readonly { method: string; node: ESTree.CallExpression }[];
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
type ZeroBound = { readonly exclusive: boolean; readonly lower: boolean; readonly value: number };

/** The sign methods, each a bound at zero. */
const ZERO_BOUNDS: ReadonlyMap<string, ZeroBound> = new Map([
  ["positive", { exclusive: true, lower: true, value: 0 }],
  ["nonnegative", { exclusive: false, lower: true, value: 0 }],
  ["negative", { exclusive: true, lower: false, value: 0 }],
  ["nonpositive", { exclusive: false, lower: false, value: 0 }],
]);
const RESHAPING_METHODS: ReadonlySet<string> = new Set([
  "pipe",
  "preprocess",
  "transform",
]);

function finiteNumber(argument: ESTree.Argument | undefined): number | null {
  if (argument === undefined) return null;
  const node = unwrapExpression(argument);
  const signed = node.type === "UnaryExpression" && (node.operator === "-" || node.operator === "+");
  const literal = signed ? unwrapExpression(node.argument) : node;
  if (literal.type !== "Literal" || typeof literal.value !== "number") return null;
  const value = signed && node.operator === "-" ? -literal.value : literal.value;
  return Number.isFinite(value) ? value : null;
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

function isOutermostCall(node: ESTree.CallExpression): boolean {
  const expression = outerExpression(node);
  const parent = parentOf(expression);
  if (parent?.type !== "MemberExpression" || parent.object !== expression) return true;
  const grandparent = parentOf(parent);
  return !(grandparent?.type === "CallExpression" && grandparent.callee === parent);
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    docs: {
      description:
        "Disallow same-chain literal Zod bounds whose accepted set is mathematically empty.",
      url: docsUrl(NAME),
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
  createOnce(context) {
    let sourceCode: SourceCode;
    let options: Options[0];
    let namespaces = new Set<string>();
    let constructors = new Map<string, SchemaKind>();
    let preprocessors = new Set<string>();
    let importBindings = new Map<string, Identifier>();

    function resolvesToTrackedImport(node: Identifier): boolean {
      const binding = importBindings.get(node.name);
      return binding !== undefined &&
        (findVariable(sourceCode.getScope(node), node.name)?.defs.some((definition) => definition.name === binding) ?? false);
    }

    function isTrackedNamespace(node: Node): boolean {
      return node.type === "Identifier" && namespaces.has(node.name) && resolvesToTrackedImport(node);
    }

    function readChain(node: ESTree.CallExpression): Chain | null {
      const calls: { method: string; node: ESTree.CallExpression }[] = [];
      let current = node;
      while (true) {
        const kind = baseKind(current);
        if (kind !== null) return { calls, kind };
        const callee = unwrapExpression(current.callee);
        if (callee.type !== "MemberExpression") return null;
        const receiver = unwrapExpression(callee.object);
        const method = getPropertyName(callee);
        if (receiver.type !== "CallExpression" || method === null) return null;
        calls.push({ method, node: current });
        current = receiver;
      }
    }

    function baseKind(node: ESTree.CallExpression): SchemaKind | null {
      const callee = unwrapExpression(node.callee);
      if (callee.type === "Identifier") {
        const kind = constructors.get(callee.name);
        return kind !== undefined && resolvesToTrackedImport(callee) ? kind : null;
      }
      if (callee.type !== "MemberExpression" || !isTrackedNamespace(unwrapExpression(callee.object))) return null;
      const name = getPropertyName(callee);
      return name === null ? null : (KINDS.get(name) ?? null);
    }

    function isInsideReshapingCall(node: ESTree.CallExpression): boolean {
      for (let parent = parentOf(node); parent !== null && parent.type !== "Program"; parent = parentOf(parent)) {
        if (parent.type === "CallExpression" && isReshapingCall(parent)) return true;
      }
      return false;
    }

    /** `.pipe()`, `.transform()` or `.preprocess()` on a schema or namespace, or an imported `preprocess()`. */
    function isReshapingCall(call: ESTree.CallExpression): boolean {
      const callee = unwrapExpression(call.callee);
      if (callee.type === "Identifier") return preprocessors.has(callee.name) && resolvesToTrackedImport(callee);
      if (callee.type !== "MemberExpression" || !RESHAPING_METHODS.has(getPropertyName(callee) ?? "")) return false;
      const receiver = unwrapExpression(callee.object);
      return receiver.type === "CallExpression" || isTrackedNamespace(receiver);
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
        semantic: ZeroBound | null,
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
        const semantic = ZERO_BOUNDS.get(method) ?? null;
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
      before() {
        sourceCode = context.sourceCode;
        options = context.options[0] as Options[0];
        namespaces = new Set();
        constructors = new Map();
        preprocessors = new Set();
        importBindings = new Map();
        const file = { filename: context.filename, cwd: context.cwd };
        return !(isTestFile(file) || isGeneratedFile(file, sourceCode.text));
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          const local = specifier.local;
          const imported = specifier.type === "ImportSpecifier" ? importSpecifierName(specifier) : null;
          const kind = imported === null ? undefined : KINDS.get(imported);
          // A namespace or default import is the `z` namespace.
          if (imported === null || imported === "z") namespaces.add(local.name);
          else if (kind !== undefined) constructors.set(local.name, kind);
          else if (imported === "preprocess") preprocessors.add(local.name);
          else continue;
          importBindings.set(local.name, local);
        }
      },
      CallExpression(node: ESTree.CallExpression): void {
        // Every chain base resolves through a tracked Zod import; the ancestor walk runs last.
        if (importBindings.size === 0 || !isOutermostCall(node)) return;
        const chain = readChain(node);
        if (chain === null || isInsideReshapingCall(node)) return;
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
