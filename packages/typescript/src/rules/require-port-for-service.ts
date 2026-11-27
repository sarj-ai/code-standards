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
const JAVASCRIPT_FILE_RE = /\.(?:js|jsx|mjs|cjs)$/iu;

type ClassLike = ESTree.Class;
type ProgramStatement = ESTree.Program["body"][number];

interface ClassBinding {
  readonly declaration: ClassLike;
  readonly name: string;
}

function isPublicInstanceMember(member: ESTree.MethodDefinition | ESTree.PropertyDefinition): boolean {
  return !member.static && member.accessibility !== "private" && member.accessibility !== "protected" &&
    member.key.type !== "PrivateIdentifier";
}

function hasPublicInstanceBehavior(node: ClassLike): boolean {
  return node.body.body.some((member) => {
    if (member.type === "MethodDefinition") return member.kind !== "constructor" && isPublicInstanceMember(member);
    return member.type === "PropertyDefinition" && isPublicInstanceMember(member) && (
      member.value?.type === "ArrowFunctionExpression" ||
      member.value?.type === "FunctionExpression" ||
      member.typeAnnotation?.typeAnnotation.type === "TSFunctionType"
    );
  });
}

function classBindings(statement: ProgramStatement): readonly ClassBinding[] {
  const declaration = statement.type === "ExportNamedDeclaration" ? statement.declaration : statement;
  if (declaration?.type === "ClassDeclaration") {
    return declaration.id === null ? [] : [{ declaration, name: declaration.id.name }];
  }
  if (declaration?.type !== "VariableDeclaration") return [];
  return declaration.declarations.flatMap((item) =>
    item.id.type === "Identifier" && item.init?.type === "ClassExpression"
      ? [{ declaration: item.init, name: item.id.name }]
      : [],
  );
}

function exportedClasses(program: ESTree.Program, classes: ReadonlyMap<string, ClassLike>): Map<ClassLike, string> {
  const exported = new Map<ClassLike, string>();
  function collectExportedClass(statement: ProgramStatement): void {
    if (statement.type === "ExportNamedDeclaration") {
      for (const binding of classBindings(statement)) {
        exported.set(binding.declaration, binding.name);
      }
      if (statement.source !== null || statement.exportKind === "type") return;
      collectClassSpecifiers(statement);
      return;
    }
    if (statement.type !== "ExportDefaultDeclaration") return;
    if (statement.declaration.type === "ClassDeclaration" || statement.declaration.type === "ClassExpression") {
      exported.set(statement.declaration, statement.declaration.id?.name ?? "default");
    } else if (statement.declaration.type === "Identifier") {
      const candidate = classes.get(statement.declaration.name);
      if (candidate !== undefined) {
        exported.set(candidate, statement.declaration.name);
      }
    }
  }

  function collectClassSpecifiers(statement: ESTree.ExportNamedDeclaration): void {
    for (const specifier of statement.specifiers) {
      if (specifier.exportKind === "type") continue;
      // TS-ESTree reads `local.name`; a string-literal local only occurs with a `source`.
      const candidate = classes.get((specifier.local as { name: string }).name);
      if (candidate === undefined) continue;
      const exportedName = specifier.exported.type === "Identifier" ? specifier.exported.name : specifier.exported.value;
      exported.set(candidate, exportedName);
    }
  }

  for (const statement of program.body) {
    collectExportedClass(statement);
  }

  return exported;
}

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
        "Require exported-class contracts and advise when an exported injected service's public methods are not covered by its declared ports.",
      url: docsUrl(NAME),
    },
    schema: [],
    fixable: "code",
    messages: {
      requireContract:
        "Exported class `{{name}}` has public behavior but no declared interface or base contract; add a focused contract and implement it.",
      requireInterface:
        "`{{name}}` stores injected collaborator(s) ({{deps}}), and its declared ports do not cover its public callable surface ({{methods}}). Where consumers need substitution, type them against one or more focused interfaces; do not create one broad interface solely to satisfy this advisory.",
    },
  },
  createOnce(context) {
    let portApplies = false;
    let contractApplies = false;
    return {
      before(): boolean | void {
        const file = { filename: context.filename, cwd: context.cwd };
        portApplies = !(isTestFile(file) || isStoryFile(file) || isScriptFile(file) ||
          isGeneratedFile(file, context.sourceCode.getText()));
        contractApplies = !(JAVASCRIPT_FILE_RE.test(file.filename) || isTestFile(file) || isStoryFile(file) ||
          isGeneratedFile(file, context.sourceCode.text));
        if (!portApplies && !contractApplies) return false;
      },
      ClassDeclaration(node): void {
        if (!portApplies) return;
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
      "Program:exit"(program): void {
        if (!contractApplies) return;
        const classes = new Map<string, ClassLike>();
        const abstractBases = new Set<string>();
        for (const statement of program.body) {
          for (const binding of classBindings(statement)) {
            classes.set(binding.name, binding.declaration);
            if (binding.declaration.abstract) abstractBases.add(binding.name);
          }
        }

        for (const [declaration, exportedName] of exportedClasses(program, classes)) {
          const extendsLocalAbstractBase =
            declaration.superClass?.type === "Identifier" && abstractBases.has(declaration.superClass.name);
          if (
            declaration.abstract ||
            (declaration.implements?.length ?? 0) > 0 ||
            extendsLocalAbstractBase ||
            !hasPublicInstanceBehavior(declaration)
          )
            continue;
          const fix = existingFactoryContractFix(context.sourceCode, declaration);
          context.report({
            node: declaration.id ?? declaration,
            messageId: "requireContract",
            data: { name: exportedName },
            ...(fix !== null && { fix }),
          });
        }
      },
    };
  },
});
