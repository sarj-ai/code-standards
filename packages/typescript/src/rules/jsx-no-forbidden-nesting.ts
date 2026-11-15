/** @fileoverview jsx-no-forbidden-nesting — intrinsic JSX elements nested where HTML forbids them. */
import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { isErasedExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { nestingViolation } from "./_nesting-violation.js";
import { attributeString, effectiveAttribute } from "./_web-jsx.js";

const NAME = "jsx-no-forbidden-nesting";

const FOREIGN_ROOTS: ReadonlySet<string> = new Set(["svg", "math"]);
const FRESH_CONTEXTS: ReadonlySet<string> = new Set(["foreignObject", "template"]);
const ALWAYS_INTERACTIVE: ReadonlySet<string> = new Set(["button", "details", "embed", "iframe", "select", "textarea"]);
const RENDERING_ARRAY_METHODS: ReadonlySet<string> = new Set(["map", "flatMap"]);

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Keep intrinsic JSX elements out of parents whose HTML content model forbids them.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      parserChild:
        "HTML forbids <{{tag}}> as a direct child of <{{ancestor}}>. The browser parser moves it, and React reports a hydration error. Place <{{tag}}> under a parent that accepts it.",
      tableRow:
        "HTML forbids <tr> as a direct child of <table>. The browser parser inserts a <tbody>, and React reports a hydration error. Wrap the rows in <tbody>, <thead> or <tfoot>.",
      parserDescendant:
        "HTML forbids <{{tag}}> inside <{{ancestor}}>. The browser parser closes <{{ancestor}}> before <{{tag}}>, and React reports a hydration error. Make the two elements siblings, or change the outer element to one that accepts <{{tag}}>.",
      contentModel:
        "HTML forbids <{{tag}}> inside <{{ancestor}}>. The browser keeps the nesting, but clicks, focus and screen readers handle the inner element inconsistently. Make the two elements siblings. Give a stray <li> a <ul>, <ol> or <menu> parent.",
    },
  },
  createOnce(context) {
    return {
      before(): boolean | void {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text))
          return false;
      },
      JSXElement(node: ESTree.JSXElement): void {
        const tag = intrinsicTag(node);
        if (tag === null) return;
        const ancestors = visibleAncestors(node);
        if (ancestors === null) return;
        const violation = nestingViolation(tag, ancestors, isInteractive(node.openingElement, tag, context.sourceCode));
        if (violation === null) return;
        const messageId = tag === "tr" && violation.ancestor === "table" ? "tableRow" : violation.kind;
        context.report({ node: node.openingElement, messageId, data: { tag, ancestor: violation.ancestor } });
      },
    };
  },
});

function intrinsicTag(node: ESTree.JSXElement): string | null {
  const name = node.openingElement.name;
  return name.type === "JSXIdentifier" && /^[a-z]/u.test(name.name) ? name.name : null;
}

function visibleAncestors(node: ESTree.JSXElement): string[] | null {
  const ancestors: string[] = [];
  for (let element = renderingParent(node); element !== null; element = renderingParent(element)) {
    const tag = intrinsicTag(element);
    if (tag === null || FRESH_CONTEXTS.has(tag)) break;
    if (FOREIGN_ROOTS.has(tag)) return null;
    ancestors.push(tag);
  }
  return ancestors;
}

function renderingParent(element: ESTree.JSXElement): ESTree.JSXElement | null {
  let child: Node = element;
  for (let parent: Node | null = element.parent; parent !== null; parent = child.parent) {
    if (parent.type === "JSXElement") return parent;
    const next = renderedThrough(parent, child);
    if (next === null) return null;
    child = next;
  }
  return null;
}

function renderedThrough(node: Node, child: Node): Node | null {
  switch (node.type) {
    case "JSXFragment":
    case "JSXExpressionContainer":
    case "ArrayExpression":
    case "LogicalExpression":
    case "ChainExpression":
      return node;
    case "ConditionalExpression":
      return child === node.test ? null : node;
    case "ArrowFunctionExpression":
      return renderingCall(node);
    case "ReturnStatement": {
      const callback = returningFunction(node);
      return callback === null ? null : renderingCall(callback);
    }
    default:
      return isErasedExpression(node) ? node : null;
  }
}

function returningFunction(statement: ESTree.ReturnStatement): ESTree.ArrowFunctionExpression | ESTree.Function | null {
  for (let node: Node | null = statement.parent; node !== null; node = node.parent) {
    if (
      node.type === "ArrowFunctionExpression" ||
      node.type === "FunctionExpression" ||
      node.type === "FunctionDeclaration"
    )
      return node;
  }
  return null;
}

function renderingCall(callback: ESTree.ArrowFunctionExpression | ESTree.Function): ESTree.CallExpression | null {
  const call = callback.parent;
  if (call?.type !== "CallExpression" || call.arguments[0] !== callback) return null;
  const callee = call.callee;
  return callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.property.type === "Identifier" &&
    RENDERING_ARRAY_METHODS.has(callee.property.name)
    ? call
    : null;
}

function isInteractive(opening: ESTree.JSXOpeningElement, tag: string, source: SourceCode): boolean {
  if (ALWAYS_INTERACTIVE.has(tag)) return true;
  switch (tag) {
    case "a":
      return hasExplicitAttribute(opening, ["href"]);
    case "input": {
      const type = attributeString(opening, source, ["type"]);
      return type !== null && type.toLowerCase() !== "hidden";
    }
    case "audio":
    case "video":
      return hasExplicitAttribute(opening, ["controls"]);
    case "img":
      return hasExplicitAttribute(opening, ["useMap", "usemap"]);
    default:
      return false;
  }
}

function hasExplicitAttribute(opening: ESTree.JSXOpeningElement, names: readonly string[]): boolean {
  const attribute = effectiveAttribute(opening, names);
  if (attribute?.type !== "JSXAttribute") return false;
  const value = attribute.value?.type === "JSXExpressionContainer" ? attribute.value.expression : null;
  return !(value?.type === "Literal" && (value.value === false || value.value === null));
}
