/**
 * @fileoverview no-bespoke-api-case-conversion — direct snake/camel mirror mappings duplicate generated API client ownership.
 *
 * Port of the 18.x `no-bespoke-api-case-conversion` rule. The rule is
 * untyped, so the port covers all of it.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const NAME = "no-bespoke-api-case-conversion";

const ADAPTER_BASENAME_RE = /(?:^|[-_.])adapters?(?:[-_.]|$)/i;
const API_BOUNDARY_IMPORT_RE = /(?:^|[/_.-])(?:api|client|sdk|contract|generated)(?:$|[/_.-])/i;
const SNAKE_CASE_RE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/;
const LOWER_CAMEL_CASE_RE = /^[a-z][A-Za-z0-9]*$/;

function memberName(node: Node): string | null {
  const current = unwrapExpression(node);
  return current.type === "MemberExpression" ? getPropertyName(current) : null;
}

function isDirectCaseTranslation(left: string, right: string): boolean {
  if (SNAKE_CASE_RE.test(left) && LOWER_CAMEL_CASE_RE.test(right)) {
    return snakeToCamel(left) === right;
  }
  if (SNAKE_CASE_RE.test(right) && LOWER_CAMEL_CASE_RE.test(left)) {
    return snakeToCamel(right) === left;
  }
  return false;
}

function snakeToCamel(name: string): string {
  return name.replace(/_([a-z0-9])/g, (_match, character: string) => character.toUpperCase());
}

/** Whether the member chain's root is a never-reassigned binding annotated with an imported API type. */
function hasApiReceiver(value: Node, sourceCode: SourceCode): boolean {
  let current = unwrapExpression(value);
  while (current.type === "MemberExpression") current = unwrapExpression(current.object);
  if (current.type !== "Identifier") return false;
  const binding = findVariable(sourceCode.getScope(current), current.name);
  if (binding?.defs.length !== 1 || binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
  const identifier = binding.defs[0]?.name;
  if (identifier?.type !== "Identifier") return false;
  const annotation = identifier.typeAnnotation?.typeAnnotation;
  return annotation?.type === "TSTypeReference" && isApiBoundaryType(annotation.typeName, sourceCode);
}

/** Whether a type name's root is imported from an API, client, SDK, contract or generated module. */
function isApiBoundaryType(typeName: ESTree.TSTypeName, sourceCode: SourceCode): boolean {
  while (typeName.type === "TSQualifiedName") typeName = typeName.left;
  if (typeName.type !== "Identifier") return false;
  const typeBinding = findVariable(sourceCode.getScope(typeName), typeName.name);
  const definition = typeBinding?.defs.length === 1 ? typeBinding.defs[0] : undefined;
  return definition?.type === "ImportBinding" && definition.parent?.type === "ImportDeclaration" &&
    API_BOUNDARY_IMPORT_RE.test(definition.parent.source.value);
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Review direct snake_case/camelCase mirror mappings on explicitly API-typed adapter values.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      noBespokeApiCaseConversion:
        "This API-typed adapter value mirrors `{{wireName}}` and `{{applicationName}}`. If the SDK owns application-facing names, move this conversion to its model boundary.",
    },
  },
  createOnce(context) {
    return {
      before(): boolean | void {
        const filename = context.filename.replaceAll("\\", "/");
        const basename = filename.slice(filename.lastIndexOf("/") + 1);
        const file = { filename: context.filename, cwd: context.cwd };
        if (!ADAPTER_BASENAME_RE.test(basename) || isGeneratedFile(file, context.sourceCode.text) || isTestFile(file, ["fixtureTree"])) return false;
      },
      Property(node: ESTree.ObjectProperty): void {
        if (node.computed || node.method || node.shorthand) return;
        const key = node.key.type === "Identifier" ? node.key.name : null;
        const value = memberName(node.value);
        if (key === null || value === null || !isDirectCaseTranslation(key, value)) return;
        if (!hasApiReceiver(node.value, context.sourceCode)) return;
        const wireName = SNAKE_CASE_RE.test(key) ? key : value;
        const applicationName = wireName === key ? value : key;
        context.report({
          node: node.key,
          messageId: "noBespokeApiCaseConversion",
          data: { applicationName, wireName },
        });
      },
    };
  },
});
