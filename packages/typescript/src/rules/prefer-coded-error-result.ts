/** @fileoverview prefer-coded-error-result — preserve failure identities and format their context at the consumer. */

import {
  defineRule,
  type ESTree,
  type Identifier,
  type Node,
  type SourceCode,
  type TsVariable,
} from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile } from "../utils/paths.js";
import {
  enclosingFunction,
  stableConstInitializer,
  stableValueBinding,
} from "../utils/stable-value-binding.js";
import { findVariable } from "../utils/static-string.js";
import { typeBinding } from "../utils/type-binding.js";

const NAME = "prefer-coded-error-result";
const MAX_DEPTH = 16;
const MAX_VARIANTS = 64;
const MAX_TYPE_STEPS = 256;
const BOOLEAN_STATUS_NAMES = ["ok", "success"] as const;
const STRING_STATUS_NAMES = ["status", "state", "kind", "type", "tag"] as const;
const STATUS_NAMES: readonly string[] = [
  ...BOOLEAN_STATUS_NAMES,
  ...STRING_STATUS_NAMES,
];
const CODE_NAMES = ["code", "kind", "type", "tag"] as const;
const SUCCESS_TAGS: ReadonlySet<string> = new Set(["ok", "success"]);
const FAILURE_TAGS: ReadonlySet<string> = new Set([
  "err",
  "error",
  "failure",
  "failed",
]);
const NATIVE_ERRORS: ReadonlySet<string> = new Set([
  "Error",
  "EvalError",
  "RangeError",
  "ReferenceError",
  "SyntaxError",
  "TypeError",
  "URIError",
  "AggregateError",
]);

interface TypeView {
  readonly node: ESTree.TSType | ESTree.TSInterfaceBody;
  readonly origin: Node;
  readonly bindings: ReadonlyMap<TsVariable, TypeView>;
}

interface WalkBudget {
  remaining: number;
}

type Properties = ReadonlyMap<string, ESTree.TSPropertySignature>;

interface ObjectVariant {
  readonly member: TypeView;
  readonly fields: Properties | null;
}

interface ProducerIssue {
  readonly node: Node;
  readonly messageId: "preferCodedErrorResult" | "formatAtConsumer";
}

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
  if (node.typeName.type !== "Identifier")
    return libraryResult(node, source) ? value : null;
  const variable = typeBinding(source, node.typeName);
  if (variable === null || variable.defs.length === 0) return value;
  const bound = value.bindings.get(variable);
  if (bound !== undefined) return resolve(bound, source, depth + 1);
  const declaration =
    variable.defs.length === 1 ? variable.defs[0]?.node : undefined;
  if (
    declaration?.type !== "TSTypeAliasDeclaration" &&
    declaration?.type !== "TSInterfaceDeclaration"
  )
    return libraryResult(node, source) ? value : null;
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

function outcomeTag(
  property: ESTree.TSPropertySignature | undefined,
  owner: TypeView,
  source: SourceCode,
  name: string,
): boolean | null {
  if (property === undefined || property.optional) return null;
  const type = propertyView(property, owner);
  const resolved = type === null ? null : resolve(type, source);
  const node = resolved?.node;
  return node?.type === "TSLiteralType" && node.literal.type === "Literal"
    ? outcomeValue(name, node.literal.value)
    : null;
}

function outcomeValue(name: string, value: unknown): boolean | null {
  if (BOOLEAN_STATUS_NAMES.some((candidate) => candidate === name))
    return typeof value === "boolean" ? value : null;
  if (
    !STRING_STATUS_NAMES.some((candidate) => candidate === name) ||
    typeof value !== "string"
  )
    return null;
  const tag = value.toLowerCase();
  return SUCCESS_TAGS.has(tag) ? true : FAILURE_TAGS.has(tag) ? false : null;
}

/** A required code of unresolved or imported type is left to its owning type checker. */
function hasCode(
  fields: Properties,
  owner: TypeView,
  source: SourceCode,
  ignoredCodes: readonly string[] = [],
): boolean {
  return CODE_NAMES.some((name) => {
    if (ignoredCodes.includes(name)) return false;
    const property = fields.get(name);
    if (property === undefined || property.optional) return false;
    const type = propertyView(property, owner);
    return type !== null && openScalar(type, source) === null;
  });
}

function openScalar(
  value: TypeView,
  source: SourceCode,
  depth = 0,
  budget: WalkBudget = { remaining: MAX_TYPE_STEPS },
): Node | null {
  if (depth >= MAX_DEPTH || --budget.remaining < 0) return null;
  const resolved = resolve(value, source);
  if (resolved === null) return null;
  if (
    resolved.node.type === "TSStringKeyword" ||
    resolved.node.type === "TSUnknownKeyword"
  )
    return resolved.origin;
  if (
    resolved.node.type !== "TSUnionType" ||
    resolved.node.types.length > MAX_VARIANTS
  )
    return null;
  for (const member of resolved.node.types) {
    const broad = openScalar(
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
  if (
    resolved.node.type === "TSStringKeyword" ||
    resolved.node.type === "TSUnknownKeyword"
  )
    return resolved.origin;
  if (nativeErrorType(resolved.node, source)) return resolved.origin;
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

function nativeErrorType(node: TypeView["node"], source: SourceCode): boolean {
  if (
    node.type !== "TSTypeReference" ||
    node.typeName.type !== "Identifier" ||
    !NATIVE_ERRORS.has(node.typeName.name) ||
    (node.typeArguments?.params.length ?? 0) !== 0
  )
    return false;
  const binding = typeBinding(source, node.typeName);
  return binding === null || binding.defs.length === 0;
}

function weakObject(
  fields: Properties,
  owner: TypeView,
  source: SourceCode,
  depth: number,
  budget: WalkBudget,
  ignoredCodes: readonly string[] = [],
): Node | null {
  const code = openStringField(
    fields,
    owner,
    source,
    CODE_NAMES.filter((name) => !ignoredCodes.includes(name)),
    budget,
  );
  if (code !== null) return code;
  // A separate typed error payload can preserve identity even when a display message also exists.
  const error = fields.get("error");
  if (error !== undefined) {
    const inner = propertyView(error, owner);
    return inner === null || error.optional
      ? null
      : weakError(inner, source, depth + 1, budget);
  }
  const carriers = [...fields].filter(([name]) => errorCarrier(name));
  if (carriers.length > 1) return null;
  const carrier = carriers[0]?.[1];
  if (carrier !== undefined) {
    const inner = propertyView(carrier, owner);
    return inner === null || carrier.optional
      ? null
      : weakError(inner, source, depth + 1, budget);
  }
  return openStringField(fields, owner, source, ["message", "reason"], budget);
}

function errorCarrier(name: string): boolean {
  return name === "error" || name === "errorMessage" || name.endsWith("Error");
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
    const broad = inner === null ? null : openScalar(inner, source, 0, budget);
    if (broad !== null) return broad;
  }
  return null;
}

/** Preserve contract precedence through unshadowed native promise annotations. */
function outcomeFailures(
  value: TypeView,
  source: SourceCode,
  depth = 0,
  budget: WalkBudget = { remaining: MAX_TYPE_STEPS },
): readonly Node[] {
  if (depth >= MAX_DEPTH || --budget.remaining < 0) return [];
  const resolved = resolve(value, source);
  if (resolved === null) return [];
  const structural = failureMessages(resolved, source);
  if (structural.length !== 0) return structural;
  const library = libraryError(resolved, source);
  if (library !== null) return [library];
  const node = resolved.node;
  if (node.type !== "TSTypeReference") return [];
  if (
    node.typeName.type !== "Identifier" ||
    !["Promise", "PromiseLike"].includes(node.typeName.name) ||
    (typeBinding(source, node.typeName)?.defs.length ?? 0) !== 0 ||
    node.typeArguments?.params.length !== 1
  )
    return [];
  const argument = node.typeArguments.params[0];
  return argument === undefined
    ? []
    : outcomeFailures(
        { ...resolved, node: argument, origin: argument },
        source,
        depth + 1,
        budget,
      );
}

function failureMessages(value: TypeView, source: SourceCode): readonly Node[] {
  const members = variants(value, source);
  if (members === null || members.length < 2) return [];
  const objects = members.map((member) => ({
    member,
    fields: properties(member),
  }));
  if (objects.some((object) => object.fields === null)) return [];
  let selected: readonly (boolean | null)[] | null = null;
  const discriminators: string[] = [];
  for (const status of STATUS_NAMES) {
    const tags = objects.map((object) =>
      outcomeTag(object.fields?.get(status), object.member, source, status),
    );
    if (
      tags.some((tag) => tag === null) ||
      !tags.includes(true) ||
      !tags.includes(false)
    )
      continue;
    if (
      selected !== null &&
      tags.some((tag, index) => tag !== selected?.[index])
    )
      return [];
    discriminators.push(status);
    if (selected === null) {
      selected = tags;
    }
  }
  if (selected === null) return presenceFailures(objects, source);
  const tags = selected;
  if (
    objects.some(
      (object, index) =>
        tags[index] === true &&
        [...(object.fields?.keys() ?? [])].some(
          (name) => name === "errors" || errorCarrier(name),
        ),
    )
  )
    return [];
  return objects.flatMap((object, index) => {
    if (
      tags[index] !== false ||
      object.fields === null ||
      hasCode(object.fields, object.member, source, discriminators) ||
      ["data", "value", "result"].some((name) => object.fields?.has(name))
    )
      return [];
    const error = weakObject(
      object.fields,
      object.member,
      source,
      0,
      { remaining: MAX_TYPE_STEPS },
      discriminators,
    );
    return error === null ? [] : [error];
  });
}

/** A required error property and one disjoint required success value establish this presence-selected Result. */
function presenceFailures(
  objects: readonly ObjectVariant[],
  source: SourceCode,
): readonly Node[] {
  const failed = objects.filter((object) => object.fields?.has("error"));
  const successful = objects.filter((object) => !object.fields?.has("error"));
  if (failed.length === 0 || successful.length === 0) return [];
  let successKey: string | null = null;
  for (const object of successful) {
    if (object.fields === null || object.fields.size !== 1) return [];
    const property = [...object.fields][0];
    if (
      property === undefined ||
      property[1].optional ||
      errorCarrier(property[0]) ||
      property[0] === "errors" ||
      STATUS_NAMES.includes(property[0]) ||
      CODE_NAMES.some((name) => name === property[0])
    )
      return [];
    if (successKey !== null && successKey !== property[0]) return [];
    successKey = property[0];
  }
  if (successKey === null) return [];
  const key = successKey;
  if (
    failed.some(
      (object) =>
        object.fields?.get("error")?.optional || object.fields?.has(key),
    )
  )
    return [];
  return failed.flatMap((object) => {
    if (object.fields === null || hasCode(object.fields, object.member, source))
      return [];
    const error = object.fields.get("error");
    const inner =
      error === undefined ? null : propertyView(error, object.member);
    const weak = inner === null ? null : weakError(inner, source);
    return weak === null ? [] : [weak];
  });
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
function libraryError(value: TypeView, source: SourceCode): Node | null {
  const reference = value.node;
  if (reference.type !== "TSTypeReference" || !libraryResult(reference, source))
    return null;
  if (reference.typeArguments?.params.length !== 2) return null;
  const error = reference.typeArguments.params[1];
  return error === undefined
    ? null
    : weakError({ ...value, node: error, origin: error }, source);
}

function libraryResult(
  reference: ESTree.TSTypeReference,
  source: SourceCode,
): boolean {
  return ["Result", "ResultAsync"].includes(
    libraryName(reference.typeName, source, true) ?? "",
  );
}

/** Import symbols prove library identity; unrelated names, computed members and type-only value imports abstain. */
function libraryName(
  node: Node,
  source: SourceCode,
  typeSpace: boolean,
): string | null {
  const reference = libraryReference(node);
  if (reference === null) return null;
  const { root, member } = reference;
  const variable = typeSpace
    ? typeBinding(source, root)
    : findVariable(source.getScope(root), root.name);
  const definition =
    variable?.defs.length === 1 ? variable.defs[0]?.node : undefined;
  if (
    definition?.type !== "ImportSpecifier" &&
    definition?.type !== "ImportNamespaceSpecifier"
  )
    return null;
  if (variable === null || !stableValueBinding(variable)) return null;
  const declaration = parentOf(definition);
  if (
    declaration?.type !== "ImportDeclaration" ||
    declaration.source.value !== "neverthrow"
  )
    return null;
  if (
    !typeSpace &&
    (declaration.importKind === "type" ||
      (definition.type === "ImportSpecifier" &&
        definition.importKind === "type"))
  )
    return null;
  return member === null && definition.type === "ImportSpecifier"
    ? importSpecifierName(definition)
    : member !== null && definition.type === "ImportNamespaceSpecifier"
      ? member
      : null;
}

function libraryReference(
  node: Node,
): { readonly root: Identifier; readonly member: string | null } | null {
  if (node.type === "Identifier") return { root: node, member: null };
  if (
    node.type === "TSQualifiedName" &&
    node.left.type === "Identifier" &&
    node.right.type === "Identifier"
  )
    return { root: node.left, member: node.right.name };
  if (
    node.type === "MemberExpression" &&
    !node.computed &&
    !node.optional &&
    node.object.type === "Identifier" &&
    node.property.type === "Identifier"
  )
    return { root: node.object, member: node.property.name };
  return null;
}

/** A literal coded failure still loses presentation ownership when it renders its context here. */
function renderedFailure(node: Node, source: SourceCode): ProducerIssue | null {
  let value = unwrapExpression(node);
  if (value.type === "AwaitExpression")
    value = unwrapExpression(value.argument);
  if (value.type === "CallExpression" || value.type === "NewExpression") {
    if (
      (value.type === "CallExpression" && value.optional) ||
      value.arguments.length !== 1
    )
      return null;
    const name = libraryName(value.callee, source, false);
    if (
      value.type === "NewExpression"
        ? name !== "Err"
        : name !== "err" && name !== "errAsync"
    )
      return null;
    const argument = value.arguments[0];
    if (argument === undefined || argument.type === "SpreadElement")
      return null;
    return renderedPayload(argument, source);
  }
  const outer = objectFields(value);
  if (outer === null) return null;
  const discriminators = STATUS_NAMES.filter((name) => {
    const status = outer.get(name);
    return (
      status?.type === "Literal" && outcomeValue(name, status.value) === false
    );
  });
  if (discriminators.length === 0) return null;
  if (
    STATUS_NAMES.some((name) => {
      const status = outer.get(name);
      return (
        status?.type === "Literal" && outcomeValue(name, status.value) === true
      );
    }) ||
    ["data", "value", "result"].some((name) => outer.has(name))
  )
    return null;
  const error = outer.get("error");
  return renderedPayload(
    error ?? value,
    source,
    error === undefined ? discriminators : [],
  );
}

function renderedPayload(
  node: Node,
  source: SourceCode,
  ignoredCodes: readonly string[] = [],
): ProducerIssue | null {
  if (renderedString(node, source))
    return { node, messageId: "preferCodedErrorResult" };
  const fields = objectFields(unwrapExpression(node));
  if (fields === null) return null;
  const codes = CODE_NAMES.filter(
    (name) => !ignoredCodes.includes(name) && fields.has(name),
  );
  const coded = codes.some((name) => {
    const code = fields.get(name);
    return code?.type === "Literal" && typeof code.value === "string";
  });
  if (codes.length !== 0 && !coded) return null;
  const primary = fields.get("error");
  const carriers = [...fields].filter(([name]) => errorCarrier(name));
  if (primary === undefined && carriers.length > 1) return null;
  const carrier = primary ?? carriers[0]?.[1];
  if (!coded && carrier !== undefined)
    return renderedString(carrier, source)
      ? { node: carrier, messageId: "preferCodedErrorResult" }
      : null;
  for (const [name, value] of fields) {
    if (
      (name === "message" || name === "reason" || errorCarrier(name)) &&
      renderedString(value, source)
    )
      return {
        node: value,
        messageId: coded ? "formatAtConsumer" : "preferCodedErrorResult",
      };
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

/** Own one bounded traversal; neither constant detection nor rendering executes application values. */
function renderedString(node: Node, source: SourceCode): boolean {
  let remaining = MAX_TYPE_STEPS;
  function literalComposition(input: Node, depth: number): boolean | null {
    if (depth >= MAX_DEPTH || --remaining < 0) return null;
    const value = unwrapExpression(input);
    if (value.type === "Identifier") {
      const initializer = stableConstInitializer(source, value);
      return initializer === null
        ? false
        : literalComposition(initializer.value, depth + 1);
    }
    if (value.type === "Literal")
      return (
        value.value === null ||
        ["string", "number", "boolean", "bigint"].includes(typeof value.value)
      );
    const children =
      value.type === "TemplateLiteral"
        ? value.expressions
        : value.type === "BinaryExpression" && value.operator === "+"
          ? [value.left, value.right]
          : null;
    if (children === null) return false;
    for (const child of children) {
      const constant = literalComposition(child, depth + 1);
      if (constant !== true) return constant;
    }
    return true;
  }
  function rendered(input: Node, depth: number): boolean {
    if (depth >= MAX_DEPTH || --remaining < 0) return false;
    const value = unwrapExpression(input);
    if (value.type === "TemplateLiteral") return value.expressions.length > 0;
    if (value.type !== "BinaryExpression" || value.operator !== "+")
      return false;
    return [value.left, value.right].some(
      (part) =>
        (part.type === "Literal" && typeof part.value === "string") ||
        rendered(part, depth + 1),
    );
  }
  return literalComposition(node, 0) === false && rendered(node, 0);
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
        "This Result failure hides its identity in a broad string, unknown, or generic Error channel. Expose expected failures as finite domain error codes with the typed context needed by the caller, and format the message at the consumer. Review intentional infrastructure and presentation boundaries explicitly.",
      formatAtConsumer:
        "This coded failure formats context into a message at the producer. Return the code and typed context, and let the consumer format the message. Preserve an intentional presentation boundary explicitly.",
    },
  },
  createOnce(context) {
    const reported = new Set<Node>();
    function check(node: ESTree.TSUnionType | ESTree.TSTypeReference): void {
      for (const candidate of outcomeFailures(view(node), context.sourceCode)) {
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
      const rendered = renderedFailure(value, context.sourceCode);
      if (rendered === null || reported.has(rendered.node)) return;
      const contract = owner.returnType?.typeAnnotation;
      if (
        contract !== undefined &&
        outcomeFailures(view(contract), context.sourceCode).length !== 0
      )
        return;
      reported.add(rendered.node);
      context.report(rendered);
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
