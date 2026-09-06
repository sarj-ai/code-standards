/**
 * @fileoverview prefer-ecmascript-private-members — prefer runtime-enforced ECMAScript privacy to TypeScript-only `private`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-ecmascript-private-members.test.ts
 */

import {
  AST_NODE_TYPES,
  ESLintUtils,
  type ParserServicesWithTypeInformation,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import {
  convertibleMemberName,
  type PrivateConvertibleMember,
} from "./_class-private.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "preferEcmascriptPrivate";
type Options = readonly [];

export const PREFER_ECMASCRIPT_PRIVATE_MEMBERS_DOCUMENTATION = {
  summary: "Prefer ECMAScript `#private` class members over TypeScript-only `private` members.",
  rationale: "ECMAScript private names enforce encapsulation at runtime instead of erasing the boundary during compilation.",
  remediation: "Review reflection, instance escape and framework contracts before replacing TypeScript privacy with ECMAScript private names and updating references.",
  category: "maintainability",
  autofix: "none",
  limitations: [
    "Ambient, abstract, computed, decorated, override, parameter-property, and generated declarations are excluded.",
    "Migration is report-only: type information cannot prove that instances or constructors never escape through this, or that reflection and framework serialization do not observe ordinary private properties.",
  ],
  references: ["https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Classes/Private_elements"],
  examples: [
    {
      id: "runtime-private-member",
      title: "Use runtime-enforced privacy",
      outcome: "no-match",
      files: [{ path: "src/vault.ts", source: "class Vault { #read() { return 1; } open() { return this.#read(); } }" }],
      focusPath: "src/vault.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "typescript-private-member",
      title: "Do not erase a privacy boundary",
      outcome: "match",
      files: [{ path: "src/vault.ts", source: "class Vault { private read() { return 1; } open() { return this.read(); } }" }],
      focusPath: "src/vault.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function reportClass(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  owner: TSESTree.ClassDeclaration | TSESTree.ClassExpression,
): void {
  const groups = new Map<string, PrivateConvertibleMember[]>();
  for (const member of owner.body.body) {
    if (!isConvertible(member)) continue;
    const name = convertibleMemberName(member);
    if (name === null) continue;
    const members = groups.get(name) ?? [];
    members.push(member);
    groups.set(name, members);
  }
  for (const [name, members] of groups) {
    const first = members[0];
    if (first === undefined) continue;
    context.report({
      node: first.key,
      messageId: "preferEcmascriptPrivate",
      data: { name },
    });
  }
}

function isConvertible(member: TSESTree.ClassElement): member is PrivateConvertibleMember {
  if (
    member.type !== AST_NODE_TYPES.MethodDefinition &&
    member.type !== AST_NODE_TYPES.PropertyDefinition &&
    member.type !== AST_NODE_TYPES.AccessorProperty
  ) return false;
  return (
    member.accessibility === "private" &&
    !(member.type === AST_NODE_TYPES.MethodDefinition && member.kind === "constructor") &&
    !member.computed &&
    member.key.type === AST_NODE_TYPES.Identifier &&
    member.decorators.length === 0 &&
    !("declare" in member && member.declare) &&
    !member.override &&
    !(member.type === AST_NODE_TYPES.MethodDefinition && member.value.body === null)
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-ecmascript-private-members",
  documentation: PREFER_ECMASCRIPT_PRIVATE_MEMBERS_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Prefer ECMAScript `#private` class members over TypeScript-only `private` members." },
    schema: [],
    messages: {
      preferEcmascriptPrivate:
        "TypeScript `private {{name}}` is erased at runtime; use the ECMAScript private name `#{{name}}`.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    let services: ParserServicesWithTypeInformation | null;
    try {
      services = ESLintUtils.getParserServices(context);
    } catch {
      services = null;
    }
    if (services === null) return {};
    return {
      ClassDeclaration: (node): void => reportClass(context, node),
      ClassExpression: (node): void => reportClass(context, node),
    };
  },
});
