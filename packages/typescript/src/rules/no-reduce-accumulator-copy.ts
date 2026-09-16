/**
 * @fileoverview no-reduce-accumulator-copy — review copying of growing collection accumulators.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-reduce-accumulator-copy.test.ts
 */
import { AST_NODE_TYPES, ASTUtils, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

export const NO_REDUCE_ACCUMULATOR_COPY_DOCUMENTATION = {
  summary: "Review copies of the accumulated collection inside a built-in reduce callback.",
  rationale: "Copying a growing accumulator at every step can make collection quadratic instead of linear in its output size.",
  remediation: "Use map or flatMap where their semantics match, or append into a fresh locally owned accumulator. Preserve retained snapshots and shared state.",
  category: "performance",
  limitations: [
    "Requires type information proving the built-in Array or ReadonlyArray reduce/reduceRight method, an inline callback, and a fresh empty array or object-literal seed.",
    "Inspects direct accumulator spreads, Object.assign with a fresh object target, Array.from, and concat/slice/toSpliced/toSorted/toReversed/with calls. Aliases, named callbacks, nested functions, and loops are outside this rule.",
    "A copy is evidence for review, not proof of growth or measured latency. No autofix is provided: snapshots, side effects, indexes, and ownership can make mutation incorrect.",
  ],
  examples: [
    { id: "copy-rows", title: "Repeated concatenation copies prior report rows", outcome: "match", files: [{ path: "src/reports.ts", source: "declare const pages: string[][];\nconst rows = pages.reduce<string[]>((acc, page) => acc.concat(page), []);" }], focusPath: "src/reports.ts", expectedCount: 1, public: true },
    { id: "flatten-rows", title: "Flatten report rows without copying the accumulated prefix", outcome: "no-match", files: [{ path: "src/reports.ts", source: "declare const pages: string[][];\nconst rows = pages.flatMap(page => page);" }], focusPath: "src/reports.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

const COPY_METHODS: ReadonlySet<string> = new Set(["concat", "slice", "toSpliced", "toSorted", "toReversed", "with"]);

function methodName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) return node.property.name;
  if (node.computed && node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string") return node.property.value;
  return null;
}

export default createRule<[], "copy">({
  name: "no-reduce-accumulator-copy",
  documentation: NO_REDUCE_ACCUMULATOR_COPY_DOCUMENTATION,
  meta: { type: "suggestion", docs: { description: NO_REDUCE_ACCUMULATOR_COPY_DOCUMENTATION.summary }, schema: [], messages: {
    copy: "This reduce callback copies its accumulated collection. If it grows each iteration, use a direct transformation or append to a fresh local accumulator; preserve snapshot and callback semantics.",
  } },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    if (!context.sourceCode.parserServices?.program || !context.sourceCode.parserServices.esTreeNodeToTSNodeMap) return {};
    const services = ESLintUtils.getParserServices(context);
    const program = services.program;
    if (program === null) return {};
    const checker = program.getTypeChecker();
    return {
      CallExpression(node): void {
        if (node.callee.type !== AST_NODE_TYPES.MemberExpression ||
          !["reduce", "reduceRight"].includes(methodName(node.callee) ?? "") ||
          node.arguments.length !== 2) return;
        const seed = node.arguments[1];
        const arraySeed = seed?.type === AST_NODE_TYPES.ArrayExpression && seed.elements.length === 0;
        const objectSeed = seed?.type === AST_NODE_TYPES.ObjectExpression && seed.properties.length === 0;
        if (!arraySeed && !objectSeed) return;
        const callback = node.arguments[0];
        if (!callback || (callback.type !== AST_NODE_TYPES.ArrowFunctionExpression && callback.type !== AST_NODE_TYPES.FunctionExpression)) return;
        const parameter = callback.params[0];
        if (parameter?.type !== AST_NODE_TYPES.Identifier) return;
        const signature = checker.getResolvedSignature(services.esTreeNodeToTSNodeMap.get(node));
        const declaration = signature?.declaration;
        if (!declaration || !program.isSourceFileDefaultLibrary(declaration.getSourceFile()) ||
          !ts.isInterfaceDeclaration(declaration.parent) ||
          !["Array", "ReadonlyArray"].includes(declaration.parent.name.text)) return;
        const accumulator = context.sourceCode.getDeclaredVariables(callback).find(variable => variable.identifiers.includes(parameter));
        if (!accumulator || accumulator.references.some(reference => reference.isWrite())) return;
        const referencesAccumulator = (value: TSESTree.Node): boolean => value.type === AST_NODE_TYPES.Identifier &&
          ASTUtils.findVariable(context.sourceCode.getScope(value), value.name) === accumulator;
        const inspectCall = (current: TSESTree.CallExpression): void => {
          if (current.callee.type !== AST_NODE_TYPES.MemberExpression) return;
          const member = current.callee;
          const name = methodName(member);
          const directCopy = arraySeed && name !== null && COPY_METHODS.has(name) && referencesAccumulator(member.object);
          const globalArray = member.object.type === AST_NODE_TYPES.Identifier && member.object.name === "Array" &&
            !(ASTUtils.findVariable(context.sourceCode.getScope(member.object), "Array")?.defs.length);
          const fromCopy = arraySeed && name === "from" && globalArray && current.arguments[0] !== undefined && referencesAccumulator(current.arguments[0]);
          const globalObject = member.object.type === AST_NODE_TYPES.Identifier && member.object.name === "Object" &&
            !(ASTUtils.findVariable(context.sourceCode.getScope(member.object), "Object")?.defs.length);
          const target = current.arguments[0];
          const assignCopy = objectSeed && name === "assign" && globalObject && target?.type === AST_NODE_TYPES.ObjectExpression &&
            current.arguments.slice(1).some(referencesAccumulator);
          if (directCopy || fromCopy || assignCopy) context.report({ node: current, messageId: "copy" });
        };
        const inspect = (current: TSESTree.Node): void => {
          if (current !== callback.body && [AST_NODE_TYPES.ArrowFunctionExpression, AST_NODE_TYPES.FunctionExpression, AST_NODE_TYPES.FunctionDeclaration].some(kind => kind === current.type)) return;
          if (current.type === AST_NODE_TYPES.SpreadElement && ((arraySeed && current.parent.type === AST_NODE_TYPES.ArrayExpression) || (objectSeed && current.parent.type === AST_NODE_TYPES.ObjectExpression)) && referencesAccumulator(current.argument)) {
            context.report({ node: current, messageId: "copy" });
          }
          if (current.type === AST_NODE_TYPES.CallExpression) inspectCall(current);
          for (const key of context.sourceCode.visitorKeys[current.type] ?? []) {
            // ESLint visitor keys contain only AST children, never parent links.
            const child = (current as unknown as Record<string, unknown>)[key];
            if (Array.isArray(child)) {
              for (const item of child) if (item !== null && typeof item === "object" && "type" in item) inspect(item as TSESTree.Node);
            } else if (child !== null && typeof child === "object" && "type" in child) inspect(child as TSESTree.Node);
          }
        };
        inspect(callback.body);
      },
    };
  },
});
