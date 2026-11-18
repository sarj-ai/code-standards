/** @fileoverview prefer-zod-field-bounds — keep a pure integer field range in its field schema. */

import { defineRule, type ESTree, type Node, type TsVariable } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile } from "../utils/paths.js";
import {
  stableValueBinding,
  typeOnlyReference,
  writtenMember,
} from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { SCHEMA_INTEGER_FIELD_MINIMUMS } from "../utils/zod.js";

const NAME = "prefer-zod-field-bounds";
const FULL_ZOD_MODULES: ReadonlySet<string> = new Set(["zod", "zod/v4"]);
const PRIMITIVE_FACTORIES: ReadonlySet<string> = new Set([
  "string",
  "boolean",
  "number",
  "int",
  "bigint",
  "symbol",
  "date",
]);
const REVERSED: ReadonlyMap<string, string> = new Map([
  [">", "<"],
  [">=", "<="],
  ["<", ">"],
  ["<=", ">="],
]);

type Identifier = Extract<Node, { type: "Identifier" }>;

function boundedField(node: Node): string | null {
  node = unwrapExpression(node);
  if (node.type !== "ArrowFunctionExpression" || node.async || node.params.length !== 1)
    return null;
  const [parameter] = node.params;
  const body = unwrapExpression(node.body);
  if (
    parameter?.type !== "Identifier" ||
    body.type !== "BinaryExpression" ||
    !REVERSED.has(body.operator)
  )
    return null;
  const left = fieldRead(body.left, parameter.name);
  const right = integerLiteral(body.right);
  if (left !== null && right !== null) return meaningfulBound(body.operator, right) ? left : null;
  const field = fieldRead(body.right, parameter.name);
  const bound = integerLiteral(body.left);
  const operator = REVERSED.get(body.operator);
  return field !== null &&
    bound !== null &&
    operator !== undefined &&
    meaningfulBound(operator, bound)
    ? field
    : null;
}

function integerLiteral(node: Node): number | null {
  node = unwrapExpression(node);
  if (node.type === "Literal" && typeof node.value === "number" && Number.isSafeInteger(node.value))
    return node.value;
  if (node.type !== "UnaryExpression" || (node.operator !== "+" && node.operator !== "-"))
    return null;
  const value = integerLiteral(node.argument);
  return value === null ? null : node.operator === "-" ? -value : value;
}

function fieldRead(node: Node, parameter: string): string | null {
  node = unwrapExpression(node);
  if (node.type !== "MemberExpression" || node.optional || node.computed) return null;
  const receiver = unwrapExpression(node.object);
  return receiver.type === "Identifier" && receiver.name === parameter
    ? getPropertyName(node)
    : null;
}

function meaningfulBound(operator: string, bound: number): boolean {
  if (operator === ">") return bound < Number.MAX_SAFE_INTEGER;
  if (operator === ">=") return bound > Number.MIN_SAFE_INTEGER;
  if (operator === "<") return bound > Number.MIN_SAFE_INTEGER;
  return operator === "<=" && bound < Number.MAX_SAFE_INTEGER;
}

/** Later schema wrappers or an opaque enclosing call may own validation order. */
function finalSchema(node: ESTree.CallExpression): boolean {
  const value = outerExpression(node);
  const parent = parentOf(value);
  return (
    (parent?.type === "VariableDeclarator" && parent.init === value) ||
    (parent?.type === "ReturnStatement" && parent.argument === value) ||
    (parent?.type === "ExportDefaultDeclaration" && parent.declaration === value)
  );
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Declare a pure integer field range on its Zod field schema instead of an object refinement.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      fieldBounds:
        "Declare the range for `{{field}}` on its integer field schema; review validation error paths and order before replacing this object refinement.",
    },
  },
  createOnce(context) {
    let stableImports = new WeakMap<TsVariable, boolean>();

    function factory(node: Node): string | null {
      node = unwrapExpression(node);
      if (node.type === "Identifier") {
        const definition = imported(node);
        return definition?.type === "ImportSpecifier" ? importSpecifierName(definition) : null;
      }
      if (node.type !== "MemberExpression" || node.computed || node.optional) return null;
      const receiver = unwrapExpression(node.object);
      if (receiver.type !== "Identifier") return null;
      const definition = imported(receiver);
      return definition !== null &&
        (definition.type === "ImportNamespaceSpecifier" || importSpecifierName(definition) === "z")
        ? getPropertyName(node)
        : null;
    }

    function imported(
      identifier: Identifier,
    ): ESTree.ImportSpecifier | ESTree.ImportNamespaceSpecifier | null {
      const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
      const definition = variable?.defs[0]?.node;
      if (
        variable?.defs.length !== 1 ||
        (definition?.type !== "ImportSpecifier" && definition?.type !== "ImportNamespaceSpecifier")
      )
        return null;
      const declaration = parentOf(definition);
      if (
        declaration?.type !== "ImportDeclaration" ||
        declaration.importKind === "type" ||
        !FULL_ZOD_MODULES.has(declaration.source.value) ||
        (definition.type === "ImportSpecifier" && definition.importKind === "type")
      )
        return null;
      let stable = stableImports.get(variable);
      if (stable === undefined) {
        stable = stableValueBinding(variable, (reference) => {
          if (typeOnlyReference(reference)) return true;
          const value = outerExpression(reference.identifier);
          const parent = parentOf(value);
          if (parent?.type === "CallExpression" && parent.callee === value && !parent.optional)
            return true;
          if (
            parent?.type !== "MemberExpression" ||
            parent.object !== value ||
            parent.computed ||
            parent.optional ||
            writtenMember(parent)
          )
            return false;
          const member = outerExpression(parent);
          const use = parentOf(member);
          return use?.type === "CallExpression" && use.callee === member && !use.optional;
        });
        stableImports.set(variable, stable);
      }
      return stable ? definition : null;
    }

    function integerField(node: Node): boolean {
      node = unwrapExpression(node);
      if (node.type !== "CallExpression" || node.optional || node.arguments.length !== 0)
        return false;
      const member = unwrapExpression(node.callee);
      if (
        member.type !== "MemberExpression" ||
        member.computed ||
        member.optional ||
        getPropertyName(member) !== "int"
      )
        return false;
      const base = unwrapExpression(member.object);
      return (
        base.type === "CallExpression" &&
        !base.optional &&
        base.arguments.length === 0 &&
        factory(base.callee) === "number"
      );
    }

    function fieldShape(node: Node, field: string): boolean {
      node = unwrapExpression(node);
      if (
        node.type !== "CallExpression" ||
        node.optional ||
        node.arguments.length !== 1 ||
        factory(node.callee) !== "object"
      )
        return false;
      const [shape] = node.arguments;
      if (shape?.type !== "ObjectExpression") return false;
      let found = false;
      const names = new Set<string>();
      for (const property of shape.properties) {
        if (
          property.type !== "Property" ||
          property.computed ||
          property.kind !== "init" ||
          property.method ||
          property.shorthand
        )
          return false;
        const name = getPropertyName(property);
        if (
          name === null ||
          name === "__proto__" ||
          names.has(name) ||
          !primitiveField(property.value)
        )
          return false;
        names.add(name);
        if (name === field) found = integerField(property.value);
      }
      return found;
    }

    function primitiveField(node: Node): boolean {
      if (integerField(node)) return true;
      node = unwrapExpression(node);
      if (node.type !== "CallExpression" || node.optional || node.arguments.length !== 0)
        return false;
      const name = factory(node.callee);
      return name !== null && PRIMITIVE_FACTORIES.has(name);
    }

    return {
      before() {
        stableImports = new WeakMap();
        return isGeneratedFile(
          { filename: context.filename, cwd: context.cwd },
          context.sourceCode.text,
        )
          ? false
          : undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (node.optional || node.arguments.length !== 1) return;
        const member = unwrapExpression(node.callee);
        if (
          member.type !== "MemberExpression" ||
          member.optional ||
          member.computed ||
          getPropertyName(member) !== "refine"
        )
          return;
        const [predicate] = node.arguments;
        if (predicate === undefined || predicate.type === "SpreadElement") return;
        const field = boundedField(predicate);
        if (
          field === null ||
          SCHEMA_INTEGER_FIELD_MINIMUMS.has(field) ||
          !finalSchema(node) ||
          !fieldShape(member.object, field)
        )
          return;
        context.report({ node: member.property, messageId: "fieldBounds", data: { field } });
      },
    };
  },
});
