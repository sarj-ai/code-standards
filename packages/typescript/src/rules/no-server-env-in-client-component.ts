/**
 * @fileoverview no-server-env-in-client-component — client bundles cannot read server-only settings.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-server-env-in-client-component.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "noServerEnvInClientComponent";
type Options = readonly [];

const SERVER_ENV_MODULE_RE = /(?:^|\/)(?:server-env|server-settings)(?:\.[cm]?[jt]sx?)?$/;

export const noServerEnvInClientComponentDocumentation = {
  summary: "server-only environment settings imported by a client component",
  rationale:
    "Next.js client modules run in the browser, where server-only environment values are unavailable; importing a server settings module can produce undefined configuration or bundle a secret-bearing module into the client graph.",
  remediation:
    "Pass an explicitly public value from a Server Component, or import it from a separately validated client-settings module backed only by NEXT_PUBLIC_* values.",
  category: "correctness",
  limitations: [
    "Only static value imports in files with a top-level 'use client' directive and conventionally named server-env/server-settings modules are checked.",
  ],
  examples: [
    {
      id: "public-client-settings",
      title: "Import a browser-safe settings boundary",
      outcome: "no-match",
      files: [
        {
          path: "status-card.tsx",
          source: "'use client';\nimport { CLIENT_SETTINGS } from '@/client-settings';\nexport const StatusCard = () => <p>{CLIENT_SETTINGS.apiOrigin}</p>;\n",
        },
      ],
      focusPath: "status-card.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "server-settings-client-import",
      title: "Do not pull server settings into a client bundle",
      outcome: "match",
      files: [
        {
          path: "status-card.tsx",
          source: "'use client';\nimport { SERVER_SETTINGS } from '@/server-settings';\nexport const StatusCard = () => <p>{SERVER_SETTINGS.apiOrigin}</p>;\n",
        },
      ],
      focusPath: "status-card.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function isClientModule(program: TSESTree.Program): boolean {
  return program.body.some(
    (statement) =>
      statement.type === "ExpressionStatement" &&
      statement.directive === "use client",
  );
}

function isTypeOnlyImport(node: TSESTree.ImportDeclaration): boolean {
  return (
    node.importKind === "type" ||
    (node.specifiers.length > 0 &&
      node.specifiers.every(
        (specifier) =>
          specifier.type === "ImportSpecifier" && specifier.importKind === "type",
      ))
  );
}

export default createRule<Options, MessageIds>({
  name: "no-server-env-in-client-component",
  documentation: noServerEnvInClientComponentDocumentation,
  meta: {
    type: "problem",
    docs: { description: noServerEnvInClientComponentDocumentation.summary },
    schema: [],
    messages: {
      noServerEnvInClientComponent:
        "A 'use client' module cannot import server-only settings. Pass public data from a Server Component or use a validated client-settings module.",
    },
  },
  defaultOptions: [],
  create(context) {
    let clientModule = false;
    return {
      Program(node): void {
        clientModule = isClientModule(node);
      },
      ImportDeclaration(node): void {
        if (
          clientModule &&
          !isTypeOnlyImport(node) &&
          typeof node.source.value === "string" &&
          SERVER_ENV_MODULE_RE.test(node.source.value)
        ) {
          context.report({ node, messageId: "noServerEnvInClientComponent" });
        }
      },
    };
  },
});
