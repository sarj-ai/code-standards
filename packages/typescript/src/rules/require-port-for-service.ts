/**
 * @fileoverview require-port-for-service — advisory detection for exported services that may benefit from focused consumer ports.
 *
 * Port of the 18.x `require-port-for-service` rule. Same algorithm. The
 * constructor, contract and module-index analysis lives in
 * `./_service-class.ts`, which `require-explicit-service-contract` shares;
 * this file holds the advisory's own exemptions.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-port-for-service.test.ts
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { forEachOwnAstChild } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { existingFactoryContractFix } from "../utils/existing-factory-contract-fix.js";
import { isGeneratedFile, isScriptFile, isStoryFile, isTestFile } from "../utils/paths.js";
import {
  type ClassNode,
  type Collaborator,
  constructorFacts,
  implementsOf,
  invokedInstanceField,
  isExportedServiceClass,
  isPrivateOrProtected,
  publicMethodNames,
  type ServiceFile,
  serviceFile,
} from "./_service-class.js";

const NAME = "require-port-for-service";

/** Third-party transports commonly replaced below a thin client wrapper. */
const HTTP_TRANSPORT_TYPE_RE = /^(?:KyInstance|AxiosInstance|Session)$/;

const TRANSPORT_WRAPPER_NAME_RE = /(?:Client$|^Http[A-Z])/;
/** Error values carry diagnostic data; their callable formatting surface is not a service port. */
const ERROR_VALUE_NAME_RE = /Error$/;
const FLUENT_BUILDER_NAME_RE = /Builder$/;
const FLUENT_RESULT_TYPE_RE = /(?:Builder|Base|Query|Without)(?:\W|$)/;

/** Router-factory call that marks HTTP wiring. */
const ROUTER_FACTORY_NAME = "Router";

/** Namespaced framework HTTP types; unqualified DOM globals do not match. */
const FRAMEWORK_HTTP_TYPES: ReadonlySet<string> = new Set(["Request", "Response", "NextFunction"]);

/** The collaborators and uncovered public surface of an exported service, or null when the advisory does not apply. */
function servicePortGap(
  node: ClassNode,
  className: string,
  file: ServiceFile,
  sourceCode: SourceCode,
): { readonly collaborators: readonly Collaborator[]; readonly methods: readonly string[] } | null {
  const facts = constructorFacts(node, file);
  if (facts === null) return null;
  const invoked = behaviorallyInvokedFields(node.body);
  const collaborators = facts.collaborators.filter((collaborator) =>
    collaborator.fields.some((field) => invoked.has(field)),
  );
  if (collaborators.length === 0 || facts.constructedFields > collaborators.length) return null;
  // HTTP wiring: a router factory is mounted by the bootstrap, not injected.
  if (isFrameworkWiring(node.body)) return null;
  // A lone third-party transport is not a seam a port could protect.
  if (isTransportWrapper(className, collaborators, sourceCode.ast)) return null;
  if (isFluentConstructionObject(node, sourceCode)) return null;
  const methods = publicMethodNames(node.body, file.functionAliases);
  if (methods.length === 0 || hasServicePort(node, methods, file)) return null;
  return { collaborators, methods };
}

/** Framework router wiring is mounted at bootstrap rather than injected into consumers. */
function isFrameworkWiring(body: ESTree.ClassBody): boolean {
  return subtreeHas(body, (node) => {
    if (node.type === "CallExpression") {
      const { callee } = node;
      if (callee.type === "Identifier") return callee.name === ROUTER_FACTORY_NAME;
      return (
        callee.type === "MemberExpression" &&
        !callee.computed &&
        callee.property.type === "Identifier" &&
        callee.property.name === ROUTER_FACTORY_NAME
      );
    }
    // `express.Request` — qualified on purpose, so the DOM `Request`/`Response`
    // globals a Workers `fetch` handler names do not read as express wiring.
    return (
      node.type === "TSTypeReference" &&
      node.typeName.type === "TSQualifiedName" &&
      FRAMEWORK_HTTP_TYPES.has(node.typeName.right.name)
    );
  });
}

/** Walk every descendant node, `parent` links excluded, until `found` returns true. */
function subtreeHas(root: Node, found: (node: Node) => boolean): boolean {
  return found(root) || forEachOwnAstChild(root, (child) => subtreeHas(child, found));
}

/** Instance fields whose retained object is called or receives a direct method call. */
function behaviorallyInvokedFields(body: ESTree.ClassBody): ReadonlySet<string> {
  const invoked = new Set<string>();
  const visit = (current: Node): void => {
    if (
      current.type === "ClassDeclaration" ||
      current.type === "ClassExpression" ||
      current.type === "FunctionDeclaration" ||
      current.type === "FunctionExpression"
    )
      return;
    if (current.type === "CallExpression") {
      const field = invokedInstanceField(current);
      if (field !== null) invoked.add(field);
    }
    forEachOwnAstChild(current, visit);
  };
  for (const member of body.body) {
    if (member.type === "StaticBlock" || member.static) continue;
    if (member.type === "MethodDefinition") {
      if (member.value.body !== null) visit(member.value.body);
      continue;
    }
    if (member.type !== "PropertyDefinition" || member.value === null) continue;
    visit(member.value.type === "ArrowFunctionExpression" ? member.value.body : member.value);
  }
  return invoked;
}

function stem(name: string): string {
  return name.replace(/^I(?=[A-Z])/, "").replace(/Impl$/, "");
}

/** Report whether the class is a thin wrapper over somebody else's HTTP transport. */
function isTransportWrapper(className: string, collaborators: readonly Collaborator[], program: ESTree.Program): boolean {
  const [only] = collaborators;
  if (collaborators.length !== 1 || only === undefined) return false;
  if (!HTTP_TRANSPORT_TYPE_RE.test(only.typeName)) return false;
  if (!TRANSPORT_WRAPPER_NAME_RE.test(className)) return false;
  const target = stem(className);
  return !fileInterfaceNames(program).some((name) => {
    const other = stem(name);
    return target.endsWith(other) || other.endsWith(target);
  });
}

/** Interface declarations at the top level of this module, exported or not. */
function fileInterfaceNames(program: ESTree.Program): string[] {
  const names: string[] = [];
  for (const statement of program.body) {
    const declaration = statement.type === "ExportNamedDeclaration" ? statement.declaration : statement;
    if (declaration?.type === "TSInterfaceDeclaration") names.push(declaration.id.name);
  }
  return names;
}

function isFluentConstructionObject(node: ClassNode, sourceCode: SourceCode): boolean {
  if (node.id === null) return false;
  const className = node.id.name;
  const methods = node.body.body.flatMap((member) =>
    member.type === "MethodDefinition" &&
      member.kind === "method" &&
      !member.static &&
      !isPrivateOrProtected(member) &&
      member.value.body !== null
      ? [member]
      : []);
  if (methods.length === 0) return false;
  return methods.every((member) => {
    const result = member.value.returnType?.typeAnnotation;
    if (result === undefined) return false;
    const returnsOwnType =
      result.type === "TSTypeReference" && result.typeName.type === "Identifier" && result.typeName.name === className;
    return returnsOwnType || (FLUENT_BUILDER_NAME_RE.test(className) && FLUENT_RESULT_TYPE_RE.test(sourceCode.getText(result)));
  });
}

function hasServicePort(node: ClassNode, methods: readonly string[], file: ServiceFile): boolean {
  if (node.superClass !== null) {
    if (node.superClass.type !== "Identifier") return true;
    const localAbstract = localAbstractness(node.superClass.name, file.classes);
    if (localAbstract === undefined || localAbstract) return true;
  }
  if (implementsOf(node).length === 0) return false;
  return implementedSurfaceCovers(node, methods, file);
}

function implementedSurfaceCovers(node: ClassNode, methods: readonly string[], file: ServiceFile): boolean {
  const combined = new Set<string>();
  for (const implementation of implementsOf(node)) {
    if (implementation.expression.type !== "Identifier") return true;
    const name = implementation.expression.name;
    const localAbstract = localAbstractness(name, file.classes);
    if (localAbstract === true) return true;
    const surface = file.interfaces.get(name);
    if (surface === undefined && localAbstract === undefined) return true;
    if (surface === undefined) continue;
    if (surface.has("*")) return true;
    for (const method of surface) combined.add(method);
  }
  return methods.every((method) => combined.has(method));
}

/** Whether a top-level class is abstract, itself or through a local ancestor; undefined when it is not local. */
function localAbstractness(name: string, classes: ReadonlyMap<string, ClassNode>): boolean | undefined {
  let current = classes.get(name);
  if (current === undefined) return undefined;
  const seen = new Set<string>([name]);
  for (;;) {
    if (current.abstract === true) return true;
    const parent: string | null = current.superClass?.type === "Identifier" ? current.superClass.name : null;
    if (parent === null || seen.has(parent)) return false;
    seen.add(parent);
    current = classes.get(parent);
    if (current === undefined) return false;
  }
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Advise when an exported service with injected collaborators has public methods not covered by its declared ports.",
      url: docsUrl(NAME),
    },
    schema: [],
    fixable: "code",
    messages: {
      requireInterface:
        "`{{name}}` stores injected collaborator(s) ({{deps}}), and its declared ports do not cover its public callable surface ({{methods}}). Where consumers need substitution, type them against one or more focused interfaces; do not create one broad interface solely to satisfy this advisory.",
    },
  },
  createOnce(context) {
    return {
      before(): boolean | void {
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isStoryFile(file) || isScriptFile(file)) return false;
        if (isGeneratedFile(file, context.sourceCode.getText())) return false;
      },
      ClassDeclaration(node): void {
        // The port itself must never fire.
        if (node.id === null || node.abstract === true || node.decorators.length > 0) return;
        if (ERROR_VALUE_NAME_RE.test(node.id.name)) return;
        const { sourceCode } = context;
        const file = serviceFile(sourceCode.ast);
        if (!isExportedServiceClass(node, file)) return;
        const gap = servicePortGap(node, node.id.name, file, sourceCode);
        if (gap === null) return;
        const fix = existingFactoryContractFix(sourceCode, node);
        context.report({
          node: node.id,
          messageId: "requireInterface",
          data: {
            name: node.id.name,
            deps: gap.collaborators.map((c) => `${c.name}: ${c.display}`).join(", "),
            methods: gap.methods.join(", "),
          },
          ...(fix !== null && { fix }),
        });
      },
    };
  },
});
