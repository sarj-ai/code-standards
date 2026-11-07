/**
 * @fileoverview require-explicit-service-contract — Require a declared contract when a service invokes an injected collaborator.
 *
 * Port of the 18.x `require-explicit-service-contract` rule. Same
 * algorithm; the service-class analysis is shared with
 * `require-port-for-service` through `./_service-class.ts`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-explicit-service-contract.test.ts
 */

import { defineRule } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { existingFactoryContractFix } from "../utils/existing-factory-contract-fix.js";
import { isGeneratedFile, isScriptFile, isStoryFile, isTestFile } from "../utils/paths.js";
import { hasDeclaredServiceContract, isExportedServiceClass, serviceFile, serviceOperations } from "./_service-class.js";

const NAME = "require-explicit-service-contract";
const JAVASCRIPT_FILE_RE = /\.(?:js|jsx|mjs|cjs)$/iu;

const BOUNDARY_SUFFIX =
  /(?:Service|ServiceImpl|Store|Repository|Provider|Executor|Enqueuer|Runner|Platform|Manager|ManagerImpl|Detector|Control|Refresher|Reader|Settlement|Retry|Stop|Catalog|DAO)$/u;
const NON_SERVICE_SUFFIX = /(?:Router|Middleware|Builder)$/u;
const BOUNDARY_DIRS: ReadonlySet<string> = new Set(["services", "stores", "providers", "repositories"]);
const NON_SERVICE_DIRS: ReadonlySet<string> = new Set(["routers", "middleware", "scripts"]);

function isServiceRole(name: string, filename: string): boolean {
  const parts = filename.split(/[\\/]/u);
  if (NON_SERVICE_SUFFIX.test(name) || parts.some((part) => NON_SERVICE_DIRS.has(part))) return false;
  return BOUNDARY_SUFFIX.test(name) || parts.some((part) => BOUNDARY_DIRS.has(part));
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Require explicit contracts for classes that invoke retained collaborators.",
      url: docsUrl(NAME),
    },
    schema: [],
    fixable: "code",
    messages: {
      requireExplicitServiceContract:
        "`{{name}}` invokes a retained collaborator from {{operations}} without a declared interface or abstract-class contract covering those operations. Implement a focused contract; it can remain local.",
    },
  },
  createOnce(context) {
    // Exported classes outside tests, stories and scripts are require-port-for-service's to advise on.
    let exemptExportedClass = false;

    return {
      before(): boolean | void {
        const file = { filename: context.filename, cwd: context.cwd };
        if (JAVASCRIPT_FILE_RE.test(file.filename) || isGeneratedFile(file, context.sourceCode.text)) return false;
        exemptExportedClass = !isTestFile(file) && !isStoryFile(file) && !isScriptFile(file);
      },
      ClassDeclaration(node): void {
        if (node.id === null || node.abstract || node.decorators.length > 0 ||
          !isServiceRole(node.id.name, context.filename))
          return;
        const file = serviceFile(context.sourceCode.ast);
        if (exemptExportedClass && isExportedServiceClass(node, file)) return;
        const operations = serviceOperations(node, file);
        if (operations.length === 0 || hasDeclaredServiceContract(node, operations, file) !== false) return;
        const fix = existingFactoryContractFix(context.sourceCode, node);
        context.report({
          node: node.id,
          messageId: "requireExplicitServiceContract",
          data: { name: node.id.name, operations: operations.join(", ") },
          ...(fix !== null && { fix }),
        });
      },
    };
  },
});
