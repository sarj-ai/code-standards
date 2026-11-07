/**
 * @fileoverview no-generic-json-parser — Parse known JSON fields with an object schema instead of an open JSON or record parser.
 *
 * Port of the 18.x `no-generic-json-parser` rule. Same algorithm; the
 * generated-file gate and the per-file report set reset run in `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-generic-json-parser.test.ts
 */

import { defineRule, type ESTree, type Node, type TsVariable } from "../types.js";
import { directArgumentCall, outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { enclosingFunction, stableConstInitializer, stableValueBinding, typeOnlyReference, writtenMember } from "../utils/stable-value-binding.js";
import { isZodModule } from "../utils/zod.js";
import { successfulParseRead } from "./_successful-parse-read.js";

const NAME = "no-generic-json-parser";
const OPEN_FACTORIES: ReadonlySet<string> = new Set(["any", "unknown", "json", "record", "partialRecord"]);
const WRAPPERS: ReadonlySet<string> = new Set(["optional", "nullable", "nullish", "default", "catch", "readonly", "brand", "describe", "meta"]);
const PARSE_METHODS: ReadonlySet<string> = new Set(["parse", "parseAsync", "safeParse", "safeParseAsync"]);
const THROWING_PARSE_METHODS: ReadonlySet<string> = new Set(["parse", "parseAsync"]);
const FINITE_KEY_FACTORIES: ReadonlySet<string> = new Set(["enum", "literal", "nativeEnum"]);

type Identifier = Extract<Node, { type: "Identifier" }>;

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Parse known JSON fields with an object schema instead of an open JSON or record parser.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { genericParser: "The generic parser does not declare `{{field}}`; parse a focused object schema for the fields this code reads." },
  },
  createOnce(context) {
    const reported = new Set<ESTree.CallExpression>();

    function initializer(node: Identifier): Node | null {
      return stableConstInitializer(context.sourceCode, node)?.value ?? null;
    }
    function declaredVariable(node: ESTree.VariableDeclarator, identifier: Node): TsVariable | undefined {
      return context.sourceCode.getDeclaredVariables(node)
        .find((candidate) => (candidate.identifiers as readonly Node[]).includes(identifier)) as TsVariable | undefined;
    }

    function parser(node: Node, seen = new Set<Node>(), awaited = false): ESTree.CallExpression | null {
      node = unwrapExpression(node);
      if (seen.has(node)) return null;
      seen.add(node);
      switch (node.type) {
        case "AwaitExpression":
          return parser(node.argument, seen, true);
        case "Identifier": {
          const value = initializer(node);
          return value === null ? null : parser(value, seen, awaited);
        }
        case "MemberExpression":
          return getPropertyName(node) === "data" ? successfulData(node) : null;
        case "CallExpression":
          return throwingParse(node, awaited);
        default:
          return null;
      }
    }
    /** `result.data` read only after the open `safeParse` succeeded. */
    function successfulData(node: ESTree.MemberExpression): ESTree.CallExpression | null {
      const call = safeParser(node.object);
      return call !== null && stableResult(node.object) && successfulParseRead(node, call, safeParser) ? call : null;
    }
    function throwingParse(node: ESTree.CallExpression, awaited: boolean): ESTree.CallExpression | null {
      if (node.callee.type !== "MemberExpression") return null;
      const method = getPropertyName(node.callee);
      if (method === null || !THROWING_PARSE_METHODS.has(method) || (method === "parseAsync" && !awaited)) return null;
      return openSchema(node.callee.object) ? node : null;
    }
    function openSchema(node: Node, seen = new Set<Node>()): boolean {
      node = unwrapExpression(node);
      if (seen.has(node)) return false;
      seen.add(node);
      if (node.type === "Identifier") {
        const value = initializer(node);
        return value !== null && stableSchema(node) && openSchema(value, seen);
      }
      if (node.type !== "CallExpression") return false;
      const name = factory(node.callee);
      if (name === "record" || name === "partialRecord") return openRecord(node, seen);
      if (name !== null) return OPEN_FACTORIES.has(name);
      const callee = unwrapExpression(node.callee);
      return callee.type === "MemberExpression" && WRAPPERS.has(getPropertyName(callee) ?? "") && openSchema(callee.object, seen);
    }
    /** A record is open unless an enum or literal key schema bounds its keys. */
    function openRecord(node: ESTree.CallExpression, seen: Set<Node>): boolean {
      const key = node.arguments[0];
      const value = node.arguments[1] ?? key;
      const finiteKey = key?.type === "CallExpression" && FINITE_KEY_FACTORIES.has(factory(key.callee) ?? "");
      return !finiteKey && value !== undefined && openSchema(value, new Set(seen));
    }
    /** The Zod factory a callee names: an imported `string` or `z.string`. */
    function factory(node: Node): string | null {
      node = unwrapExpression(node);
      if (node.type === "Identifier") {
        const specifier = zodValueImport(node);
        return specifier?.type === "ImportSpecifier" ? importSpecifierName(specifier) : null;
      }
      if (node.type !== "MemberExpression") return null;
      const receiver = unwrapExpression(node.object);
      if (receiver.type !== "Identifier") return null;
      const specifier = zodValueImport(receiver);
      if (specifier === null || (specifier.type === "ImportSpecifier" && importSpecifierName(specifier) !== "z")) return null;
      return getPropertyName(node);
    }
    function zodValueImport(node: Identifier): ESTree.ImportSpecifier | ESTree.ImportNamespaceSpecifier | null {
      const definition = binding(node)?.defs[0]?.node;
      if (definition === undefined || !(definition.type === "ImportNamespaceSpecifier" ||
        (definition.type === "ImportSpecifier" && definition.importKind !== "type"))) return null;
      const declaration = parentOf(definition);
      return declaration?.type === "ImportDeclaration" && declaration.importKind !== "type" && isZodModule(declaration.source.value)
        ? definition : null;
    }

    function binding(node: Identifier): TsVariable | null {
      return findVariable(context.sourceCode.getScope(node), node.name);
    }

    function safeParser(node: Node, seen = new Set<Node>(), awaited = false): ESTree.CallExpression | null {
      node = unwrapExpression(node);
      if (seen.has(node)) return null;
      seen.add(node);
      if (node.type === "AwaitExpression") {
        const argument = unwrapExpression(node.argument);
        return awaitedOnlyHere(argument) ? safeParser(argument, seen, true) : null;
      }
      if (node.type === "Identifier") {
        const value = initializer(node);
        return value === null ? null : safeParser(value, seen, awaited);
      }
      if (node.type !== "CallExpression" || node.callee.type !== "MemberExpression") return null;
      const method = getPropertyName(node.callee);
      if (method !== "safeParse" && method !== "safeParseAsync" ||
        method === "safeParseAsync" && !awaited) return null;
      return openSchema(node.callee.object) ? node : null;
    }
    /** An awaited local promise must have no other value reads. */
    function awaitedOnlyHere(argument: Node): boolean {
      if (argument.type !== "Identifier") return true;
      const local = stableConstInitializer(context.sourceCode, argument);
      return local !== null && local.variable.references.every((reference) =>
        reference.init === true || typeOnlyReference(reference) || reference.identifier === argument);
    }
    /** Follow const aliases to the binding that holds the value itself. */
    function rootBinding(node: Identifier): TsVariable | null {
      const chain = new Set<TsVariable>();
      let root = stableConstInitializer(context.sourceCode, node);
      while (root !== null) {
        if (chain.has(root.variable)) return null;
        chain.add(root.variable);
        const value = unwrapExpression(root.value);
        if (value.type !== "Identifier") return root.variable;
        root = stableConstInitializer(context.sourceCode, value);
      }
      return null;
    }
    /**
     * Every value read of `variable`, through stable local const aliases, satisfies `use`.
     * A binding already being checked counts as satisfied.
     */
    function everyRead(variable: TsVariable, seen: Set<TsVariable>, use: (value: Node, parent: Node) => boolean): boolean {
      if (seen.has(variable)) return true;
      seen.add(variable);
      return stableValueBinding(variable) && variable.references.every((reference) => {
        if (reference.init === true || typeOnlyReference(reference)) return true;
        if (reference.isWrite()) return false;
        const value = outerExpression(reference.identifier);
        const parent = parentOf(value);
        if (parent === null) return false;
        if (parent.type === "VariableDeclarator" && parent.init === value) {
          const alias = localAlias(parent);
          return alias !== undefined && everyRead(alias, seen, use);
        }
        return use(value, parent);
      });
    }
    function stableSchema(node: Identifier): boolean {
      const root = rootBinding(node);
      return root !== null && everyRead(root, new Set(), schemaUse);
    }
    function schemaUse(value: Node, parent: Node): boolean {
      if (parent.type !== "MemberExpression" || parent.object !== value || writtenMember(parent)) return false;
      const name = getPropertyName(parent);
      return name !== null && (WRAPPERS.has(name) || PARSE_METHODS.has(name));
    }
    function opaqueReturn(node: Node): boolean {
      const value = outerExpression(node);
      const parent = parentOf(value);
      if (parent === null || parent.type !== "ReturnStatement" &&
        !(parent.type === "ArrowFunctionExpression" && parent.body === value)) return false;
      return enclosingFunction(value)?.returnType?.typeAnnotation.type === "TSUnknownKeyword";
    }
    function validationArgument(node: Node): boolean {
      const call = directArgumentCall(node);
      return call !== null && call.arguments[0] === outerExpression(node) &&
        call.callee.type === "MemberExpression" &&
        PARSE_METHODS.has(getPropertyName(call.callee) ?? "") &&
        !openSchema(call.callee.object);
    }
    function validatedField(node: ESTree.MemberExpression): boolean {
      if (validationArgument(node)) return true;
      const value = outerExpression(node);
      const parent = parentOf(value);
      if (parent === null) return false;
      if (parent.type !== "VariableDeclarator" || parent.init !== value || parent.id.type !== "Identifier" ||
        (parentOf(parent) as ESTree.VariableDeclaration | null)?.kind !== "const") return false;
      const variable = declaredVariable(parent, parent.id);
      return variable !== undefined && stableValueBinding(variable) &&
        variable.references.some((reference) => reference.isRead()) &&
        variable.references.every((reference) => reference.init === true || typeOnlyReference(reference) ||
          !reference.isWrite() && validationArgument(reference.identifier));
    }
    function localAlias(node: ESTree.VariableDeclarator): TsVariable | undefined {
      if ((parentOf(node) as ESTree.VariableDeclaration | null)?.kind !== "const" || node.id.type !== "Identifier") return undefined;
      const variable = declaredVariable(node, node.id);
      return variable !== undefined && stableValueBinding(variable) ? variable : undefined;
    }
    function dataUse(value: Node, parent: Node): boolean {
      return parent.type === "MemberExpression" && parent.object === value ? !writtenMember(parent) : validationArgument(value);
    }
    function stableResult(node: Node): boolean {
      node = unwrapExpression(node);
      const root = node.type === "Identifier" ? rootBinding(node) : null;
      return root !== null && everyRead(root, new Set(), resultUse);
    }
    /** A safe-parse result is read only for `success`, `error`, or a stable `data`. */
    function resultUse(value: Node, parent: Node): boolean {
      if (parent.type !== "MemberExpression" || parent.object !== value || writtenMember(parent)) return false;
      const key = getPropertyName(parent);
      if (key === "success" || key === "error") return true;
      if (key !== "data") return false;
      const data = outerExpression(parent);
      const consumer = parentOf(data);
      if (consumer === null) return false;
      if (consumer.type === "VariableDeclarator" && consumer.init === data) {
        const alias = localAlias(consumer);
        return alias !== undefined && everyRead(alias, new Set(), dataUse);
      }
      return dataUse(data, consumer);
    }

    return {
      before() {
        reported.clear();
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      MemberExpression(node) {
        const field = getPropertyName(node);
        if (field === null || writtenMember(node)) return;
        // Most member reads have no open parser, so that check runs before the costlier exemptions.
        const call = parser(node.object);
        if (call === null || reported.has(call) || validatedField(node) || opaqueReturn(node)) return;
        reported.add(call);
        context.report({ node: call, messageId: "genericParser", data: { field } });
      },
    };
  },
});
