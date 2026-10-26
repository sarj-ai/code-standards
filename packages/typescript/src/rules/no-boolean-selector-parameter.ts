/**
 * @fileoverview no-boolean-selector-parameter — preserve boolean data and required contracts while identifying operation selectors.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-boolean-selector-parameter.test.ts
 */
import {
  AST_NODE_TYPES,
  ASTUtils,
  ESLintUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";
import { rules as sonarRules } from "eslint-plugin-sonarjs";

import {
  isBooleanDataSelection,
  isEligibleBooleanSelector,
} from "./_boolean-selector-contract.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { literalSelectorFix } from "./_literal-selector-fix.js";
import { isGeneratedFile } from "./_paths.js";

type Options = readonly [];
type MessageIds = "booleanSelector";
interface NativeReport {
  readonly loc?: TSESTree.SourceLocation | TSESTree.Position;
}
const UPSTREAM_SELECTOR_RULE = sonarRules["no-selector-parameter"];

export const NO_BOOLEAN_SELECTOR_PARAMETER_DOCUMENTATION = {
  summary:
    "Prefer intention-revealing operations over a boolean parameter selecting between actions.",
  rationale:
    "A positional boolean hides which operation a caller requests. Splitting independent actions can make that intent explicit, while boolean data, pure mappings and externally required callback or method contracts remain valid.",
  remediation:
    "Consider separate named operations or an explicit domain mode. Review the public API and its callers manually; preserve required callback, setter and inherited contracts instead of wrapping them solely to silence the warning.",
  category: "maintainability",
  defaultLevel: "warning",
  autofix: "safe",
  limitations: [
    "Requires type information. Adapts maintained SonarJS S2301 for single-statement if/else or conditional bodies and adds expression-bodied arrow conditionals. Only a direct broad-boolean parameter or its negation is considered; optional, nullable, literal-only, generic, destructured and indirect predicate conditions are excluded.",
    "Preserves setters, pure mappings, selected pure data passed to one stable lexical operation or assigned to one simple target, independently authored callable and inherited member contracts, inline callbacks, and statically proven named callback references. Independent helpers remain checked in JSX files; callback identity is established from references rather than handler names.",
    "The upstream block-body detector still exempts literal on[A-Z] object properties; the concise-arrow extension does not infer a callback contract from that name. Multi-statement bodies, short-circuit guards, local parameter aliases and arbitrary control flow are not inferred. Noncomputed property reads count as data without proving getter effects; computed reads remain outside that exemption, including literal keys. Side-effect detection does not prove whether a called function is pure, and a warning requires manual design review. Generated files are excluded; tests remain checked.",
    "Automatic fixes only reuse two already authored private zero-argument ordinary operations returning primitive string literals. A complete comment-free four-declaration module must contain those operations, one private const broad-boolean arrow selecting their direct calls, and one exported zero-argument ordinary function with an explicit string-array return that calls the selector exclusively with literal true and false. Calls are routed to the existing named operations and the exclusively used selector declaration is removed. All other APIs, callbacks, dynamic arguments, contracts and operation bodies remain manual.",
  ],
  references: [
    "https://understandlegacycode.com/blog/what-is-wrong-with-boolean-parameters/",
    "https://martinfowler.com/bliki/FlagArgument.html",
    "https://github.com/SonarSource/SonarJS/tree/master/packages/analysis/src/jsts/rules/S2301",
  ],
  examples: [
    {
      id: "concise-boolean-dispatch",
      title: "Name the selected operation explicitly",
      outcome: "match",
      files: [
        {
          path: "src/book.ts",
          source:
            "const book = (premium: boolean) => premium ? premiumBook() : regularBook();",
        },
      ],
      focusPath: "src/book.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "boolean-value-mapping",
      title: "Boolean data may select a pure value",
      outcome: "no-match",
      files: [
        {
          path: "src/label.ts",
          source:
            'function label(enabled: boolean) { if (enabled) { return "Enabled"; } else { return "Disabled"; } }',
        },
      ],
      focusPath: "src/label.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Call the already named selected operations",
      outcome: "match",
      files: [
        {
          path: "src/book.ts",
          source:
            "function premiumBook() { return 'premium'; }\nfunction regularBook() { return 'regular'; }\nconst book = (premium: boolean) => premium ? premiumBook() : regularBook();\nexport function choices(): string[] { return [book(true), book(false), book(true)]; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/book.ts",
          source:
            "function premiumBook() { return 'premium'; }\nfunction regularBook() { return 'regular'; }\nexport function choices(): string[] { return [premiumBook(), regularBook(), premiumBook()]; }",
        },
      ],
      focusPath: "src/book.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-boolean-selector-parameter",
  documentation: NO_BOOLEAN_SELECTOR_PARAMETER_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_BOOLEAN_SELECTOR_PARAMETER_DOCUMENTATION.summary },
    schema: [],
    fixable: "code",
    messages: {
      booleanSelector:
        'Consider separate intention-revealing operations instead of using "{{parameterName}}" to select an action. Preserve required contracts and boolean data.',
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isGeneratedFile(context, context.sourceCode.text) ||
      !context.sourceCode.parserServices?.program
    )
      return {};
    const services = ESLintUtils.getParserServices(context);
    const reported = new Set<TSESTree.Identifier>();
    function report(identifier: TSESTree.Identifier): void {
      if (
        reported.has(identifier) ||
        !isDirectTest(identifier) ||
        !isEligibleBooleanSelector(identifier, context.sourceCode, services)
      )
        return;
      const selection = (
        identifier.parent.type === AST_NODE_TYPES.UnaryExpression
          ? identifier.parent
          : identifier
      ).parent;
      if (
        selection.type === AST_NODE_TYPES.ConditionalExpression &&
        isBooleanDataSelection(
          selection.consequent,
          selection.alternate,
          context.sourceCode,
          services,
        )
      )
        return;
      reported.add(identifier);
      const fix = literalSelectorFix(context.sourceCode, identifier);
      context.report({
        node: identifier,
        messageId: "booleanSelector",
        data: { parameterName: identifier.name },
        fix,
      });
    }
    function translate({ loc }: NativeReport): void {
      if (loc === undefined) return;
      const position = "start" in loc ? loc.start : loc;
      const identifier = context.sourceCode.getNodeByRangeIndex(
        context.sourceCode.getIndexFromLoc(position),
      );
      if (identifier?.type === AST_NODE_TYPES.Identifier) report(identifier);
    }
    // Native ESLint and TypeScript-ESTree expose different static listener types,
    // but the pinned detector consumes these original nodes and parser services.
    // The facade changes only reporting; it does not clone nodes or alter scopes.
    const nativeContext: unknown = Object.create(context, {
      report: { value: translate },
    });
    const nativeArguments: readonly unknown[] = [nativeContext];
    const listeners: unknown = Reflect.apply(
      UPSTREAM_SELECTOR_RULE.create.bind(UPSTREAM_SELECTOR_RULE),
      undefined,
      nativeArguments,
    );
    const native: TSESLint.RuleListener = {};
    if (typeof listeners !== "object" || listeners === null) return native;
    for (const selector of Object.keys(listeners)) {
      const listener: unknown = Reflect.get(listeners, selector);
      if (typeof listener === "function")
        native[selector] = (...nodes: unknown[]): void => {
          Reflect.apply(listener, undefined, nodes);
        };
    }
    return {
      ...native,
      ConditionalExpression(node) {
        native.ConditionalExpression?.(node);
        if (
          node.parent.type !== AST_NODE_TYPES.ArrowFunctionExpression ||
          node.parent.body !== node ||
          (!ASTUtils.hasSideEffect(node.consequent, context.sourceCode) &&
            !ASTUtils.hasSideEffect(node.alternate, context.sourceCode))
        )
          return;
        const callable = node.parent;
        if (
          (callable.parent.type === AST_NODE_TYPES.CallExpression &&
            callable.parent.arguments.includes(callable)) ||
          callable.parent.type === AST_NODE_TYPES.JSXExpressionContainer
        )
          return;
        const identifier = testIdentifier(node.test);
        if (identifier !== undefined) report(identifier);
      },
    };
  },
});

function testIdentifier(
  test: TSESTree.Expression,
): TSESTree.Identifier | undefined {
  const value =
    test.type === AST_NODE_TYPES.UnaryExpression && test.operator === "!"
      ? test.argument
      : test;
  return value.type === AST_NODE_TYPES.Identifier ? value : undefined;
}

function isDirectTest(identifier: TSESTree.Identifier): boolean {
  const test =
    identifier.parent.type === AST_NODE_TYPES.UnaryExpression &&
    identifier.parent.operator === "!"
      ? identifier.parent
      : identifier;
  return (
    (test.parent.type === AST_NODE_TYPES.IfStatement ||
      test.parent.type === AST_NODE_TYPES.ConditionalExpression) &&
    test.parent.test === test
  );
}
