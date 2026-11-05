/**
 * @fileoverview no-reduce-accumulator-copy — review copying of growing collection accumulators.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-reduce-accumulator-copy.test.ts
 */

import { getTypeServices } from "./_eslint-rule.js";


import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { forEachAstChild } from "./_for-each-ast-child.js";
import { literalIdentityReduceFix } from "./_literal-identity-reduce-fix.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { enclosingFunction, stableConstInitializer, typeOnlyReference } from "./_stable-value-binding.js";
import { unwrapExpression } from "./_unwrap-expression.js";

export const NO_REDUCE_ACCUMULATOR_COPY_DOCUMENTATION = {
  summary:
    "Review copies of the accumulated collection inside a built-in reduce callback.",
  rationale:
    "Copying a growing accumulator at every step can make collection quadratic instead of linear in its output size.",
  remediation:
    "Use map or flatMap where their semantics match, or append into a fresh locally owned accumulator. Preserve retained snapshots and shared state.",
  category: "performance",
  requiresTypeInformation: true,
  references: ["https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-reduce-accumulator-copy.ts"],
  autofix: "safe",
  limitations: [
    "Requires type information proving the built-in Array or ReadonlyArray reduce/reduceRight method, an inline callback, and a fresh empty array or object-literal seed, directly or through single-use stable const aliases.",
    "Inspects direct accumulator spreads, Object.assign with a fresh object target, Array.from, and concat/slice/toSpliced/toSorted/toReversed/with calls. Stable callback-local const accumulator aliases are resolved. Named callbacks, mutable/escaping seeds, nested functions, and loops remain outside this rule.",
    "A copy is evidence for review, not proof of growth or measured latency. Automatic edits only remove an exact identity reducer over a fresh nonempty literal-string array in a sole exported zero-argument function with an explicit string[] return. The direct literal return remains fresh on every call. Snapshots, aliases, callbacks, nonliteral values, reverse reduction, imports, comments and other control flow remain manual.",
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
    {
      id: "safe-autofix",
      title: "Return the existing fresh identity collection directly",
      outcome: "match",
      files: [
        {
          path: "src/reports.ts",
          source:
            "export function collect(): string[] { return ['a', 'b'].reduce<string[]>((acc, item) => [...acc, item], []); }",
        },
      ],
      fixedFiles: [
        {
          path: "src/reports.ts",
          source: "export function collect(): string[] { return ['a', 'b']; }",
        },
      ],
      focusPath: "src/reports.ts",
      expectedCount: 1,
    },
    {"id": "reducer-aliases-before", "scenarioId": "reducer-aliases", "title": "Retain fresh seed and accumulator identities — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "declare const pages: string[][]; const seed: string[] = []; pages.reduce((acc, page) => { const previous = acc; return [...previous, ...page]; }, seed);"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "reducer-aliases-after", "scenarioId": "reducer-aliases", "title": "Retain fresh seed and accumulator identities — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "declare const pages: string[][]; pages.flatMap(page => page);"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
  ],
} as const satisfies RuleDocumentation;

const COPY_METHODS: ReadonlySet<string> = new Set([
  "concat",
  "slice",
  "toSpliced",
  "toSorted",
  "toReversed",
  "with",
]);

export default createRule<[], "copy">({
  name: "no-reduce-accumulator-copy",
  documentation: NO_REDUCE_ACCUMULATOR_COPY_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: NO_REDUCE_ACCUMULATOR_COPY_DOCUMENTATION.summary },
    schema: [],
    messages: {
      copy: "This reduce callback copies its accumulated collection. If it grows each iteration, use a direct transformation or append to a fresh local accumulator; preserve snapshot and callback semantics.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    if (
      !context.sourceCode.parserServices?.program ||
      !context.sourceCode.parserServices.esTreeNodeToTSNodeMap
    )
      return {};
    const services = getTypeServices(context);
    const program = services.program;
    if (program === null) return {};
    const checker = program.getTypeChecker();
    const seedValue = (value: TSESTree.Node, seen = new Set<TSESTree.Node>()): TSESTree.Node | null => {
      value = unwrapExpression(value);
      if (seen.has(value)) return null;
      seen.add(value);
      if (value.type !== AST_NODE_TYPES.Identifier) return value;
      const local = stableConstInitializer(context.sourceCode, value);
      if (local === null || !local.variable.references.every(reference => reference.init === true ||
        typeOnlyReference(reference) || reference.identifier === value)) return null;
      return seedValue(local.value, seen);
    };
    return {
      CallExpression(node): void {
        if (
          node.callee.type !== AST_NODE_TYPES.MemberExpression ||
          !["reduce", "reduceRight"].includes(
            ASTUtils.getPropertyName(node.callee) ?? "",
          ) ||
          node.arguments.length !== 2
        )
          return;
        const argument = node.arguments[1];
        const seed = argument === undefined ? null : seedValue(argument);
        const arraySeed =
          seed?.type === AST_NODE_TYPES.ArrayExpression &&
          seed.elements.length === 0;
        const objectSeed =
          seed?.type === AST_NODE_TYPES.ObjectExpression &&
          seed.properties.length === 0;
        if (!arraySeed && !objectSeed) return;
        const callback = node.arguments[0];
        if (
          !callback ||
          (callback.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
            callback.type !== AST_NODE_TYPES.FunctionExpression)
        )
          return;
        const parameter = callback.params[0];
        if (parameter?.type !== AST_NODE_TYPES.Identifier) return;
        const signature = checker.getResolvedSignature(
          services.esTreeNodeToTSNodeMap.get(node),
        );
        const declaration = signature?.declaration;
        if (
          !declaration ||
          !program.isSourceFileDefaultLibrary(declaration.getSourceFile()) ||
          !ts.isInterfaceDeclaration(declaration.parent) ||
          !["Array", "ReadonlyArray"].includes(declaration.parent.name.text)
        )
          return;
        const accumulator = context.sourceCode
          .getDeclaredVariables(callback)
          .find((variable) => variable.identifiers.includes(parameter));
        if (
          !accumulator ||
          accumulator.references.some((reference) => reference.isWrite())
        )
          return;
        const fix = literalIdentityReduceFix(context.sourceCode, node);
        const referencesAccumulator = (value: TSESTree.Node, seen = new Set<TSESTree.Node>()): boolean => {
          value = unwrapExpression(value);
          if (value.type !== AST_NODE_TYPES.Identifier || seen.has(value)) return false;
          seen.add(value);
          if (ASTUtils.findVariable(context.sourceCode.getScope(value), value.name) === accumulator) return true;
          const local = stableConstInitializer(context.sourceCode, value);
          return local !== null && enclosingFunction(local.declaration) === callback && referencesAccumulator(local.value, seen);
        };
        const inspect = (current: TSESTree.Node): void => {
          if (
            current !== callback.body &&
            [
              AST_NODE_TYPES.ArrowFunctionExpression,
              AST_NODE_TYPES.FunctionExpression,
              AST_NODE_TYPES.FunctionDeclaration,
              AST_NODE_TYPES.ClassDeclaration,
              AST_NODE_TYPES.ClassExpression,
              AST_NODE_TYPES.ForStatement,
              AST_NODE_TYPES.ForInStatement,
              AST_NODE_TYPES.ForOfStatement,
              AST_NODE_TYPES.WhileStatement,
              AST_NODE_TYPES.DoWhileStatement,
            ].some((kind) => kind === current.type)
          )
            return;
          if (
            current.type === AST_NODE_TYPES.SpreadElement &&
            ((arraySeed &&
              current.parent.type === AST_NODE_TYPES.ArrayExpression) ||
              (objectSeed &&
                current.parent.type === AST_NODE_TYPES.ObjectExpression)) &&
            referencesAccumulator(current.argument)
          ) {
            context.report({
              node: current,
              messageId: "copy",
              fix,
            });
          }
          if (current.type === AST_NODE_TYPES.CallExpression)
            inspectCall(current);
          forEachAstChild(current, context.sourceCode.visitorKeys, inspect);
        };

        const inspectCall = (current: TSESTree.CallExpression): void => {
          if (current.callee.type !== AST_NODE_TYPES.MemberExpression) return;
          const member = current.callee;
          const name = ASTUtils.getPropertyName(member);
          const directCopy =
            arraySeed &&
            name !== null &&
            COPY_METHODS.has(name) &&
            referencesAccumulator(member.object);
          const globalArray =
            member.object.type === AST_NODE_TYPES.Identifier &&
            member.object.name === "Array" &&
            !ASTUtils.findVariable(
              context.sourceCode.getScope(member.object),
              "Array",
            )?.defs.length;
          const fromCopy =
            arraySeed &&
            name === "from" &&
            globalArray &&
            current.arguments[0] !== undefined &&
            referencesAccumulator(current.arguments[0]);
          const globalObject =
            member.object.type === AST_NODE_TYPES.Identifier &&
            member.object.name === "Object" &&
            !ASTUtils.findVariable(
              context.sourceCode.getScope(member.object),
              "Object",
            )?.defs.length;
          const target = current.arguments[0];
          const assignCopy =
            objectSeed &&
            name === "assign" &&
            globalObject &&
            target?.type === AST_NODE_TYPES.ObjectExpression &&
            current.arguments.slice(1).some(argument => referencesAccumulator(argument));
          if (directCopy || fromCopy || assignCopy)
            context.report({ node: current, messageId: "copy" });
        };
        inspect(callback.body);
      },
    };
  },
});
