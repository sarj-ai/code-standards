/**
 * @fileoverview require-interface-for-injected-service — an exported class with injected collaborators and no port above it can only be tested by mocking the class.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/require-interface-for-injected-service.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/require-interface-for-injected-service.md
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isScriptFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "requireInterface";
type Options = readonly [];

const CONFIGISH_TYPE_RE =
  /(?:Options|Opts|Config|Configuration|Settings|Params|Props|Args|Env|Environment|Callbacks|Flags)$/;

/**
 * Parameter names that carry the same signal from the other side, plus the two
 * ambient-capability names the brief called out as weak evidence of a seam: a
 * class whose ONLY dependency is a logger or a clock is not the substitutability
 * problem this rule is about.
 */
const CONFIGISH_NAME_RE =
  /^(?:options|opts|config|configuration|settings|params|props|args|env|environment|callbacks|flags|logger|log|clock)$/i;

/**
 * Third-party HTTP transports. A class whose ONLY stored collaborator is one of
 * these is a thin wrapper over somebody else's wire client: the Python side of
 * this standard excludes `*Client` for exactly this reason — an ABC over a class
 * whose collaborator is somebody else's HTTP transport substitutes nothing, and
 * a consumer's test fakes the transport (`respx`, `nock`, `msw`), not the wrapper.
 */
const HTTP_TRANSPORT_TYPE_RE = /^(?:KyInstance|AxiosInstance|Session)$/;

/** Only the `*Client` naming carries the guard; see the transport-wrapper note in the header. */
const TRANSPORT_WRAPPER_NAME_RE = /Client$/;

/** `express.Router()` / `Router()` — the router-factory call that marks HTTP wiring. */
const ROUTER_FACTORY_NAME = "Router";

/** Namespaced framework HTTP types (`express.Request`), never the DOM globals of the same name. */
const FRAMEWORK_HTTP_TYPES: ReadonlySet<string> = new Set(["Request", "Response", "NextFunction"]);

interface Collaborator {
  readonly name: string;
  /** Rightmost segment of the type name — what the config-ish guards test. */
  readonly typeName: string;
  /** Full source spelling, including any namespace qualifier, for the message. */
  readonly display: string;
}

/** The class's own declaration is what `export`s it; anonymous defaults have no name to report. */
const isExportedClass = (node: TSESTree.ClassDeclaration): boolean =>
  node.parent.type === AST_NODE_TYPES.ExportNamedDeclaration ||
  node.parent.type === AST_NODE_TYPES.ExportDefaultDeclaration;

/** `catalog.Client` -> `"catalog.Client"`; a nested qualifier is flattened the same way. */
const qualifiedName = (name: TSESTree.EntityName): string =>
  name.type === AST_NODE_TYPES.Identifier
    ? name.name
    : name.type === AST_NODE_TYPES.TSQualifiedName
      ? `${qualifiedName(name.left)}.${name.right.name}`
      : "";

const typeReferenceName = (annotated: TSESTree.Parameter): Collaborator | null => {
  let target: TSESTree.Node = annotated;
  if (target.type === AST_NODE_TYPES.TSParameterProperty) target = target.parameter;
  if (target.type === AST_NODE_TYPES.AssignmentPattern) target = target.left;
  if (target.type !== AST_NODE_TYPES.Identifier) return null;

  const annotation = target.typeAnnotation?.typeAnnotation;
  // A bare type reference is the only shape that names a nominal collaborator.
  // An inline `{ a: string }`, a union, an array, or a function type is data or
  // a callback, never something a consumer would want to swap wholesale.
  if (annotation === undefined || annotation.type !== AST_NODE_TYPES.TSTypeReference) {
    return null;
  }
  const { typeName } = annotation;
  const rightmost =
    typeName.type === AST_NODE_TYPES.Identifier
      ? typeName.name
      : typeName.type === AST_NODE_TYPES.TSQualifiedName
        ? typeName.right.name
        : null;
  if (rightmost === null) return null;
  return { name: target.name, typeName: rightmost, display: qualifiedName(typeName) };
};

interface ConstructorFacts {
  /** Parameters assigned to an instance field, either as a parameter property or in the body. */
  readonly collaborators: readonly Collaborator[];
  /** How many instance fields the constructor fills with a `new` expression. */
  readonly constructedFields: number;
}

const readConstructor = (ctor: TSESTree.MethodDefinition): ConstructorFacts => {
  const body = ctor.value.body;
  const storedFrom = new Set<string>();
  let constructedFields = 0;

  if (body !== null && body !== undefined) {
    for (const statement of body.body) {
      if (statement.type !== AST_NODE_TYPES.ExpressionStatement) continue;
      const expression = statement.expression;
      if (
        expression.type !== AST_NODE_TYPES.AssignmentExpression ||
        expression.operator !== "=" ||
        expression.left.type !== AST_NODE_TYPES.MemberExpression ||
        expression.left.object.type !== AST_NODE_TYPES.ThisExpression
      ) {
        continue;
      }
      const source = expression.right;
      if (source.type === AST_NODE_TYPES.NewExpression) {
        constructedFields += 1;
      } else if (source.type === AST_NODE_TYPES.Identifier) {
        // `this.svc = svc`
        storedFrom.add(source.name);
      } else if (
        source.type === AST_NODE_TYPES.MemberExpression &&
        source.object.type === AST_NODE_TYPES.Identifier
      ) {
        // `this.slack = deps.slack` — a dependency bag spread onto fields.
        storedFrom.add(source.object.name);
      }
    }
  }

  const collaborators: Collaborator[] = [];
  for (const parameter of ctor.value.params) {
    const reference = typeReferenceName(parameter);
    if (reference === null) continue;
    const stored =
      parameter.type === AST_NODE_TYPES.TSParameterProperty || storedFrom.has(reference.name);
    if (!stored) continue;
    if (CONFIGISH_TYPE_RE.test(reference.typeName)) continue;
    if (CONFIGISH_NAME_RE.test(reference.name)) continue;
    collaborators.push(reference);
  }

  return { collaborators, constructedFields };
};

/** Walk every descendant node, `parent` links excluded, until `found` returns true. */
const subtreeHas = (root: TSESTree.Node, found: (node: TSESTree.Node) => boolean): boolean => {
  let hit = false;
  const visit = (current: TSESTree.Node): void => {
    if (hit) return;
    if (found(current)) {
      hit = true;
      return;
    }
    for (const key of Object.keys(current) as (keyof TSESTree.Node)[]) {
      if (key === "parent") continue;
      const value = current[key];
      for (const child of (Array.isArray(value) ? value : [value]) as unknown[]) {
        if (
          child !== null &&
          typeof child === "object" &&
          typeof (child as { type?: unknown }).type === "string"
        ) {
          visit(child as TSESTree.Node);
        }
      }
    }
  };
  visit(root);
  return hit;
};

/**
 * Report whether the class body is HTTP framework wiring: it manufactures a
 * router (`express.Router()`), or it handles the framework's own namespaced
 * request/response objects. Such a class is mounted by the server's bootstrap,
 * never injected into anything, so there is no consumer to give a port to.
 */
const isFrameworkWiring = (body: TSESTree.ClassBody): boolean =>
  subtreeHas(body, (node) => {
    if (node.type === AST_NODE_TYPES.CallExpression) {
      const { callee } = node;
      if (callee.type === AST_NODE_TYPES.Identifier) return callee.name === ROUTER_FACTORY_NAME;
      return (
        callee.type === AST_NODE_TYPES.MemberExpression &&
        !callee.computed &&
        callee.property.type === AST_NODE_TYPES.Identifier &&
        callee.property.name === ROUTER_FACTORY_NAME
      );
    }
    // `express.Request` — qualified on purpose, so the DOM `Request`/`Response`
    // globals a Workers `fetch` handler names do not read as express wiring.
    return (
      node.type === AST_NODE_TYPES.TSTypeReference &&
      node.typeName.type === AST_NODE_TYPES.TSQualifiedName &&
      FRAMEWORK_HTTP_TYPES.has(node.typeName.right.name)
    );
  });

const stem = (name: string): string => name.replace(/^I(?=[A-Z])/, "").replace(/Impl$/, "");

/** Interface declarations at the top level of this module, exported or not. */
const fileInterfaceNames = (program: TSESTree.Program): string[] => {
  const names: string[] = [];
  for (const statement of program.body) {
    const declaration =
      statement.type === AST_NODE_TYPES.ExportNamedDeclaration ? statement.declaration : statement;
    if (declaration?.type === AST_NODE_TYPES.TSInterfaceDeclaration) names.push(declaration.id.name);
  }
  return names;
};

/** Report whether the class is a thin wrapper over somebody else's HTTP transport. */
const isTransportWrapper = (
  className: string,
  collaborators: readonly Collaborator[],
  program: TSESTree.Program,
): boolean => {
  const [only] = collaborators;
  if (collaborators.length !== 1 || only === undefined) return false;
  if (!HTTP_TRANSPORT_TYPE_RE.test(only.typeName)) return false;
  if (!TRANSPORT_WRAPPER_NAME_RE.test(className)) return false;
  const target = stem(className);
  return !fileInterfaceNames(program).some((name) => {
    const other = stem(name);
    return target.endsWith(other) || other.endsWith(target);
  });
};

/**
 * Public instance methods only. `kind === "method"` excludes getters and setters
 * on purpose: a class that exposes only accessors is a value object, and the
 * constructor is not a seam worth porting.
 */
const publicMethodNames = (body: TSESTree.ClassBody): string[] => {
  const names: string[] = [];
  for (const member of body.body) {
    if (member.type !== AST_NODE_TYPES.MethodDefinition) continue;
    if (member.kind !== "method" || member.static) continue;
    if (member.accessibility === "private" || member.accessibility === "protected") continue;
    if (member.key.type === AST_NODE_TYPES.PrivateIdentifier) continue;
    if (member.key.type === AST_NODE_TYPES.Identifier) names.push(member.key.name);
    else names.push("…");
  }
  return names;
};

export default createRule<Options, MessageIds>({
  name: "require-interface-for-injected-service",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "An exported service class with constructor-injected collaborators must implement an interface, so consumers depend on a port they can substitute instead of mocking the class.",
    },
    schema: [],
    messages: {
      requireInterface:
        "`{{name}}` stores injected collaborator(s) ({{deps}}) but implements no interface, so every consumer depends on this concrete class and can only be tested by mocking it. Declare an interface with its public method signature(s) ({{methods}}) and `class {{name}} implements <Interface>`.",
    },
  },
  defaultOptions: [],
  create(context) {
    const { filename } = context;
    if (isTestFile(filename) || isStoryFile(filename) || isScriptFile(filename)) return {};
    if (isGeneratedFile(filename, context.sourceCode.getText())) return {};

    return {
      ClassDeclaration(node: TSESTree.ClassDeclaration): void {
        if (node.id === null) return;
        if (!isExportedClass(node)) return;
        // The port itself must never fire, and a class that extends anything —
        // an abstract base, a framework class, `Error` — already has one.
        if (node.abstract === true) return;
        if (node.superClass !== null) return;
        if (node.implements.length > 0) return;
        // A framework that instantiates by class token (NestJS `@Injectable()`)
        // makes the class its own contract.
        if (node.decorators.length > 0) return;

        const ctor = node.body.body.find(
          (member): member is TSESTree.MethodDefinition =>
            member.type === AST_NODE_TYPES.MethodDefinition && member.kind === "constructor",
        );
        if (ctor === undefined) return;

        const { collaborators, constructedFields } = readConstructor(ctor);
        if (collaborators.length === 0) return;
        // A composition root BUILDS more than it RECEIVES — that is where
        // concrete types are supposed to be named, and a port above it protects
        // nobody. Constructing one internal helper while receiving a real
        // collaborator is an ordinary service, not a wiring class, so the test
        // is a ratio rather than the mere presence of a `new`.
        if (constructedFields > collaborators.length) return;
        // HTTP wiring: a router factory is mounted by the bootstrap, not injected.
        if (isFrameworkWiring(node.body)) return;
        // A lone third-party transport is not a seam a port could protect.
        if (isTransportWrapper(node.id.name, collaborators, context.sourceCode.ast)) return;

        const methods = publicMethodNames(node.body);
        if (methods.length === 0) return;

        context.report({
          node: node.id,
          messageId: "requireInterface",
          data: {
            name: node.id.name,
            deps: collaborators.map((c) => `${c.name}: ${c.display}`).join(", "),
            methods: methods.join(", "),
          },
        });
      },
    };
  },
});
