/**
 * @fileoverview no-reduce-accumulator-copy — avoid copying the accumulator on each reduction.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-reduce-accumulator-copy.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import type { ESTree, SourceCode, Variable } from "@oxlint/plugins";

import {
  arrayMethodTarget,
  isKnownArrayExpression,
  resolveArrayBinding,
  unwrapArrayExpression,
} from "./_array-method.js";

function enclosingReducer(node: ESTree.Node) {
  let parent = node.parent;
  while (parent !== null) {
    if (parent.type === "FunctionDeclaration") return null;
    if (
      parent.type === "ArrowFunctionExpression" ||
      parent.type === "FunctionExpression"
    ) {
      return reducerCallback(parent);
    }
    parent = parent.parent;
  }
  return null;
}

/** Match the inline callback against its owning reduce call. */
function reducerCallback(
  callback: ESTree.ArrowFunctionExpression | ESTree.Function,
) {
  let owner: ESTree.Node | null = callback.parent;
  while (owner !== null && unwrapArrayExpression(owner) === callback)
    owner = owner.parent;
  if (owner?.type !== "CallExpression") return null;
  const method = arrayMethodTarget(owner.callee);
  const firstArgument = owner.arguments[0];
  if (
    method === null ||
    (method.name !== "reduce" && method.name !== "reduceRight") ||
    owner.arguments.length > 2 ||
    firstArgument === undefined ||
    unwrapArrayExpression(firstArgument) !== callback
  )
    return null;
  const firstParameter = callback.params[0];
  const accumulator =
    firstParameter?.type === "AssignmentPattern"
      ? firstParameter.left
      : firstParameter;
  if (accumulator?.type !== "Identifier") return null;
  return { callback, accumulator, initialValue: owner.arguments[1] };
}

function referencesAccumulator(
  sourceCode: SourceCode,
  node: ESTree.Node,
  accumulator: Variable,
  visited = new Set<Variable>(),
): boolean {
  const variable = resolveArrayBinding(sourceCode, node);
  if (variable === null || visited.has(variable)) return false;
  if (variable === accumulator) return true;
  visited.add(variable);
  if (
    variable.references.some(
      (reference) => reference.isWrite() && !reference.init,
    )
  )
    return false;
  for (const definition of variable.defs) {
    if (
      definition.type === "Variable" &&
      definition.node.type === "VariableDeclarator" &&
      definition.node.id.type === "Identifier" &&
      definition.node.init !== null &&
      definition.node.parent.type === "VariableDeclaration" &&
      definition.node.parent.kind === "const"
    ) {
      return referencesAccumulator(
        sourceCode,
        definition.node.init,
        accumulator,
        visited,
      );
    }
  }
  return false;
}

function isGlobalCopyOwner(
  sourceCode: SourceCode,
  node: ESTree.Node,
  name: string,
): boolean {
  node = unwrapArrayExpression(node);
  if (node.type !== "Identifier" || node.name !== name) return false;
  const variable = resolveArrayBinding(sourceCode, node);
  return variable === null || variable.defs.length === 0;
}

export const NO_REDUCE_ACCUMULATOR_COPY_DOCUMENTATION = {
  summary:
    "Review copies of the accumulated collection inside a built-in reduce callback.",
  rationale:
    "Copying a growing accumulator at every step can make collection quadratic instead of linear in its output size.",
  remediation:
    "Use map or flatMap where their semantics match, or append into a fresh locally owned accumulator. Preserve retained snapshots and shared state.",
  category: "performance",
  limitations: [
    "Inline reduce/reduceRight callbacks are identified by syntax, including custom methods. Stable accumulator aliases and local array seed evidence are followed through lexical scopes.",
    "Object.assign to a literal target, Array.from, and concat/slice/toSpliced/toSorted/toReversed/with copies are checked. Native oxc/no-accumulating-spread owns spread accumulation and loop copies.",
    "Imported seeds and named callbacks are not resolved. Nested functions and reassigned aliases are excluded. A copy calls for review, not proof of measured latency; no autofix changes ownership.",
  ],
  examples: [
    {
      id: "copy-rows",
      title: "Repeated concatenation copies prior report rows",
      outcome: "match",
      files: [
        {
          path: "src/reports.ts",
          source:
            "declare const pages: string[][];\nconst rows = pages.reduce<string[]>((acc, page) => acc.concat(page), []);",
        },
      ],
      focusPath: "src/reports.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "flatten-rows",
      title: "Flatten report rows without copying the accumulated prefix",
      outcome: "no-match",
      files: [
        {
          path: "src/reports.ts",
          source:
            "declare const pages: string[][];\nconst rows = pages.flatMap(page => page);",
        },
      ],
      focusPath: "src/reports.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

/** Reject non-spread copies of reducer accumulators; pair with oxc/no-accumulating-spread. */
export default createRule({
  name: "no-reduce-accumulator-copy",
  documentation: NO_REDUCE_ACCUMULATOR_COPY_DOCUMENTATION,
  defaultOptions: [],
  meta: {
    type: "problem",
    docs: { description: NO_REDUCE_ACCUMULATOR_COPY_DOCUMENTATION.summary },
    messages: {
      copy: "Do not copy the reducer accumulator on every iteration; growing copies can cause quadratic work. Mutate a fresh, locally owned accumulator and return it, or use an iterator pipeline/flatMap.",
    },
  },
  createOnce(context) {
    let generated = false;
    return {
      Program(): void {
        generated = isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text);
      },
      CallExpression(node) {
        if (generated) return;
        const method = arrayMethodTarget(node.callee);
        if (method === null) return;
        const reducer = enclosingReducer(node);
        if (reducer === null) return;
        const accumulator = context.sourceCode
          .getDeclaredVariables(reducer.callback)
          .find((variable) =>
            variable.identifiers.some(
              (identifier) => identifier.start === reducer.accumulator.start,
            ),
          );
        if (accumulator === undefined) return;
        const isAccumulator = (expression: ESTree.Node) =>
          referencesAccumulator(context.sourceCode, expression, accumulator);
        let copiesAccumulator = false;
        if (
          method.name === "assign" &&
          isGlobalCopyOwner(context.sourceCode, method.object, "Object")
        ) {
          const target = node.arguments[0];
          copiesAccumulator =
            target !== undefined &&
            unwrapArrayExpression(target).type === "ObjectExpression" &&
            node.arguments.slice(1).some(isAccumulator);
        } else if (
          method.name === "from" &&
          isGlobalCopyOwner(context.sourceCode, method.object, "Array")
        ) {
          const source = node.arguments[0];
          copiesAccumulator = source !== undefined && isAccumulator(source);
        } else if (
          [
            "concat",
            "slice",
            "toSpliced",
            "toSorted",
            "toReversed",
            "with",
          ].includes(method.name)
        ) {
          const initialValue = reducer.initialValue;
          const arrayAccumulator =
            initialValue !== undefined &&
            isKnownArrayExpression(context.sourceCode, initialValue);
          copiesAccumulator = arrayAccumulator && isAccumulator(method.object);
        }
        if (copiesAccumulator) context.report({ node, messageId: "copy" });
      },
    };
  },
});
