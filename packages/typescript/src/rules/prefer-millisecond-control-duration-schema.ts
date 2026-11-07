/**
 * @fileoverview prefer-millisecond-control-duration-schema — second-granularity control fields make application API timing imprecise.
 *
 * Port of the 18.x `prefer-millisecond-control-duration-schema` rule.
 * The rule is untyped, so the port covers all of it.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-millisecond-control-duration-schema.test.ts
 */

import { defineRule, type ESTree, type Node, type TsVariable } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";

const NAME = "prefer-millisecond-control-duration-schema";

type Identifier = Extract<Node, { type: "Identifier" }>;

const CONTROL_SECONDS_RE =
  /(?:^|_)(?:timeout|delay|interval|backoff|ttl|lease|heartbeat|debounce|throttle)_seconds$/i;
const CONTROL_SECONDS_CAMEL_RE =
  /(?:timeout|delay|interval|backoff|ttl|lease|heartbeat|debounce|throttle)Seconds$/i;
const NUMERIC_REFINEMENTS: ReadonlySet<string> = new Set(["int", "min", "max", "positive", "nonnegative", "finite", "multipleOf", "optional", "nullable", "nullish", "default", "describe", "brand", "readonly"]);

function directIdentifierKey(node: ESTree.ObjectProperty): Identifier | null {
  return !node.computed && node.key.type === "Identifier" ? node.key : null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Require application-owned Zod control-duration fields to use millisecond granularity.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferMilliseconds:
        "Zod control-duration field `{{name}}` uses seconds; define the owning API contract in milliseconds with an `Ms`/`_ms` suffix.",
    },
  },
  createOnce(context) {
    let zodNamespaces = new Set<TsVariable>();
    let objectFactories = new Set<TsVariable>();
    let numberFactories = new Set<TsVariable>();

    function binding(identifier: Identifier): TsVariable | null {
      return findVariable(context.sourceCode.getScope(identifier), identifier.name);
    }

    function record(target: Set<TsVariable>, identifier: Identifier): void {
      const variable = binding(identifier);
      if (variable !== null) target.add(variable);
    }

    function isZodObjectCall(node: ESTree.CallExpression): boolean {
      const callee = unwrapExpression(node.callee);
      if (callee.type === "Identifier") {
        const variable = binding(callee);
        return variable !== null && objectFactories.has(variable);
      }
      if (callee.type !== "MemberExpression") return false;
      const calleeReceiver = unwrapExpression(callee.object);
      const method = getPropertyName(callee);
      if (calleeReceiver.type !== "Identifier" || (method !== "object" && method !== "strictObject")) return false;
      const variable = binding(calleeReceiver);
      return variable !== null && zodNamespaces.has(variable);
    }

    function isNumericSchema(node: Node): boolean {
      node = unwrapExpression(node);
      if (node.type !== "CallExpression") return false;
      const callee = unwrapExpression(node.callee);
      if (callee.type === "Identifier") {
        const variable = binding(callee);
        return variable !== null && numberFactories.has(variable);
      }
      const method = callee.type === "MemberExpression" ? getPropertyName(callee) : null;
      if (callee.type !== "MemberExpression" || method === null) return false;
      const calleeReceiver = unwrapExpression(callee.object);
      if (calleeReceiver.type === "Identifier") {
        const variable = binding(calleeReceiver);
        return method === "number" && variable !== null && zodNamespaces.has(variable);
      }
      return NUMERIC_REFINEMENTS.has(method) && isNumericSchema(calleeReceiver);
    }

    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (isGeneratedFile(file, context.sourceCode.text) || isTestFile(file, ["fixtureTree"])) return false;
        zodNamespaces = new Set();
        objectFactories = new Set();
        numberFactories = new Set();
        return undefined;
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          const importedName = specifier.type === "ImportSpecifier" ? importSpecifierName(specifier) : null;
          if (importedName === "number") record(numberFactories, specifier.local);
          if (
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier" ||
            importedName === "z"
          ) {
            record(zodNamespaces, specifier.local);
          } else if (importedName === "object" || importedName === "strictObject") {
            record(objectFactories, specifier.local);
          }
        }
      },
      CallExpression(node: ESTree.CallExpression): void {
        const shape = node.arguments[0];
        if (shape?.type !== "ObjectExpression" || !isZodObjectCall(node)) return;
        for (const member of shape.properties) {
          if (member.type !== "Property") continue;
          const key = directIdentifierKey(member);
          if (
            key === null ||
            (!CONTROL_SECONDS_RE.test(key.name) && !CONTROL_SECONDS_CAMEL_RE.test(key.name)) ||
            !isNumericSchema(member.value)
          ) {
            continue;
          }
          context.report({ node: key, messageId: "preferMilliseconds", data: { name: key.name } });
        }
      },
    };
  },
});
