/**
 * @fileoverview interface-contract-members-private — keep an implementing class's non-contract methods runtime-private.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/interface-contract-members-private.test.ts
 */

import {
  AST_NODE_TYPES,
  ESLintUtils,
  type ParserServicesWithTypeInformation,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";
import * as ts from "typescript";

import { convertibleMemberName } from "./_class-private.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "nonContractMemberMustBePrivate";
type Options = readonly [];

export const INTERFACE_CONTRACT_MEMBERS_PRIVATE_DOCUMENTATION = {
  summary: "Require methods outside an implemented interface contract to use ECMAScript private names.",
  rationale: "An implementing class should expose exactly its declared interface while keeping implementation helpers runtime-private.",
  remediation: "Add the method to the interface when it is public API, or make it `#private` and remove external or inherited access.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Only concrete classes with an explicit `implements` clause are checked; constructors and static members are excluded.",
    "Inherited interface members are resolved by TypeScript. Computed names are excluded because their contract identity is not stable syntax.",
    "The rule abstains for the whole class when TypeScript cannot resolve any implemented contract, avoiding false positives for missing or unavailable package declarations.",
    "The rule is report-only because a public member can have consumers in another source file; the developer must choose whether to extend the interface or privatize it.",
    "TypeScript-private members are left to prefer-ecmascript-private-members so one concern produces one diagnostic.",
  ],
  examples: [
    {
      id: "exact-interface-surface",
      title: "Keep helpers behind the runtime boundary",
      outcome: "no-match",
      files: [{ path: "src/store.ts", source: "interface Store { load(): void } class DiskStore implements Store { load() { this.#read(); } #read() {} }" }],
      focusPath: "src/store.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "extra-public-method",
      title: "Do not grow an undeclared public surface",
      outcome: "match",
      files: [{ path: "src/store.ts", source: "interface Store { load(): void } class DiskStore implements Store { load() { this.read(); } read() {} }" }],
      focusPath: "src/store.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function reportClass(
  context: Readonly<TSESLint.RuleContext<MessageIds, Options>>,
  services: ParserServicesWithTypeInformation,
  owner: TSESTree.ClassDeclaration | TSESTree.ClassExpression,
): void {
  if (owner.abstract) return;
  const contract = interfaceNames(services, owner);
  if (contract === null) return;
  const groups = new Map<string, TSESTree.MethodDefinition[]>();
  for (const member of owner.body.body) {
    if (!candidate(member)) continue;
    const name = convertibleMemberName(member);
    if (name === null || contract.has(name)) continue;
    // Avoid duplicate diagnostics: the dedicated modern-private rule owns this
    // member and converts it to the same required final form.
    if (member.accessibility === "private" || member.key.type === AST_NODE_TYPES.PrivateIdentifier) continue;
    const members = groups.get(name) ?? [];
    members.push(member);
    groups.set(name, members);
  }
  for (const [name, members] of groups) {
    const first = members[0];
    if (first === undefined) continue;
    context.report({
      node: first.key,
      messageId: "nonContractMemberMustBePrivate",
      data: { name },
    });
  }
}

function candidate(member: TSESTree.ClassElement): member is TSESTree.MethodDefinition {
  return (
    member.type === AST_NODE_TYPES.MethodDefinition &&
    member.kind !== "constructor" &&
    !member.static &&
    !member.computed &&
    member.key.type === AST_NODE_TYPES.Identifier &&
    member.value.body !== null
  );
}

function interfaceNames(
  services: ParserServicesWithTypeInformation,
  owner: TSESTree.ClassDeclaration | TSESTree.ClassExpression,
): ReadonlySet<string> | null {
  const tsOwner = services.esTreeNodeToTSNodeMap.get(owner);
  if (!ts.isClassDeclaration(tsOwner) && !ts.isClassExpression(tsOwner)) return null;
  const implemented = tsOwner.heritageClauses?.filter((clause) => clause.token === ts.SyntaxKind.ImplementsKeyword) ?? [];
  if (implemented.length === 0) return null;
  const checker = services.program.getTypeChecker();
  const names = new Set<string>();
  for (const clause of implemented) {
    for (const contract of clause.types) {
      const type = checker.getTypeAtLocation(contract);
      if ((type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) !== 0) return null;
      for (const property of checker.getPropertiesOfType(type)) names.add(property.getName());
    }
  }
  return names;
}

export default createRule<Options, MessageIds>({
  name: "interface-contract-members-private",
  documentation: INTERFACE_CONTRACT_MEMBERS_PRIVATE_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: "Require methods outside an implemented interface contract to use ECMAScript private names." },
    schema: [],
    messages: {
      nonContractMemberMustBePrivate:
        "Method `{{name}}` is not part of this class's implemented interface contract; make it `#{{name}}` or declare it in the interface.",
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
      ClassDeclaration: (node): void => reportClass(context, services, node),
      ClassExpression: (node): void => reportClass(context, services, node),
    };
  },
});
