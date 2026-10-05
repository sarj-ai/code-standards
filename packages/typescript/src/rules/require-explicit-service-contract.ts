/**
 * @fileoverview require-explicit-service-contract — Require a declared contract when a service invokes an injected collaborator.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-explicit-service-contract.test.ts
 */

import type { ESTree } from "@oxlint/plugins";
import { sourceOrigin } from "./_source-origin.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import {
  isGeneratedFile,
  isScriptFile,
  isStoryFile,
  isTestFile,
} from "./_paths.js";
import {
  createExportedServiceClassResolver,
  createServiceOperationResolver,
  hasDeclaredServiceContract,
} from "./require-port-for-service.js";

type MessageIds = "requireExplicitServiceContract";
type Options = readonly [];

export const REQUIRE_EXPLICIT_SERVICE_CONTRACT_DOCUMENTATION = {
  defaultLevel: "warning",
  summary:
    "Require explicit contracts for classes that invoke retained collaborators.",
  rationale:
    "A one-operation service can orchestrate a collaborator without declaring the contract that callers consume and implementations and fakes satisfy.",
  remediation:
    "Explicitly implement a focused interface or extend an abstract class covering the service operations. Export the contract only when its consumers need it.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "The rule checks service, store, and provider class declarations whose constructor stores a typed behavioral collaborator and whose public method reaches that collaborator.",
    "Existing local interfaces, type aliases, and inherited contracts can cover the operations; the compiler owns signature compatibility.",
    "Imported or dynamic base classes with unavailable declarations and decorated classes or operations are unresolved and do not produce a finding.",
    "Generated files and JavaScript without implements syntax are excluded.",
  ],
  examples: [
    {
      id: "single-operation-service-without-contract",
      title: "A single service operation still needs its contract",
      outcome: "match",
      files: [
        {
          path: "src/service.ts",
          source:
            "class OrchestratorService { constructor(private readonly worker: Worker) {} run(): void { this.worker.run(); } }",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "explicit-single-operation-contract",
      title: "The service declares its operation",
      outcome: "no-match",
      files: [
        {
          path: "src/service.ts",
          source:
            "interface Runner { run(): void } class OrchestratorService implements Runner { constructor(private readonly worker: Worker) {} run(): void { this.worker.run(); } }",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "require-explicit-service-contract",
  documentation: REQUIRE_EXPLICIT_SERVICE_CONTRACT_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description: REQUIRE_EXPLICIT_SERVICE_CONTRACT_DOCUMENTATION.summary,
    },
    schema: [],
    messages: {
      requireExplicitServiceContract:
        "`{{name}}` invokes a retained collaborator from {{operations}} without a declared interface or abstract-class contract covering those operations. Implement a focused contract; it can remain local.",
    },
  },
  defaultOptions: [],
  create(context) {
    const origin = sourceOrigin(context);
    if (
      /\.(?:js|jsx|mjs|cjs)$/iu.test(origin.filename) ||
      isGeneratedFile(origin.filename, origin.text)
    )
      return {};
    const program: ESTree.Program = context.sourceCode.ast;
    const operationsFor = createServiceOperationResolver(program);
    const isExportedServiceClass = createExportedServiceClassResolver(program);
    return {
      ClassDeclaration(node): void {
        if (
          node.id === null ||
          node.abstract ||
          node.decorators.length > 0 ||
          !isServiceRole(node.id.name, origin.filename)
        )
          return;
        if (
          isExportedServiceClass(node) &&
          !isTestFile(origin.filename) &&
          !isStoryFile(origin.filename) &&
          !isScriptFile(origin.filename)
        )
          return;
        const operations = operationsFor(node);
        if (
          operations.length === 0 ||
          hasDeclaredServiceContract(node, operations, program) !== false
        )
          return;
        context.report({
          node: node.id,
          messageId: "requireExplicitServiceContract",
          data: { name: node.id.name, operations: operations.join(", ") },
        });
      },
    };
  },
});

const BOUNDARY_SUFFIX =
  /(?:Service|ServiceImpl|Store|Repository|Provider|Executor|Enqueuer|Runner|Platform|Manager|ManagerImpl|Detector|Control|Refresher|Reader|Settlement|Retry|Stop|Catalog|DAO)$/u;
const NON_SERVICE_SUFFIX = /(?:Router|Middleware|Builder)$/u;
const BOUNDARY_DIRS: ReadonlySet<string> = new Set([
  "services",
  "stores",
  "providers",
  "repositories",
]);
const NON_SERVICE_DIRS: ReadonlySet<string> = new Set([
  "routers",
  "middleware",
  "scripts",
]);

function isServiceRole(name: string, filename: string): boolean {
  const parts = filename.split(/[\\/]/u);
  if (
    NON_SERVICE_SUFFIX.test(name) ||
    parts.some((part) => NON_SERVICE_DIRS.has(part))
  )
    return false;
  return (
    BOUNDARY_SUFFIX.test(name) || parts.some((part) => BOUNDARY_DIRS.has(part))
  );
}
