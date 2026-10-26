/**
 * @fileoverview require-explicit-service-contract — Require a declared contract when a service invokes an injected collaborator.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-explicit-service-contract.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { existingFactoryContractFix } from "./_existing-factory-contract-fix.js";
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
  defaultLevel: "error",
  summary:
    "Require explicit contracts for classes that invoke retained collaborators.",
  rationale:
    "A one-operation service can orchestrate a collaborator without declaring the contract that callers consume and implementations and fakes satisfy.",
  remediation:
    "Explicitly implement a focused interface or extend an abstract class covering the service operations. Export the contract only when its consumers need it.",
  category: "architecture",
  autofix: "safe",
  limitations: [
    "Automatic fixes only add the exact existing closed type alias named by an already-authored direct factory return annotation. A complete comment-free four-declaration module must contain one exported closed object type alias containing one zero-argument void method, one local matching worker interface, one ordinary nonabstract nongeneric class with an empty constructor retaining a private readonly worker parameter and one matching public forwarding method, and one exported ordinary required-worker-parameter factory returning that exact new class as the port. Unique lexical bindings, no heritage/decorators/defaults/imports/merges/other members or authority, and exact existing types/calls are required. Mergeable public interfaces are refused because downstream declaration augmentation can introduce a private-field compatibility error. No contract, method, field, import or name is invented; emitted JavaScript remains identical. Other shapes remain manual.",
    "The rule checks service, store, and provider class declarations whose constructor stores a typed behavioral collaborator and whose public method reaches that collaborator.",
    "Existing local interfaces, type aliases, and inherited contracts can cover the operations; the compiler owns signature compatibility.",
    "Imported or dynamic base classes with unavailable declarations and decorated classes or operations are unresolved and do not produce a finding.",
    "Constructor retention requires an untouched parameter property or one direct, unconditional assignment. Written or replaced operation members do not prove their declared bodies execute; external aliases, mutators, and callbacks are not resolved.",
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
    {
      id: "safe-autofix",
      title: "The existing factory already names the service contract",
      outcome: "match",
      files: [
        {
          path: "src/service.ts",
          source:
            "export type Port = { run(): void; };\ninterface Worker { run(): void; }\nclass Service { constructor(private readonly worker: Worker) {} run(): void { this.worker.run(); } }\nexport function create(worker: Worker): Port { return new Service(worker); }",
        },
      ],
      fixedFiles: [
        {
          path: "src/service.ts",
          source:
            "export type Port = { run(): void; };\ninterface Worker { run(): void; }\nclass Service implements Port { constructor(private readonly worker: Worker) {} run(): void { this.worker.run(); } }\nexport function create(worker: Worker): Port { return new Service(worker); }",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 1,
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
    fixable: "code",
    messages: {
      requireExplicitServiceContract:
        "`{{name}}` invokes a retained collaborator from {{operations}} without a declared interface or abstract-class contract covering those operations. Implement a focused contract; it can remain local.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      /\.(?:js|jsx|mjs|cjs)$/iu.test(context.filename) ||
      isGeneratedFile(context, context.sourceCode.text)
    )
      return {};
    const program: TSESTree.Program = context.sourceCode.ast;
    const operationsFor = createServiceOperationResolver(program);
    const isExportedServiceClass = createExportedServiceClassResolver(program);
    return {
      ClassDeclaration(node): void {
        if (
          node.id === null ||
          node.abstract ||
          node.decorators.length > 0 ||
          !isServiceRole(node.id.name, context.filename)
        )
          return;
        if (
          isExportedServiceClass(node) &&
          !isTestFile(context) &&
          !isStoryFile(context) &&
          !isScriptFile(context)
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
          fix: existingFactoryContractFix(context.sourceCode, node),
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
