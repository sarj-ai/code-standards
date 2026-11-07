/**
 * @fileoverview no-first-party-module-mock — prefer explicit injection over ambient replacement of first-party modules.
 *
 * Port of the 18.x `no-first-party-module-mock` rule. Same algorithm;
 * options are read and the test-file and generated-file gates run in
 * `before()`. Oxlint merges `meta.defaultOptions` into the options.
 */

import { defineRule, type ESTree } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { getPropertyName, staticString } from "../utils/static-string.js";
import { importedTestMockNamespace } from "../utils/test-mock-provenance.js";

const NAME = "no-first-party-module-mock";

type Options = readonly [{ additionalModulePrefixes?: readonly string[] }];

const MOCK_METHODS: ReadonlySet<string> = new Set(["mock", "doMock", "unstable_mockModule"]);

function isFirstParty(source: string, prefixes: readonly string[]): boolean {
  return source.startsWith("./") || source.startsWith("../") || prefixes.some((prefix) => source.startsWith(prefix));
}

function mayBeVirtual(options: ESTree.Argument | undefined): boolean {
  if (options === undefined) return false;
  if (options.type !== "ObjectExpression") return true;
  return options.properties.some((property) => {
    if (property.type !== "Property" || property.computed) return true;
    const name = property.key.type === "Identifier" ? property.key.name : property.key.type === "Literal" ? property.key.value : null;
    return name === "virtual" && !(property.value.type === "Literal" && property.value.value === false);
  });
}

export default defineRule({
  meta: {
    defaultOptions: [{ additionalModulePrefixes: [] }],
    type: "problem",
    docs: { description: "Prefer injected collaborators over mocking maintained first-party modules in tests.", url: docsUrl(NAME) },
    schema: [{ type: "object", additionalProperties: false, properties: { additionalModulePrefixes: { description: "Additional maintained module prefixes that tests must not mock.", type: "array", items: { type: "string", minLength: 1 }, uniqueItems: true } } }],
    messages: { noFirstPartyModuleMock: "This test replaces the maintained module `{{module}}`. Inject a narrow collaborator or test the real module; suppress locally only when module lookup or bootstrap behavior is the contract." },
  },
  createOnce(context) {
    let prefixes: readonly string[] = [];
    return {
      before(): boolean | void {
        const file = { filename: context.filename, cwd: context.cwd };
        if (!isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        const [options] = context.options as unknown as Options;
        prefixes = options.additionalModulePrefixes ?? [];
      },
      CallExpression(node: ESTree.CallExpression): void {
        const callee = unwrapExpression(node.callee);
        if (callee.type !== "MemberExpression") return;
        const receiver = unwrapExpression(callee.object);
        const method = getPropertyName(callee);
        if (receiver.type !== "Identifier" || method === null || !MOCK_METHODS.has(method)) return;
        const framework = importedTestMockNamespace(context.sourceCode, receiver);
        if (framework === null ||
          (method === "unstable_mockModule" && framework !== "jest") ||
          (framework === "jest" && mayBeVirtual(node.arguments[2]))) return;
        const [first] = node.arguments;
        if (first === undefined) return;
        const argument = unwrapExpression(first);
        const moduleName = staticString(argument);
        if (moduleName === null || !isFirstParty(moduleName, prefixes)) return;
        context.report({ node: argument, messageId: "noFirstPartyModuleMock", data: { module: moduleName } });
      },
    };
  },
});
