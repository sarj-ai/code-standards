/**
 * @fileoverview prefer-configured-cloud-scope — keep outgoing cloud account scope in validated deployment configuration.
 */

import {
  defineRule,
  type ESTree,
  type Identifier,
  type Node,
  type SourceCode,
  type TsVariable,
} from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, staticPropertyName } from "../utils/static-string.js";

const NAME = "prefer-configured-cloud-scope";
const ACCOUNT_PREFIX = "https://api.cloudflare.com/client/v4/accounts/";
const ACCOUNT_URL =
  /^https:\/\/api\.cloudflare\.com\/client\/v4\/accounts\/[a-fA-F\d]{32}(?=\/|[?#]|$)/u;
const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set(["globalThis", "global", "self", "window"]);

interface UrlPart {
  readonly text: string;
  readonly source: Node | null;
}

const UNKNOWN: readonly UrlPart[] = [{ text: "\0", source: null }];

function accountSource(parts: readonly UrlPart[]): Node | null {
  if (!ACCOUNT_URL.test(parts.map((part) => part.text).join(""))) return null;
  let offset = 0;
  for (const part of parts) {
    if (offset + part.text.length > ACCOUNT_PREFIX.length) return part.source;
    offset += part.text.length;
  }
  return null;
}

function boundedParts(parts: readonly UrlPart[]): readonly UrlPart[] {
  return parts.length <= 128 && parts.reduce((size, part) => size + part.text.length, 0) <= 8192
    ? parts
    : UNKNOWN;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Prefer validated deployment configuration for account scope in outgoing cloud management requests.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      configuredScope:
        "This outgoing Cloudflare management request uses a source-literal account scope. Load the account ID into one shared Zod-validated settings object at startup, then inject or import it; keep independent security allowlists intact.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    const reported = new Set<Node>();
    const requests: ESTree.CallExpression[] = [];
    let fetchOverridden = false;
    let nodesRemaining = 0;

    function bindingOf(node: Identifier): TsVariable | null {
      return findVariable(sourceCode.getScope(node), node.name);
    }

    function unshadowed(node: Identifier): boolean {
      const binding = bindingOf(node);
      return binding === null || binding.defs.length === 0;
    }

    function globalReceiver(node: Node): boolean {
      return node.type === "Identifier" && GLOBAL_RECEIVERS.has(node.name) && unshadowed(node);
    }

    function outgoingFetch(node: Node, seen = new Set<TsVariable>()): boolean {
      const callee = unwrapExpression(node);
      if (callee.type === "MemberExpression") {
        return globalReceiver(callee.object) && staticPropertyName(callee, sourceCode) === "fetch";
      }
      if (callee.type !== "Identifier") return false;
      const binding = bindingOf(callee);
      if (binding === null || binding.defs.length === 0) return callee.name === "fetch";
      if (
        seen.has(binding) ||
        seen.size >= 16 ||
        binding.defs.length !== 1 ||
        binding.references.some((ref) => ref.isWrite() && ref.init !== true)
      )
        return false;
      const next = new Set([...seen, binding]);
      const [definition] = binding.defs;
      if (definition?.type === "Parameter") {
        const parameter = parentOf(definition.name);
        return (
          parameter?.type === "AssignmentPattern" &&
          parameter.left === definition.name &&
          outgoingFetch(parameter.right, next)
        );
      }
      if (
        definition?.type !== "Variable" ||
        definition.parent?.type !== "VariableDeclaration" ||
        definition.parent.kind !== "const"
      )
        return false;
      const declarator = definition.node as ESTree.VariableDeclarator;
      return (
        declarator.id.type === "Identifier" &&
        declarator.init !== null &&
        outgoingFetch(declarator.init, next)
      );
    }

    function checkWrite(target: Node, depth = 0): void {
      if (depth >= 16) {
        fetchOverridden = true;
        return;
      }
      const value = unwrapExpression(target);
      switch (value.type) {
        case "Identifier":
          fetchOverridden ||=
            (value.name === "fetch" || GLOBAL_RECEIVERS.has(value.name)) && unshadowed(value);
          return;
        case "MemberExpression":
          if (globalReceiver(value.object)) {
            const name = staticPropertyName(value, sourceCode);
            fetchOverridden ||= name === null || name === "fetch" || GLOBAL_RECEIVERS.has(name);
          }
          return;
        case "ObjectPattern":
          for (const property of value.properties)
            checkWrite(
              property.type === "RestElement" ? property.argument : property.value,
              depth + 1,
            );
          return;
        case "ArrayPattern":
          for (const element of value.elements)
            if (element !== null) checkWrite(element, depth + 1);
          return;
        case "AssignmentPattern":
          checkWrite(value.left, depth + 1);
          return;
        case "RestElement":
          checkWrite(value.argument, depth + 1);
          return;
      }
    }

    function urlParts(node: Node, seen = new Set<TsVariable>(), depth = 0): readonly UrlPart[] {
      if (depth >= 16 || nodesRemaining-- <= 0) return UNKNOWN;
      const value = unwrapExpression(node);
      if (value.type === "Literal" && typeof value.value === "string") {
        return boundedParts([{ text: value.value, source: value }]);
      }
      if (value.type === "Identifier") {
        const binding = bindingOf(value);
        if (
          binding === null ||
          seen.has(binding) ||
          binding.defs.length !== 1 ||
          binding.references.some((ref) => ref.isWrite() && ref.init !== true)
        )
          return UNKNOWN;
        const [definition] = binding.defs;
        if (
          definition?.type !== "Variable" ||
          definition.parent?.type !== "VariableDeclaration" ||
          definition.parent.kind !== "const"
        )
          return UNKNOWN;
        const declarator = definition.node as ESTree.VariableDeclarator;
        if (declarator.id.type !== "Identifier" || declarator.init === null) return UNKNOWN;
        return urlParts(declarator.init, new Set([...seen, binding]), depth + 1);
      }
      if (value.type === "BinaryExpression" && value.operator === "+") {
        return boundedParts([
          ...urlParts(value.left, seen, depth + 1),
          ...urlParts(value.right, seen, depth + 1),
        ]);
      }
      if (value.type === "TemplateLiteral") return templateParts(value, seen, depth);
      return UNKNOWN;
    }

    function templateParts(
      value: ESTree.TemplateLiteral,
      seen: Set<TsVariable>,
      depth: number,
    ): readonly UrlPart[] {
      const parts: UrlPart[] = [];
      for (let index = 0; index < value.quasis.length; index++) {
        if (parts.length >= 128) return UNKNOWN;
        const quasi = value.quasis[index];
        if (quasi === undefined || quasi.value.cooked === null) return UNKNOWN;
        parts.push({ text: quasi.value.cooked, source: quasi });
        const expression = value.expressions[index];
        if (expression !== undefined) parts.push(...urlParts(expression, seen, depth + 1));
      }
      return boundedParts(parts);
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        reported.clear();
        requests.length = 0;
        fetchOverridden = false;
        const file = { filename: context.filename, cwd: context.cwd };
        return !isTestFile(file) && !isGeneratedFile(file, sourceCode.text);
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (outgoingFetch(node.callee)) requests.push(node);
      },
      AssignmentExpression(node: ESTree.AssignmentExpression): void {
        checkWrite(node.left);
      },
      UpdateExpression(node: ESTree.UpdateExpression): void {
        checkWrite(node.argument);
      },
      UnaryExpression(node: ESTree.UnaryExpression): void {
        if (node.operator === "delete") checkWrite(node.argument);
      },
      ForInStatement(node: ESTree.ForInStatement): void {
        if (node.left.type !== "VariableDeclaration") checkWrite(node.left);
      },
      ForOfStatement(node: ESTree.ForOfStatement): void {
        if (node.left.type !== "VariableDeclaration") checkWrite(node.left);
      },
      "Program:exit"(): void {
        if (fetchOverridden) return;
        for (const request of requests) {
          const [url] = request.arguments;
          if (url === undefined || url.type === "SpreadElement") continue;
          nodesRemaining = 256;
          const literal = accountSource(urlParts(url));
          if (literal === null || reported.has(literal)) continue;
          reported.add(literal);
          context.report({ node: literal, messageId: "configuredScope" });
        }
      },
    };
  },
});
