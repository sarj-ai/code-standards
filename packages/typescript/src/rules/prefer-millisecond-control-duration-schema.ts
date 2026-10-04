/**
 * @fileoverview prefer-millisecond-control-duration-schema — second-granularity control fields make application API timing imprecise.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-millisecond-control-duration-schema.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Variable } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "preferMilliseconds";
type Options = readonly [];

export const PREFER_MILLISECOND_CONTROL_DURATION_SCHEMA_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Require application-owned Zod control-duration fields to use millisecond granularity.",
  rationale:
    "Second-granularity timeout and scheduling controls lose precision and invite implicit unit conversion at API boundaries. Encoding milliseconds in the schema keeps the unit explicit and composes with platform timing APIs.",
  remediation:
    "Rename the field with an `Ms`/`_ms` suffix and express its bounds and default in milliseconds; update the owning API contract rather than converting in application code.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Only direct identifier keys with recognizable numeric Zod leaves in application-owned z.object/z.strictObject schemas are checked; aliases and transformations are not inferred.",
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
          source: "import { z } from 'zod';\nexport const RequestSchema = z.object({ timeoutMs: z.number().int().min(1000).max(300000).default(30000) });",
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
          source: "import { z } from 'zod';\nexport const RequestSchema = z.object({ timeout_seconds: z.number().int().min(1).max(300).default(30) });",
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

function directIdentifierKey(node: ESTree.ObjectProperty): ESTree.BindingIdentifier | null {
  return !node.computed && node.key.type === "Identifier" ? node.key : null;
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
      isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text) ||
      isTestFile(sourceOrigin(context).filename, ["fixtureTree"])
    ) {
      return {};
    }

    const zodNamespaces = new Set<Variable>();
    const objectFactories = new Set<Variable>();
    const numberFactories = new Set<Variable>();

    function binding(identifier: ESTree.BindingIdentifier): Variable | null {
      return findVariable(context.sourceCode.getScope(identifier), identifier.name);
    }

    function record(target: Set<Variable>, identifier: ESTree.BindingIdentifier): void {
      const variable = binding(identifier);
      if (variable !== null) target.add(variable);
    }

    function isZodObjectCall(node: ESTree.CallExpression): boolean {
      const callee = node.callee;
      if (callee.type === "Identifier") {
        const variable = binding(callee);
        return variable !== null && objectFactories.has(variable);
      }
      if (
        callee.type !== "MemberExpression" ||
        callee.computed ||
        callee.object.type !== "Identifier" ||
        callee.property.type !== "Identifier" ||
        (callee.property.name !== "object" && callee.property.name !== "strictObject")
      ) {
        return false;
      }
      const variable = binding(callee.object);
      return variable !== null && zodNamespaces.has(variable);
    }

    function isNumericSchema(node: ESTree.Node): boolean {
      if (node.type !== "CallExpression") return false;
      const callee = node.callee;
      if (callee.type === "Identifier") {
        const variable = binding(callee);
        return variable !== null && numberFactories.has(variable);
      }
      if (callee.type !== "MemberExpression" || callee.computed ||
          callee.property.type !== "Identifier") return false;
      if (callee.object.type === "Identifier") {
        const variable = binding(callee.object);
        return callee.property.name === "number" && variable !== null && zodNamespaces.has(variable);
      }
      return ["int", "min", "max", "positive", "nonnegative", "finite", "multipleOf", "optional", "nullable", "nullish", "default", "describe", "brand", "readonly"].includes(callee.property.name) &&
        isNumericSchema(callee.object);
    }

    return {
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (specifier.type === "ImportSpecifier" && specifier.imported.type === "Identifier" && specifier.imported.name === "number") {
            record(numberFactories, specifier.local);
          }
          if (
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier" ||
            (specifier.type === "ImportSpecifier" &&
              specifier.imported.type === "Identifier" &&
              specifier.imported.name === "z")
          ) {
            record(zodNamespaces, specifier.local);
          } else if (
            specifier.type === "ImportSpecifier" &&
            specifier.imported.type === "Identifier" &&
            (specifier.imported.name === "object" || specifier.imported.name === "strictObject")
          ) {
            record(objectFactories, specifier.local);
          }
        }
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (!isZodObjectCall(node)) return;
        const shape = node.arguments[0];
        if (shape?.type !== "ObjectExpression") return;
        for (const member of shape.properties) {
          if (member.type !== "Property" || !isNumericSchema(member.value)) continue;
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
