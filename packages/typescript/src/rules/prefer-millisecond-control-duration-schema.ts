/**
 * @fileoverview prefer-millisecond-control-duration-schema — second-granularity control fields make application API timing imprecise.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-millisecond-control-duration-schema.test.ts
 */

import {
  ASTUtils,
  AST_NODE_TYPES,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "preferMilliseconds";
type Options = readonly [];

export const PREFER_MILLISECOND_CONTROL_DURATION_SCHEMA_DOCUMENTATION = {
  summary: "Require application-owned Zod control-duration fields to use millisecond granularity.",
  rationale:
    "Second-granularity timeout and scheduling controls lose precision and invite implicit unit conversion at API boundaries. Encoding milliseconds in the schema keeps the unit explicit and composes with platform timing APIs.",
  remediation:
    "Rename the field with an `Ms`/`_ms` suffix and express its bounds and default in milliseconds; update the owning API contract rather than converting in application code.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Only direct identifier keys in application-owned z.object/z.strictObject schemas are checked.",
    "The rule covers control timings such as timeout, delay, interval, backoff, TTL, lease, heartbeat, debounce, and throttle; observed durations and business-domain periods are excluded.",
    "Quoted/computed protocol keys, generated/vendor code, tests, fixtures, and non-Zod schemas are excluded.",
  ],
  examples: [
    {
      id: "millisecond-timeout-schema",
      title: "Encode control timing in milliseconds",
      outcome: "no-match",
      files: [
        {
          path: "src/request.ts",
          source: "import { z } from 'zod';\nexport const RequestSchema = z.object({ timeoutMs: z.number().int().min(1) });",
        },
      ],
      focusPath: "src/request.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "second-timeout-schema",
      title: "Do not expose second-granularity timeout controls",
      outcome: "match",
      files: [
        {
          path: "src/request.ts",
          source: "import { z } from 'zod';\nexport const RequestSchema = z.object({ timeout_seconds: z.number().int().min(1) });",
        },
      ],
      focusPath: "src/request.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const CONTROL_SECONDS_RE =
  /(?:^|_)(?:timeout|delay|interval|backoff|ttl|lease|heartbeat|debounce|throttle)_seconds$/i;
const CONTROL_SECONDS_CAMEL_RE =
  /(?:timeout|delay|interval|backoff|ttl|lease|heartbeat|debounce|throttle)Seconds$/i;

function directIdentifierKey(node: TSESTree.Property): TSESTree.Identifier | null {
  return !node.computed && node.key.type === AST_NODE_TYPES.Identifier ? node.key : null;
}

export default createRule<Options, MessageIds>({
  name: "prefer-millisecond-control-duration-schema",
  documentation: PREFER_MILLISECOND_CONTROL_DURATION_SCHEMA_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: PREFER_MILLISECOND_CONTROL_DURATION_SCHEMA_DOCUMENTATION.summary },
    schema: [],
    messages: {
      preferMilliseconds:
        "Zod control-duration field `{{name}}` uses seconds; define the owning API contract in milliseconds with an `Ms`/`_ms` suffix.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isGeneratedFile(context.filename, context.sourceCode.text) ||
      isTestFile(context.filename, ["fixtureTree"])
    ) {
      return {};
    }

    const zodNamespaces = new Set<TSESLint.Scope.Variable>();
    const objectFactories = new Set<TSESLint.Scope.Variable>();

    function binding(identifier: TSESTree.Identifier): TSESLint.Scope.Variable | null {
      return ASTUtils.findVariable(context.sourceCode.getScope(identifier), identifier.name);
    }

    function record(target: Set<TSESLint.Scope.Variable>, identifier: TSESTree.Identifier): void {
      const variable = binding(identifier);
      if (variable !== null) target.add(variable);
    }

    function isZodObjectCall(node: TSESTree.CallExpression): boolean {
      const callee = node.callee;
      if (callee.type === AST_NODE_TYPES.Identifier) {
        const variable = binding(callee);
        return variable !== null && objectFactories.has(variable);
      }
      if (
        callee.type !== AST_NODE_TYPES.MemberExpression ||
        callee.computed ||
        callee.object.type !== AST_NODE_TYPES.Identifier ||
        callee.property.type !== AST_NODE_TYPES.Identifier ||
        (callee.property.name !== "object" && callee.property.name !== "strictObject")
      ) {
        return false;
      }
      const variable = binding(callee.object);
      return variable !== null && zodNamespaces.has(variable);
    }

    return {
      ImportDeclaration(node: TSESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
            (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
              specifier.imported.type === AST_NODE_TYPES.Identifier &&
              specifier.imported.name === "z")
          ) {
            record(zodNamespaces, specifier.local);
          } else if (
            specifier.type === AST_NODE_TYPES.ImportSpecifier &&
            specifier.imported.type === AST_NODE_TYPES.Identifier &&
            (specifier.imported.name === "object" || specifier.imported.name === "strictObject")
          ) {
            record(objectFactories, specifier.local);
          }
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        if (!isZodObjectCall(node)) return;
        const shape = node.arguments[0];
        if (shape?.type !== AST_NODE_TYPES.ObjectExpression) return;
        for (const member of shape.properties) {
          if (member.type !== AST_NODE_TYPES.Property) continue;
          const key = directIdentifierKey(member);
          if (
            key === null ||
            (!CONTROL_SECONDS_RE.test(key.name) && !CONTROL_SECONDS_CAMEL_RE.test(key.name))
          ) {
            continue;
          }
          context.report({ node: key, messageId: "preferMilliseconds", data: { name: key.name } });
        }
      },
    };
  },
});
