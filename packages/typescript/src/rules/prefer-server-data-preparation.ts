/**
 * @fileoverview prefer-server-data-preparation — prepare data projections before interactive client views.
 *
 * Port of the 18.x `prefer-server-data-preparation` rule. Typed: without
 * tsrs types it reports nothing, as the original returns no visitors without
 * a program. The walk keeps prop projections that pass the syntactic checks;
 * `Program:exit` runs the typed interaction and native-array proofs on them.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { forEachOwnAstChild, outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { nativeTypes, type NativeTypes, type TsNode } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { firstParameterBindings, parameterPath, reactHook, type RenderFunction, renderFunction } from "../utils/react-prop-bindings.js";
import { typeOnlyReference } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";

const NAME = "prefer-server-data-preparation";
const METHODS: ReadonlySet<string> = new Set(["map", "filter", "flatMap"]);
const DOM_EVENTS: ReadonlySet<string> = new Set(["onClick", "onChange", "onInput", "onSubmit"]);
const BINARY: ReadonlySet<string> = new Set(["===", "!==", "==", "!=", ">", ">=", "<", "<=", "+", "-", "*", "/", "%"]);
const UNARY: ReadonlySet<string> = new Set(["!", "+", "-", "~", "typeof"]);

type Callback = ESTree.ArrowFunctionExpression | ESTree.Function;

function clientDirective(program: ESTree.Program): boolean {
  for (const statement of program.body) {
    // Oxlint sets `directive` to null on ordinary expression statements.
    if (statement.type !== "ExpressionStatement" || statement.directive == null) return false;
    if (statement.directive === "use client") return true;
  }
  return false;
}

function projection(source: SourceCode, callback: Callback, mode: "data" | "view" = "data"): boolean {
  if (callback.async || callback.generator || callback.params.length !== 1) return false;
  const parameter = callback.params[0];
  const destructured = parameter?.type === "ObjectPattern";
  if (destructured && parameter.properties.some((property) =>
    property.type !== "Property" || property.computed || property.value.type !== "Identifier")) return false;
  const parameters = firstParameterBindings(source, callback);
  const body = parameters.size === 0 ? null : returnedExpression(callback);
  if (body === null) return false;
  let fieldRead = false;
  const inspect = (input: Node, depth: number): boolean => {
    if (depth > 64) return false;
    const node = unwrapExpression(input);
    if (parameterPath(source, node, parameters)) {
      if (node.type !== "MemberExpression" && !destructured) return false;
      fieldRead = true;
      return true;
    }
    const inspectChild = (child: Node): boolean => inspect(child, depth + 1);
    return valueProjection(node, inspectChild) || (mode === "view" && displayProjection(node, inspectChild));
  };
  return inspect(body, 0) && fieldRead;
}

/** The one expression a callback returns: an expression body, or a block holding a single `return <expression>`. */
function returnedExpression(callback: Callback): Node | null {
  const body = callback.body as Node | null;
  if (body?.type !== "BlockStatement") return body;
  const [statement] = body.body;
  return body.body.length === 1 && statement?.type === "ReturnStatement" ? statement.argument : null;
}

/** Literals and operator, array and object expressions built only from projected children. */
function valueProjection(node: Node, inspectChild: (child: Node) => boolean): boolean {
  switch (node.type) {
    case "Literal":
      return !("regex" in node);
    case "UnaryExpression":
      return UNARY.has(node.operator) && inspectChild(node.argument);
    case "BinaryExpression":
      return BINARY.has(node.operator) && inspectChild(node.left) && inspectChild(node.right);
    case "LogicalExpression":
      return inspectChild(node.left) && inspectChild(node.right);
    case "ConditionalExpression":
      return inspectChild(node.test) && inspectChild(node.consequent) && inspectChild(node.alternate);
    case "ArrayExpression":
      return node.elements.every((element) => element !== null && element.type !== "SpreadElement" && inspectChild(element));
    case "ObjectExpression":
      return node.properties.every((property) => property.type === "Property" && property.kind === "init" &&
        !property.method && !property.computed && inspectChild(property.value));
    default:
      return false;
  }
}

function displayProjection(node: Node, inspectChild: (child: Node) => boolean): boolean {
  if (node.type === "JSXElement") {
    return node.openingElement.attributes.every((attribute) =>
      attribute.type === "JSXAttribute" && (attribute.value === null || inspectChild(attribute.value))) &&
      node.children.every(inspectChild);
  }
  if (node.type === "JSXFragment") return node.children.every(inspectChild);
  if (node.type === "JSXText") return true;
  if (node.type === "JSXExpressionContainer") return node.expression.type === "JSXEmptyExpression" || inspectChild(node.expression);
  return false;
}

function onlyProjectedInput(source: SourceCode, receiver: Node, nativeArray: (node: ESTree.CallExpression) => boolean,
  cache: Map<TsVariable, boolean>): boolean {
  let root = unwrapExpression(receiver);
  while (root.type === "MemberExpression") root = unwrapExpression(root.object);
  if (root.type !== "Identifier") return false;
  const variable = findVariable(source.getScope(root), root.name);
  if (variable === null) return false;
  const cached = cache.get(variable);
  if (cached !== undefined) return cached;
  const projected = variable.references.every((reference) =>
    typeOnlyReference(reference) || (reference.isRead() && isProjectedRead(source, reference.identifier, nativeArray)));
  cache.set(variable, projected);
  return projected;
}

/** `input.items.map(callback)` on a native array, where `callback` only projects fields. */
function isProjectedRead(source: SourceCode, identifier: Node, nativeArray: (node: ESTree.CallExpression) => boolean): boolean {
  const call = projectionMethodCall(identifier);
  const callback = call?.arguments[0];
  return call !== null && (callback?.type === "ArrowFunctionExpression" || callback?.type === "FunctionExpression") &&
    (projection(source, callback) || projection(source, callback, "view")) && nativeArray(call);
}

/** The non-optional one-argument `.map`/`.filter`/`.flatMap` call at the end of a member chain from `identifier`. */
function projectionMethodCall(identifier: Node): ESTree.CallExpression | null {
  let access = outerExpression(identifier);
  let call = parentOf(access);
  while (call?.type === "MemberExpression" && call.object === access) {
    access = outerExpression(call);
    call = parentOf(access);
  }
  const member = unwrapExpression(access);
  if (call?.type !== "CallExpression" || call.callee !== access || call.optional || call.arguments.length !== 1) return null;
  return member.type === "MemberExpression" && !member.optional && METHODS.has(getPropertyName(member) ?? "") ? call : null;
}

function clientInteraction(source: SourceCode, node: Node, callable: (node: Node) => boolean): boolean {
  if (node.type === "ArrowFunctionExpression" || node.type === "FunctionExpression" || node.type === "FunctionDeclaration") return false;
  if (node.type === "CallExpression" && (reactHook(source, node.callee, "useState") || reactHook(source, node.callee, "useReducer"))) return true;
  if (node.type === "JSXOpeningElement" && node.name.type === "JSXIdentifier" && /^[a-z]/u.test(node.name.name) &&
    node.attributes.some((attribute) =>
      attribute.type === "JSXAttribute" && attribute.name.type === "JSXIdentifier" && DOM_EVENTS.has(attribute.name.name) &&
      attribute.value?.type === "JSXExpressionContainer" && attribute.value.expression.type !== "JSXEmptyExpression" &&
      callable(attribute.value.expression))) return true;
  return forEachOwnAstChild(node, (child) => clientInteraction(source, child, callable), (key) => key !== "tokens" && key !== "comments");
}

interface Candidate {
  readonly node: ESTree.CallExpression;
  readonly component: RenderFunction;
  readonly receiver: Node;
}

/** The original's typed checks, against tsrs. */
function typedProofs(native: NativeTypes) {
  const { checker, program, ast } = native;
  const callable = (node: Node): boolean => {
    const tsNode = native.node(unwrapExpression(node));
    if (tsNode === undefined) return false;
    const type = checker.getTypeAtLocation(tsNode);
    const members = type.isUnionType() ? type.getTypes() : [type];
    return members.some((member) => member.getCallSignatures().length > 0);
  };
  const nativeArray = (node: ESTree.CallExpression): boolean => {
    const callee = unwrapExpression(node.callee);
    if (callee.type !== "MemberExpression") return false;
    const object = native.node(unwrapExpression(callee.object));
    const call = native.node(node);
    if (object === undefined || call === undefined) return false;
    const receiver = checker.getNonNullableType(checker.getTypeAtLocation(object));
    const members = receiver.isUnionType() ? receiver.getTypes() : [receiver];
    if (!members.every((type) => checker.isArrayType(type) || checker.isTupleType(type))) return false;
    const handle = checker.getResolvedSignature(call).declaration;
    if (handle === undefined || program.getSourceFileMetadataByPath(handle.path)?.isDefaultLibrary !== true) return false;
    const declaration = handle.resolve(program.getProject()) as TsNode | undefined;
    const parent = declaration?.parent;
    return parent !== undefined && ast.isInterfaceDeclaration(parent) && ["Array", "ReadonlyArray"].includes(parent.name.text);
  };
  return { callable, nativeArray };
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Prepare data-only input collections before an interactive client view when possible.", url: docsUrl(NAME) },
    schema: [],
    messages: {
      prepareData:
        "Review preparing this prop-only collection in its producer or Server Component when the inputs are available there. Keep operations depending on unsaved edits or browser interaction reactive in the client.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: Candidate[] = [];
    return {
      before() {
        tsrs = null;
        candidates = [];
        const file = { filename: context.filename, cwd: context.cwd };
        if (isGeneratedFile(file, context.sourceCode.text) || isTestFile(file) || !clientDirective(context.sourceCode.ast)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      CallExpression(node) {
        const source = context.sourceCode;
        const callee = unwrapExpression(node.callee);
        if (node.optional || callee.type !== "MemberExpression" || callee.optional || node.arguments.length !== 1 ||
          !METHODS.has(getPropertyName(callee) ?? "")) return;
        const callback = node.arguments[0];
        if (callback?.type !== "ArrowFunctionExpression" && callback?.type !== "FunctionExpression") return;
        const component = renderFunction(node);
        if (component === null || !parameterPath(source, callee.object, firstParameterBindings(source, component)) ||
          !projection(source, callback)) return;
        candidates.push({ node, component, receiver: callee.object });
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        const source = context.sourceCode;
        const found = tsrs.run((file) => {
          const { callable, nativeArray } = typedProofs(nativeTypes(file));
          const interactions = new Map<Node, boolean>();
          const projectedInputs = new Map<TsVariable, boolean>();
          return candidates.map(({ component, receiver }) => {
            let interactive = interactions.get(component);
            if (interactive === undefined) {
              interactive = component.body !== null && clientInteraction(source, component.body, callable);
              interactions.set(component, interactive);
            }
            return interactive && onlyProjectedInput(source, receiver, nativeArray, projectedInputs);
          });
        });
        if (found === null) return;
        candidates.forEach(({ node }, i) => {
          if (found[i] === true) context.report({ node, messageId: "prepareData" });
        });
      },
    };
  },
});
