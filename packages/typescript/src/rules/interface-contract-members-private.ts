/**
 * @fileoverview interface-contract-members-private — keep an implementing class's non-contract methods runtime-private.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/interface-contract-members-private.test.ts
 */



import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, SourceCode } from "@oxlint/plugins";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { resolveVariable } from "./_scope.js";

type MessageIds = "nonContractMemberMustBePrivate";
type Options = readonly [];

export const INTERFACE_CONTRACT_MEMBERS_PRIVATE_DOCUMENTATION = {
  summary:
    "Require methods outside an implemented interface contract to use ECMAScript private names.",
  rationale:
    "An implementing class should expose exactly its declared interface while keeping implementation helpers runtime-private.",
  remediation:
    "Add the method to the interface when it is public API, or make it `#private` and remove external or inherited access.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Only concrete classes with an explicit `implements` clause are checked; constructors, static members, protected extension hooks, and overrides are excluded.",
    "Implemented interfaces and transitive interface parents must have one same-file lexical declaration. Imported interfaces, type aliases, merged declarations, index signatures, and computed names are excluded.",
    "The rule abstains for the whole class when any implemented contract cannot be established from local declarations; cross-module contracts are not inspected.",
    "The rule is report-only because a public member can have consumers in another source file; the developer must choose whether to extend the interface or privatize it.",
    "TypeScript-private members are left to prefer-ecmascript-private-members so one concern produces one diagnostic.",
  ],
  examples: [
    {
      id: "exact-interface-surface",
      title: "Keep helpers behind the runtime boundary",
      outcome: "no-match",
      files: [
        {
          path: "src/store.ts",
          source:
            "interface Store { load(): void } class DiskStore implements Store { load() { this.#read(); } #read() {} }",
        },
      ],
      focusPath: "src/store.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "extra-public-method",
      title: "Do not grow an undeclared public surface",
      outcome: "match",
      files: [
        {
          path: "src/store.ts",
          source:
            "interface Store { load(): void } class DiskStore implements Store { load() { this.read(); } read() {} }",
        },
      ],
      focusPath: "src/store.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

/** Resolve only unambiguous interfaces declared in this file. */
function interfaceNames(
  sourceCode: SourceCode,
  identifier: ESTree.IdentifierReference,
  seen = new Set<ESTree.Node>(),
): ReadonlySet<string> | null {
  const definitions = resolveVariable(sourceCode, identifier)?.defs;
  if (definitions?.length !== 1) return null;
  const declaration = definitions[0]?.node;
  if (declaration?.type !== "TSInterfaceDeclaration" || seen.has(declaration))
    return null;
  seen.add(declaration);
  const names = new Set<string>();
  for (const member of declaration.body.body) {
    if (
      (member.type !== "TSMethodSignature" &&
        member.type !== "TSPropertySignature") ||
      member.computed
    )
      return null;
    const key = member.key;
    if (key.type === "Identifier") names.add(key.name);
    else if (key.type === "Literal" && typeof key.value === "string")
      names.add(key.value);
    else return null;
  }
  for (const heritage of declaration.extends) {
    if (heritage.expression.type !== "Identifier") return null;
    const inherited = interfaceNames(
      sourceCode,
      heritage.expression,
      new Set(seen),
    );
    if (inherited === null) return null;
    for (const name of inherited) names.add(name);
  }
  return names;
}

export default createRule<Options, MessageIds>({
  name: "interface-contract-members-private",
  documentation: INTERFACE_CONTRACT_MEMBERS_PRIVATE_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Require methods outside an implemented interface contract to use ECMAScript private names.",
    },
    schema: [],
    messages: {
      nonContractMemberMustBePrivate:
        "Method `{{name}}` is not part of this class's implemented interface contract; make it `#{{name}}` or declare it in the interface.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) return {};
    function reportClass(owner: ESTree.Class): void {
      if (owner.abstract || !owner.implements?.length) return;
      const contract = new Set<string>();
      for (const implemented of owner.implements) {
        if (implemented.expression.type !== "Identifier") return;
        const names = interfaceNames(
          context.sourceCode,
          implemented.expression,
        );
        if (names === null) return;
        for (const name of names) contract.add(name);
      }
      const reported = new Set<string>();
      for (const member of owner.body.body) {
        if (
          member.type !== "MethodDefinition" ||
          member.kind === "constructor" ||
          member.static ||
          member.accessibility === "protected" ||
          member.accessibility === "private" ||
          member.override ||
          member.computed ||
          member.key.type !== "Identifier" ||
          member.value.body === null
        )
          continue;
        const name = member.key.name;
        if (contract.has(name) || reported.has(name)) continue;
        reported.add(name);
        context.report({
          node: member.key,
          messageId: "nonContractMemberMustBePrivate",
          data: { name },
        });
      }
    }
    return { ClassDeclaration: reportClass, ClassExpression: reportClass };
  },
});
