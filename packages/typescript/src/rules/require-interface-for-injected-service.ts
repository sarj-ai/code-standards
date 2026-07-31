/**
 * @fileoverview An exported concrete class that takes injected collaborators and
 * has no interface above it is not substitutable. Every consumer must import and
 * depend on the concrete class, so the only way to test a consumer is to mock the
 * class — the exact failure the Python side of this standard attacks with
 * `prefer-real-store-in-tests` / `prefer-library-fake`. An interface (a port),
 * even a two-method one, lets a consumer's test pass a real alternative
 * implementation instead of a mock.
 *
 * The rule fires on an EXPORTED, non-abstract class declaration that
 *   (a) has no `implements` clause and does not `extend` anything,
 *   (b) stores >=1 constructor parameter whose type is a bare type reference
 *       (not a primitive, literal, inline object type, union, or function type)
 *       and is not a config/options/callback bag, and
 *   (c) declares >=1 public instance method (a class with only a constructor,
 *       fields, or getters is a value object / DTO, not a service).
 *
 * CORPUS SWEEP (2026-07, re-measured over 18 first-party repos, written below
 * as `repo A` .. `repo R`; one label per repo, stable within this docstring
 * only). 286 exported class declarations
 * in non-test / non-generated files; 216 already carry an `implements` clause,
 * extend a base class, or are themselves abstract. 76% of the population is
 * ALREADY compliant, which is what makes this a lint rule rather than a design
 * proposal. 30 fire after the two guards below (35 before them).
 *
 * The earlier sweep read 82% of 229 because it covered only the first twelve
 * repos; the six added here are where both false-positive families lived, and
 * both were invisible to it. Adoption varies far more than the aggregate
 * suggests: repo C (62/62), repo A (32/32, the flagship product), repo Q
 * (12/12), repo K and repo D are at 100%; repo N 86%, repo J 83%, repo M 80%,
 * repo H 71%, repo I 56%, repo L / repo O / repo P 50%, repo B 46% (32 of
 * 69), repo R 29%, repo F 25%. The rule is a ratchet for the low half, not a
 * description of the high half.
 *
 * The convention being enforced is `interface`, not `abstract class`, and the
 * corpus is unambiguous about it: 175 `implements` clauses against exactly ONE
 * hand-written abstract class in 7,912 files (a lone content-generation helper
 * in repo K). (A raw grep finds ~220 more `abstract class` tokens in repo D
 * and repo E; every one is an ambient Cloudflare declaration inside
 * `worker-configuration.d.ts`, excluded here as generated.) Three impl-naming
 * conventions coexist — `HttpMessageService implements MessageService`
 * (repo A), `ApiClient implements IApiClient` (repo B, repo C, repo H), and
 * `ReportParserImpl` / `ReportParser` (repo J) — so the message names no
 * interface for you.
 *
 * FIRING DISTRIBUTION, and why the hits are outliers rather than a house style
 * (before -> after the two guards below):
 *   repo B             69 exported classes, 20 -> 20 hits
 *   repo H             17 exported classes,  3 ->  3 hits
 *   repo J             24 exported classes,  3 ->  2 hits
 *   repo M             20 exported classes,  3 ->  2 hits
 *   repo I              9 exported classes,  2 ->  2 hits
 *   repo L              2 exported classes,  1 ->  1 hit
 *   repo N             14 exported classes,  1 ->  0 hits
 *   repo O              2 exported classes,  1 ->  0 hits
 *   repo P              2 exported classes,  1 ->  0 hits
 *   repo A / repo C / repo Q / repo K / repo D / repo E / repo G /
 *   repo F / repo R: 0 hits
 *
 * THE FALSE-POSITIVE RATE WAS 14%, NOT 0-3.4%. The earlier claim rested on a
 * sweep that never reached repo M, repo N, repo O or repo P, and both
 * false-positive families live only there (plus one instance each already in
 * repo J and, for the transport family, nowhere the old sweep looked). Of 35
 * raw hits, 5 were false: three copies of one express router template and two
 * copies of one `ky` wrapper. The two guards below remove exactly those 5 and
 * cost 0 true positives — verified hit-by-hit across all 18 repos, 35 -> 30.
 *
 * The origin case, raised in review on repo B, is a task-runner service:
 * `class RecordNormalizerService` holds one god-object collaborator
 * (`svc: ServiceRegistry`), exposes one `run` method, and implements nothing.
 * Its own test has to build the collaborator with
 * `{ ... } as unknown as ServiceRegistry` — the cast-mock this rule is trying
 * to make unnecessary. Its sibling in the same directory tree is the same
 * shape done right: `class TaskTrackerService implements ITaskTrackerService`.
 *
 * Two further confirmations that the rule finds real drift rather than taste:
 *
 *   - The composition root of repo H types 8 of its 11 fields as `I*`
 *     interfaces and 3 as concrete classes. The rule fires on exactly those
 *     three — the repo's own composition root already documents which classes
 *     are missing a port.
 *   - One site in repo J declares `interface ReportParser` three lines above
 *     `class ReportParserImpl`, which never says `implements`. The port exists
 *     and the impl is silently free to drift from it.
 *
 * NAMED FALSE POSITIVES that shaped the guards (each measured, not imagined):
 *   - One site in repo B: `JsonHttpClient` takes
 *     `options: JsonHttpClientOptions`, whose three fields are all
 *     primitives. A config bag is not a collaborator seam -> config-ish type
 *     suffixes and parameter names are excluded. Cost: 1 of 32 raw hits.
 *   - One site in repo F: a realtime-session manager takes
 *     `callbacks: RealtimeSessionCallbacks`, an OUTBOUND observer bag, not an
 *     inbound dependency; there is nothing to substitute. -> `Callbacks`
 *     suffix and `callbacks` parameter name excluded. Cost: 1 of 32.
 *   - One site in repo H: a `ServiceFactory` receives a `db` and `new`s eleven
 *     services onto its own fields. That is a composition
 *     root: it is where concrete types are supposed to be named, and a port
 *     above it protects nobody. -> a constructor that BUILDS more fields than it
 *     RECEIVES collaborators is exempt. Cost: 1 of 32.
 *
 *     The first cut of that guard exempted any constructor containing a `new`
 *     at all, and the corpus immediately punished it: two sibling message
 *     handlers in repo B each take `svc: ServiceRegistry` AND build one
 *     internal `TaskProcessor`, and both silently stopped firing. Constructing
 *     a helper is not being a wiring class; the ratio is what separates the
 *     two.
 *
 *   - FRAMEWORK ROUTERS. Three sites — one each in repo J, repo M and repo N —
 *     are three copies of one job-runner template:
 *     `MainRouter(taskStore, taskExecutor)` whose `init()`
 *     returns an `express.Router()`. The server's bootstrap mounts it; nothing
 *     injects it, so there is no consumer to hand a port to. -> a class whose
 *     body manufactures a router (`express.Router()` / `Router()`) or handles
 *     the framework's own namespaced request/response types
 *     (`express.Request`) is exempt. The DOM `Request`/`Response` globals a
 *     Workers `fetch` handler names are unqualified and deliberately do not
 *     match. Cost: 3 of 35 raw hits, all three false positives, 0 true
 *     positives lost.
 *
 *   - TRANSPORT WRAPPERS. Two sites, one in repo O and one in repo P, are two
 *     copies of `LedgerHttpClient(private readonly client: KyInstance)`. These
 *     are
 *     false by this standard's own stated reasoning: the Python twin excludes
 *     `*Client` precisely because an ABC over a class whose collaborator is
 *     somebody else's HTTP transport substitutes nothing — a consumer's test
 *     fakes the transport (`respx`, `nock`, `msw`), not the wrapper. -> a class
 *     is exempt when its ONLY collaborator is a third-party transport
 *     (`KyInstance`, `AxiosInstance`, `Session`), it is named `*Client`, AND no
 *     interface in the same file shares its stem. All three arms are load
 *     bearing. The `*Client` arm is what keeps the corpus's two
 *     `AxiosInstance`-only domain wrappers — repo I's `HttpMessageService` and
 *     repo J's `ReportParserImpl` — firing, because both
 *     wrap the transport in a domain operation their consumers can substitute.
 *     The same-file-interface arm has zero measured cost and is kept as a
 *     precaution: a `FooClient` beside an `IFooClient` it never `implements` is
 *     exactly the drift this rule exists for, and the corpus cannot prove that
 *     shape's absence elsewhere. Cost: 2 of 35 raw hits, both false positives,
 *     0 true positives lost.
 *
 * GUARDS WITH ZERO MEASURED COST, kept as precautions because the corpus is
 * first-party and cannot prove their absence elsewhere: decorated classes
 * (NestJS-style `@Injectable()` providers are instantiated by class token, so
 * the class IS the contract — 0 decorated classes in the corpus), and a
 * logger/clock-only dependency (weak evidence of a real seam — 0 such classes).
 *
 * GUARDS THAT NEED NO CODE, because `extends` already covers them: React class
 * components (`extends React.Component`), Lexical/editor nodes
 * (`extends TextNode`, `extends DecoratorNode`), error classes
 * (`extends Error`), Durable Objects, Workflows and custom elements. Every one
 * of the 4 exported classes in `.tsx` files across the corpus is such a case
 * (two editor-node classes in repo A, plus one error-boundary component that
 * appears once in repo D and once in repo E). Extending a
 * framework base class is itself a form of port.
 *
 * THE ONE-METHOD THRESHOLD is the load-bearing difference from the Python
 * sibling `require_port_for_service` (SARJ063), which demands >=2 public methods
 * and a `*Service`/`*Store`/`*Client` name. Measured here: 22 of the 29 hits
 * expose exactly ONE public method (the distribution is 22x1, 1x2, 1x5, 1x6,
 * 1x8, 2x9, 1x12), so a >=2 threshold would discard 76% of them — including the
 * origin case, whose sole method is `run`. A service-family NAME filter would
 * cost as much: `TaskProcessor`, `InteractiveActionHandler`,
 * `ReportParserImpl`, `MainRouter` and every `*Handler` in repo B carry
 * no such suffix. TypeScript's `export` keyword plus a stored collaborator is
 * the proxy for "someone depends on this" that Python has to approximate with
 * naming, so this rule leans on those two instead.
 *
 * DELIBERATE FALSE NEGATIVES, each measured at 0 occurrences in the corpus and
 * therefore not worth the AST cost: a destructuring constructor
 * (`constructor({ a, b }: Deps)`) and a class whose public methods are all arrow
 * properties (`handle = async () => {}`) rather than method definitions.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isGeneratedFile, isScriptFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "requireInterface";
type Options = readonly [];

/**
 * Type-name suffixes that mark a constructor parameter as configuration rather
 * than a collaborator. Deliberately short: every entry here is a silent false
 * negative for anyone who names a real dependency that way, so it lists only
 * what the corpus proved (`*Options`, `*Callbacks`) plus the immediate synonyms.
 * `Handler` / `Listener` / `Store` / `Client` are pointedly ABSENT — those are
 * exactly the collaborators the rule exists to notice.
 */
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

/** `IFooClient` / `FooClientImpl` both reduce to `FooClient`, the three impl conventions the corpus uses. */
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

/**
 * Report whether the class is a thin wrapper over somebody else's HTTP transport.
 *
 * Three conditions, all necessary. The class receives exactly ONE collaborator
 * and that collaborator is a third-party transport, so there is no domain seam
 * hiding behind it. It is named `*Client`, which is the arm that keeps the
 * corpus's `HttpMessageService` and `ReportParserImpl` — both `AxiosInstance`-only
 * — firing, because those wrap a transport in a *domain* operation and their
 * consumers do have something to substitute. And no interface in the same file
 * shares its stem, because an in-file port the class silently fails to
 * `implements` is the drift this rule exists to catch.
 */
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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
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
