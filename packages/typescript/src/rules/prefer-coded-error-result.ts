/** @fileoverview prefer-coded-error-result — preserve failure identities and format their context at the consumer. */

import {
  defineRule,
  type ESTree,
  type Node,
  type SourceCode,
  type TsVariable,
} from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile } from "../utils/paths.js";
import { enclosingFunction } from "../utils/stable-value-binding.js";
import { typeBinding } from "../utils/type-binding.js";

const NAME = "prefer-coded-error-result";
const MAX_DEPTH = 16;
const MAX_VARIANTS = 64;
const MAX_TYPE_STEPS = 256;
const STATUS_NAMES = ["ok", "success"] as const;
const CODE_NAMES = ["code", "kind", "type", "tag"] as const;

interface TypeView {
  readonly node: ESTree.TSType | ESTree.TSInterfaceBody;
  readonly origin: Node;
  readonly bindings: ReadonlyMap<TsVariable, TypeView>;
}

interface WalkBudget {
  remaining: number;
}

type Properties = ReadonlyMap<string, ESTree.TSPropertySignature>;

function view(node: ESTree.TSType): TypeView {
  return { node, origin: node, bindings: new Map() };
}

function resolve(
  value: TypeView,
  source: SourceCode,
  depth = 0,
): TypeView | null {
  if (depth >= MAX_DEPTH) return null;
  const node = value.node;
  if (node.type !== "TSTypeReference") return value;
  if (node.typeName.type !== "Identifier") return null;
  const variable = typeBinding(source, node.typeName);
  if (variable === null) return null;
  const bound = value.bindings.get(variable);
  if (bound !== undefined) return resolve(bound, source, depth + 1);
  const declaration =
    variable.defs.length === 1 ? variable.defs[0]?.node : undefined;
  if (
    declaration?.type !== "TSTypeAliasDeclaration" &&
    declaration?.type !== "TSInterfaceDeclaration"
  )
    return null;
  if (
    declaration.type === "TSInterfaceDeclaration" &&
    declaration.extends.length !== 0
  )
    return null;
  const bindings = bindArguments(declaration, node, value, source);
  if (bindings === null) return null;
  return resolve(
    {
      node:
        declaration.type === "TSTypeAliasDeclaration"
          ? declaration.typeAnnotation
          : declaration.body,
      origin: value.origin,
      bindings,
    },
    source,
    depth + 1,
  );
}

function bindArguments(
  declaration: ESTree.TSTypeAliasDeclaration | ESTree.TSInterfaceDeclaration,
  reference: ESTree.TSTypeReference,
  outer: TypeView,
  source: SourceCode,
): ReadonlyMap<TsVariable, TypeView> | null {
  const parameters = declaration.typeParameters?.params ?? [];
  const arguments_ = reference.typeArguments?.params ?? [];
  if (arguments_.length > parameters.length) return null;
  const bindings = new Map<TsVariable, TypeView>();
  for (const [index, parameter] of parameters.entries()) {
    const variable = typeBinding(source, parameter.name);
    if (variable === null) return null;
    const argument = arguments_[index];
    if (argument !== undefined)
      bindings.set(variable, {
        node: argument,
        origin: argument,
        bindings: outer.bindings,
      });
    else if (parameter.default !== null)
      bindings.set(variable, {
        node: parameter.default,
        origin: reference,
        bindings,
      });
  }
  return bindings;
}

function properties(value: TypeView): Properties | null {
  const node = value.node;
  const members =
    node.type === "TSTypeLiteral"
      ? node.members
      : node.type === "TSInterfaceBody"
        ? node.body
        : null;
  if (members === null) return null;
  const result = new Map<string, ESTree.TSPropertySignature>();
  for (const member of members) {
    if (
      member.type !== "TSPropertySignature" ||
      member.computed ||
      member.typeAnnotation === null
    )
      return null;
    const name =
      member.key.type === "Identifier"
        ? member.key.name
        : member.key.type === "Literal" && typeof member.key.value === "string"
          ? member.key.value
          : null;
    if (name === null || result.has(name)) return null;
    result.set(name, member);
  }
  return result;
}

function propertyView(
  property: ESTree.TSPropertySignature,
  owner: TypeView,
): TypeView | null {
  const node = property.typeAnnotation?.typeAnnotation;
  return node === undefined
    ? null
    : { node, origin: node, bindings: owner.bindings };
}

function booleanTag(
  property: ESTree.TSPropertySignature | undefined,
  owner: TypeView,
  source: SourceCode,
): boolean | null {
  if (property === undefined || property.optional) return null;
  const type = propertyView(property, owner);
  const resolved = type === null ? null : resolve(type, source);
  const node = resolved?.node;
  return node?.type === "TSLiteralType" &&
    node.literal.type === "Literal" &&
    typeof node.literal.value === "boolean"
    ? node.literal.value
    : null;
}

/** A required code of unknown or imported type is left to its owning type checker. */
function hasCode(
  fields: Properties,
  owner: TypeView,
  source: SourceCode,
): boolean {
  return CODE_NAMES.some((name) => {
    const property = fields.get(name);
    if (property === undefined || property.optional) return false;
    const type = propertyView(property, owner);
    return type !== null && openString(type, source) === null;
  });
}

function openString(
  value: TypeView,
  source: SourceCode,
  depth = 0,
  budget: WalkBudget = { remaining: MAX_TYPE_STEPS },
): Node | null {
  if (depth >= MAX_DEPTH || --budget.remaining < 0) return null;
  const resolved = resolve(value, source);
  if (resolved === null) return null;
  if (resolved.node.type === "TSStringKeyword") return resolved.origin;
  if (
    resolved.node.type !== "TSUnionType" ||
    resolved.node.types.length > MAX_VARIANTS
  )
    return null;
  for (const member of resolved.node.types) {
    const broad = openString(
      { ...resolved, node: member },
      source,
      depth + 1,
      budget,
    );
    if (broad !== null) return broad;
  }
  return null;
}

function weakError(
  value: TypeView,
  source: SourceCode,
  depth = 0,
  budget: WalkBudget = { remaining: MAX_TYPE_STEPS },
): Node | null {
  if (depth >= MAX_DEPTH || --budget.remaining < 0) return null;
  const resolved = resolve(value, source);
  if (resolved === null) return null;
  if (resolved.node.type === "TSStringKeyword") return resolved.origin;
  if (resolved.node.type === "TSUnionType") {
    if (resolved.node.types.length > MAX_VARIANTS) return null;
    for (const member of resolved.node.types) {
      const error = weakError(
        { ...resolved, node: member },
        source,
        depth + 1,
        budget,
      );
      if (error !== null) return error;
    }
    return null;
  }
  const fields = properties(resolved);
  if (fields === null || hasCode(fields, resolved, source)) return null;
  return weakObject(fields, resolved, source, depth, budget);
}

function weakObject(
  fields: Properties,
  owner: TypeView,
  source: SourceCode,
  depth: number,
  budget: WalkBudget,
): Node | null {
  const code = openStringField(fields, owner, source, CODE_NAMES, budget);
  if (code !== null) return code;
  // A separate typed error payload can preserve identity even when a display message also exists.
  const error = fields.get("error");
  if (error !== undefined) {
    const inner = propertyView(error, owner);
    return inner === null || error.optional
      ? null
      : weakError(inner, source, depth + 1, budget);
  }
  return openStringField(fields, owner, source, ["message", "reason"], budget);
}

function openStringField(
  fields: Properties,
  owner: TypeView,
  source: SourceCode,
  names: readonly string[],
  budget: WalkBudget,
): Node | null {
  for (const name of names) {
    const property = fields.get(name);
    if (property === undefined || property.optional) continue;
    const inner = propertyView(property, owner);
    const broad = inner === null ? null : openString(inner, source, 0, budget);
    if (broad !== null) return broad;
  }
  return null;
}

function failureMessages(value: TypeView, source: SourceCode): readonly Node[] {
  const members = variants(value, source);
  if (members === null || members.length < 2) return [];
  const objects = members.map((member) => ({
    member,
    fields: properties(member),
  }));
  if (objects.some((object) => object.fields === null)) return [];
  for (const status of STATUS_NAMES) {
    const tags = objects.map((object) =>
      booleanTag(object.fields?.get(status), object.member, source),
    );
    if (
      tags.some((tag) => tag === null) ||
      !tags.includes(true) ||
      !tags.includes(false)
    )
      continue;
    if (
      objects.some(
        (object, index) =>
          tags[index] === true &&
          ["error", "errors"].some((name) => object.fields?.has(name)),
      )
    )
      continue;
    return objects.flatMap((object, index) => {
      if (
        tags[index] !== false ||
        object.fields === null ||
        hasCode(object.fields, object.member, source)
      )
        return [];
      if (["data", "value", "result"].some((name) => object.fields?.has(name)))
        return [];
      const error = weakError(object.member, source);
      return error === null ? [] : [error];
    });
  }
  return [];
}

function variants(
  value: TypeView,
  source: SourceCode,
  depth = 0,
  budget: WalkBudget = { remaining: MAX_TYPE_STEPS },
): readonly TypeView[] | null {
  if (--budget.remaining < 0) return null;
  const resolved = resolve(value, source);
  if (resolved === null || depth >= MAX_DEPTH) return null;
  if (resolved.node.type !== "TSUnionType") return [resolved];
  const result: TypeView[] = [];
  for (const member of resolved.node.types) {
    const nested = variants(
      { ...resolved, node: member, origin: member },
      source,
      depth + 1,
      budget,
    );
    if (nested === null || result.length + nested.length > MAX_VARIANTS)
      return null;
    result.push(...nested);
  }
  return result;
}

/** Library identity, rather than the local name Result, establishes the generic error position. */
function libraryError(
  reference: ESTree.TSTypeReference,
  source: SourceCode,
): Node | null {
  if (
    reference.typeName.type !== "Identifier" ||
    reference.typeArguments?.params.length !== 2
  )
    return null;
  const variable = typeBinding(source, reference.typeName);
  const definition =
    variable?.defs.length === 1 ? variable.defs[0]?.node : undefined;
  if (definition?.type !== "ImportSpecifier") return null;
  const declaration = parentOf(definition);
  if (
    declaration?.type !== "ImportDeclaration" ||
    declaration.source.value !== "neverthrow"
  )
    return null;
  if (
    !["Result", "ResultAsync"].includes(importSpecifierName(definition) ?? "")
  )
    return null;
  const error = reference.typeArguments.params[1];
  return error === undefined ? null : weakError(view(error), source);
}

/** Preserve contract precedence through unshadowed native promise annotations. */
function weakAnnotation(
  node: ESTree.TSType,
  source: SourceCode,
  depth = 0,
  budget: WalkBudget = { remaining: MAX_TYPE_STEPS },
): boolean {
  if (depth >= MAX_DEPTH || --budget.remaining < 0) return false;
  if (failureMessages(view(node), source).length !== 0) return true;
  if (node.type !== "TSTypeReference") return false;
  if (libraryError(node, source) !== null) return true;
  if (
    node.typeName.type !== "Identifier" ||
    !["Promise", "PromiseLike"].includes(node.typeName.name) ||
    typeBinding(source, node.typeName) !== null ||
    node.typeArguments?.params.length !== 1
  )
    return false;
  const argument = node.typeArguments.params[0];
  return (
    argument !== undefined &&
    weakAnnotation(argument, source, depth + 1, budget)
  );
}

/** A literal coded failure still loses presentation ownership when it renders its context here. */
function renderedFailure(node: Node): Node | null {
  const outer = objectFields(unwrapExpression(node));
  if (
    outer === null ||
    !STATUS_NAMES.some((name) => {
      const status = outer.get(name);
      return status?.type === "Literal" && status.value === false;
    })
  )
    return null;
  const error = outer.get("error");
  const fields =
    error === undefined ? outer : objectFields(unwrapExpression(error));
  if (
    fields === null ||
    !CODE_NAMES.some((name) => {
      const code = fields.get(name);
      return code?.type === "Literal" && typeof code.value === "string";
    })
  )
    return null;
  for (const name of ["message", "reason"] as const) {
    const value = fields.get(name);
    if (value !== undefined && renderedString(value)) return value;
  }
  return null;
}

function objectFields(node: Node): ReadonlyMap<string, Node> | null {
  if (node.type !== "ObjectExpression") return null;
  const fields = new Map<string, Node>();
  for (const property of node.properties) {
    if (
      property.type !== "Property" ||
      property.computed ||
      property.kind !== "init" ||
      property.method
    )
      return null;
    const key =
      property.key.type === "Identifier"
        ? property.key.name
        : property.key.type === "Literal" &&
            typeof property.key.value === "string"
          ? property.key.value
          : null;
    if (key === null || fields.has(key)) return null;
    fields.set(key, property.value);
  }
  return fields;
}

function renderedString(node: Node, depth = 0): boolean {
  const value = unwrapExpression(node);
  if (depth >= MAX_DEPTH) return false;
  if (value.type === "TemplateLiteral") return value.expressions.length > 0;
  if (value.type !== "BinaryExpression" || value.operator !== "+") return false;
  return [value.left, value.right].some(
    (part) =>
      (part.type === "Literal" && typeof part.value === "string") ||
      renderedString(part, depth + 1),
  );
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Return a stable error code and typed context instead of only a rendered failure message.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferCodedErrorResult:
        "This Result failure carries only a rendered string or an open string code. Return a finite error code with the typed context needed by the caller, and format the message at the consumer. Keep an intentional presentation boundary explicit.",
      formatAtConsumer:
        "This coded failure formats context into a message at the producer. Return the code and typed context, and let the consumer format the message. Preserve an intentional presentation boundary explicitly.",
    },
  },
  createOnce(context) {
    const reported = new Set<Node>();
    function check(node: ESTree.TSUnionType | ESTree.TSTypeReference): void {
      const candidates = failureMessages(view(node), context.sourceCode);
      const library =
        node.type === "TSTypeReference"
          ? libraryError(node, context.sourceCode)
          : null;
      for (const candidate of library === null
        ? candidates
        : [...candidates, library]) {
        if (reported.has(candidate)) continue;
        reported.add(candidate);
        context.report({
          node: candidate,
          messageId: "preferCodedErrorResult",
        });
      }
    }
    function checkProducer(
      owner: ESTree.Function | ESTree.ArrowFunctionExpression | null,
      value: Node,
    ): void {
      if (owner === null) return;
      const rendered = renderedFailure(value);
      if (rendered === null || reported.has(rendered)) return;
      const contract = owner.returnType?.typeAnnotation;
      if (
        contract !== undefined &&
        weakAnnotation(contract, context.sourceCode)
      )
        return;
      reported.add(rendered);
      context.report({ node: rendered, messageId: "formatAtConsumer" });
    }
    return {
      before() {
        reported.clear();
        if (
          isGeneratedFile(
            { filename: context.filename, cwd: context.cwd },
            context.sourceCode.text,
          )
        )
          return false;
        return undefined;
      },
      TSUnionType: check,
      TSTypeReference: check,
      ReturnStatement(node) {
        if (node.argument !== null)
          checkProducer(enclosingFunction(node), node.argument);
      },
      ArrowFunctionExpression(node) {
        if (node.body.type !== "BlockStatement") checkProducer(node, node.body);
      },
    };
  },
});
