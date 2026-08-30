/**
 * @fileoverview require-port-for-service — advisory detection for exported services that may benefit from focused consumer ports.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-port-for-service.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isScriptFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "requireInterface";
type Options = readonly [];

export const REQUIRE_PORT_FOR_SERVICE_DOCUMENTATION = {
  summary: "Advise when an exported service with injected collaborators has public methods not covered by its declared ports.",
  rationale: "A declared port keeps consumers coupled to the service capability instead of its concrete implementation.",
  remediation: "Declare and implement an interface covering the service's public methods.",
  category: "architecture",
  aliases: ["require-interface-for-injected-service"],
  examples: [
    { id: "declared-service-port", title: "Implement the service port", outcome: "no-match", files: [{ path: "src/service.ts", source: "interface Handler { handle(): void }\nexport class RequestHandler implements Handler { constructor(private readonly store: TaskStore) {} handle(): void { this.store.handle(); } }" }], focusPath: "src/service.ts", expectedCount: 0, public: true },
    { id: "concrete-injected-service", title: "Do not expose only the concrete service", outcome: "match", files: [{ path: "src/service.ts", source: "export class RequestHandler { constructor(private readonly store: TaskStore) {} handle(): void { this.store.handle(); } }" }], focusPath: "src/service.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const CONFIGISH_TYPE_RE =
  /(?:Options|Opts|Config|Configuration|Settings|Params|Props|Args|Env|Environment|Callbacks|Flags)$/;

/** Configuration names plus logger and clock, which alone do not establish a service seam. */
const CONFIGISH_NAME_RE =
  /^(?:options|opts|config|configuration|settings|params|props|args|env|environment|callbacks|flags|logger|log|clock)$/i;

/** Third-party transports commonly replaced below a thin client wrapper. */
const HTTP_TRANSPORT_TYPE_RE = /^(?:KyInstance|AxiosInstance|Session)$/;

/** Containers and mapped helpers describe data rather than substitutable implementations. */
const BUILTIN_CONTAINER_TYPE_RE =
  /^(?:Record|Map|WeakMap|Set|WeakSet|Array|ReadonlyArray|ReadonlyMap|ReadonlySet|Promise|Partial|Required|Readonly|Pick|Omit|Exclude|Extract|NonNullable|Awaited|Parameters|ReturnType|InstanceType)$/;

/** Nominal leaf values are constructor data, not collaborators with swappable behavior. */
const VALUE_TYPE_RE = /^(?:ArrayBuffer|Blob|Buffer|Date|NodePath|RegExp|URL|URLSearchParams)$/;

const TRANSPORT_WRAPPER_NAME_RE = /(?:Client$|^Http[A-Z])/;
/** Error values carry diagnostic data; their callable formatting surface is not a service port. */
const ERROR_VALUE_NAME_RE = /Error$/;
const FLUENT_BUILDER_NAME_RE = /Builder$/;
const FLUENT_RESULT_TYPE_RE = /(?:Builder|Base|Query|Without)(?:\W|$)/;

/** Router-factory call that marks HTTP wiring. */
const ROUTER_FACTORY_NAME = "Router";

/** Namespaced framework HTTP types; unqualified DOM globals do not match. */
const FRAMEWORK_HTTP_TYPES: ReadonlySet<string> = new Set(["Request", "Response", "NextFunction"]);
const STORAGE_ASSIGNMENT_OPERATORS: ReadonlySet<string> = new Set(["=", "&&=", "??=", "||="]);

interface Collaborator {
  readonly name: string;
  /** Rightmost segment of the type name — what the config-ish guards test. */
  readonly typeName: string;
  /** Full source spelling, including any namespace qualifier, for the message. */
  readonly display: string;
  /** Instance fields that retain this constructor parameter. */
  readonly fields: readonly string[];
}

const staticMemberName = (member: TSESTree.MemberExpression): string | null => {
  if (member.property.type === AST_NODE_TYPES.PrivateIdentifier) return `#${member.property.name}`;
  if (!member.computed && member.property.type === AST_NODE_TYPES.Identifier) return member.property.name;
  return member.computed &&
    member.property.type === AST_NODE_TYPES.Literal &&
    typeof member.property.value === "string"
    ? member.property.value
    : null;
};

const detachedValueExports = (program: TSESTree.Program): ReadonlySet<string> => {
  const names = new Set<string>();
  for (const statement of program.body) {
    if (
      statement.type === AST_NODE_TYPES.ExportNamedDeclaration &&
      statement.declaration === null &&
      statement.source === null &&
      statement.exportKind !== "type"
    ) {
      for (const specifier of statement.specifiers) {
        if (specifier.exportKind !== "type") names.add(specifier.local.name);
      }
    } else if (
      statement.type === AST_NODE_TYPES.ExportDefaultDeclaration &&
      statement.declaration.type === AST_NODE_TYPES.Identifier
    ) {
      names.add(statement.declaration.name);
    } else if (
      statement.type === AST_NODE_TYPES.TSExportAssignment &&
      statement.expression.type === AST_NODE_TYPES.Identifier
    ) {
      names.add(statement.expression.name);
    }
  }
  return names;
};

const isExportedClass = (node: TSESTree.ClassDeclaration, detached: ReadonlySet<string>): boolean =>
  node.parent.type === AST_NODE_TYPES.ExportNamedDeclaration ||
  node.parent.type === AST_NODE_TYPES.ExportDefaultDeclaration ||
  (node.id !== null && detached.has(node.id.name));

/** The rightmost segment plus the full spelling of a bare type reference, or null for anything else. */
const readTypeReference = (
  annotation: TSESTree.TypeNode | undefined,
): { readonly typeName: string; readonly display: string } | null => {
  if (annotation?.type === AST_NODE_TYPES.TSUnionType) {
    const members = annotation.types.filter((member) =>
      member.type !== AST_NODE_TYPES.TSUndefinedKeyword &&
      member.type !== AST_NODE_TYPES.TSNullKeyword,
    );
    annotation = members.length === 1 ? members[0] : undefined;
  }
  if (annotation === undefined || annotation.type !== AST_NODE_TYPES.TSTypeReference) return null;
  const { typeName } = annotation;
  const rightmost =
    typeName.type === AST_NODE_TYPES.Identifier
      ? typeName.name
      : typeName.type === AST_NODE_TYPES.TSQualifiedName
        ? typeName.right.name
        : null;
  if (rightmost === null) return null;
  return { typeName: rightmost, display: qualifiedName(typeName) };
};

/** `catalog.Client` -> `"catalog.Client"`; a nested qualifier is flattened the same way. */
const qualifiedName = (name: TSESTree.EntityName): string =>
  name.type === AST_NODE_TYPES.Identifier
    ? name.name
    : name.type === AST_NODE_TYPES.TSQualifiedName
      ? `${qualifiedName(name.left)}.${name.right.name}`
      : "";

/** Property signatures of a `{ a: A; b: B }` body, keyed by property name. */
const propertySignatureTypes = (
  members: readonly TSESTree.TypeElement[],
): Map<string, TypeReference> => {
  const types = new Map<string, TypeReference>();
  for (const member of members) {
    if (member.type !== AST_NODE_TYPES.TSPropertySignature) continue;
    if (member.computed || member.key.type !== AST_NODE_TYPES.Identifier) continue;
    const reference = readTypeReference(member.typeAnnotation?.typeAnnotation);
    if (reference === null) continue;
    types.set(member.key.name, reference);
  }
  return types;
};

type TypeReference = { readonly typeName: string; readonly display: string };
type MemberTypes = ReadonlyMap<string, TypeReference>;

const fileTypeIndex = (program: TSESTree.Program): FileTypeIndex => {
  const objects = new Map<string, MemberTypes>();
  const functionAliases = new Set<string>();
  for (const statement of program.body) {
    const declaration =
      statement.type === AST_NODE_TYPES.ExportNamedDeclaration ? statement.declaration : statement;
    if (declaration?.type === AST_NODE_TYPES.TSInterfaceDeclaration) {
      objects.set(declaration.id.name, propertySignatureTypes(declaration.body.body));
      continue;
    }
    if (declaration?.type !== AST_NODE_TYPES.TSTypeAliasDeclaration) continue;
    const aliased = declaration.typeAnnotation;
    if (
      aliased.type === AST_NODE_TYPES.TSFunctionType ||
      aliased.type === AST_NODE_TYPES.TSConstructorType
    ) {
      functionAliases.add(declaration.id.name);
      continue;
    }
    // `type Deps = { … }` and `type Deps = Base & { … }` both resolve; the
    // intersection form is how a bag is usually extended.
    const literals =
      aliased.type === AST_NODE_TYPES.TSTypeLiteral
        ? [aliased]
        : aliased.type === AST_NODE_TYPES.TSIntersectionType
          ? aliased.types.filter((part) => part.type === AST_NODE_TYPES.TSTypeLiteral)
          : [];
    if (literals.length === 0) continue;
    const merged = new Map<string, TypeReference>();
    for (const literal of literals) {
      for (const [name, reference] of propertySignatureTypes(literal.members)) {
        merged.set(name, reference);
      }
    }
    objects.set(declaration.id.name, merged);
  }
  return { objects, functionAliases };
};

/** Locally declared object shapes and function aliases used to resolve constructor bags. */
interface FileTypeIndex {
  /** `interface Deps { … }` / `type Deps = { … }`, by name. */
  readonly objects: ReadonlyMap<string, MemberTypes>;
  /** `type Replayer = (e: Event) => void` — a callback with a nominal name. */
  readonly functionAliases: ReadonlySet<string>;
}

/** Names bound by `class Foo<T>` / `constructor<T>()` — placeholders, not implementations. */
const typeParameterNames = (
  ...declarations: readonly (TSESTree.TSTypeParameterDeclaration | undefined)[]
): ReadonlySet<string> => {
  const names = new Set<string>();
  for (const declaration of declarations) {
    for (const parameter of declaration?.params ?? []) names.add(parameter.name.name);
  }
  return names;
};

const readConstructor = (
  ctor: TSESTree.MethodDefinition,
  declared: () => FileTypeIndex,
  typeParameters: ReadonlySet<string>,
): ConstructorFacts => {
  const body = ctor.value.body;
  const storedFieldsFrom = new Map<string, Set<string>>();
  const storedMemberFieldsFrom = new Map<string, Map<string, Set<string>>>();
  let constructedFields = 0;

  if (body !== null && body !== undefined) {
    const pending: TSESTree.Node[] = [...body.body];
    while (pending.length > 0) {
      const current = pending.pop();
      if (current === undefined) break;
      if (
        current.type === AST_NODE_TYPES.ArrowFunctionExpression ||
        current.type === AST_NODE_TYPES.FunctionExpression ||
        current.type === AST_NODE_TYPES.FunctionDeclaration ||
        current.type === AST_NODE_TYPES.ClassExpression ||
        current.type === AST_NODE_TYPES.ClassDeclaration
      ) continue;
      const expression = current.type === AST_NODE_TYPES.ExpressionStatement ? current.expression : null;
      const storedField =
        expression?.type === AST_NODE_TYPES.AssignmentExpression &&
        expression.left.type === AST_NODE_TYPES.MemberExpression &&
        expression.left.object.type === AST_NODE_TYPES.ThisExpression
          ? staticMemberName(expression.left)
          : null;
      if (
        expression?.type !== AST_NODE_TYPES.AssignmentExpression ||
        !STORAGE_ASSIGNMENT_OPERATORS.has(expression.operator) ||
        expression.left.type !== AST_NODE_TYPES.MemberExpression ||
        expression.left.object.type !== AST_NODE_TYPES.ThisExpression ||
        storedField === null
      ) {
        for (const key of Object.keys(current) as (keyof TSESTree.Node)[]) {
          if (key === "parent") continue;
          const value = current[key];
          for (const child of (Array.isArray(value) ? value : [value]) as unknown[]) {
            if (child !== null && typeof child === "object" && typeof (child as { type?: unknown }).type === "string") {
              pending.push(child as TSESTree.Node);
            }
          }
        }
        continue;
      }
      let source = expression.right;
      while (
        source.type === AST_NODE_TYPES.TSNonNullExpression ||
        source.type === AST_NODE_TYPES.TSAsExpression ||
        source.type === AST_NODE_TYPES.TSSatisfiesExpression ||
        source.type === AST_NODE_TYPES.TSTypeAssertion
      ) source = source.expression;
      if (source.type === AST_NODE_TYPES.NewExpression) {
        constructedFields += 1;
      } else if (source.type === AST_NODE_TYPES.Identifier) {
        // `this.svc = svc`
        const fields = storedFieldsFrom.get(source.name) ?? new Set<string>();
        fields.add(storedField);
        storedFieldsFrom.set(source.name, fields);
      } else if (
        source.type === AST_NODE_TYPES.MemberExpression &&
        source.object.type === AST_NODE_TYPES.Identifier
      ) {
        // `this.slack = deps.slack` — a dependency bag spread onto fields.
        const fields = storedFieldsFrom.get(source.object.name) ?? new Set<string>();
        fields.add(storedField);
        storedFieldsFrom.set(source.object.name, fields);
        const member = staticMemberName(source);
        if (member !== null) {
          const members = storedMemberFieldsFrom.get(source.object.name) ?? new Map<string, Set<string>>();
          const memberFields = members.get(member) ?? new Set<string>();
          memberFields.add(storedField);
          members.set(member, memberFields);
          storedMemberFieldsFrom.set(source.object.name, members);
        }
      }
    }
  }

  const collaborators: Collaborator[] = [];
  for (const parameter of ctor.value.params) {
    for (const reference of parameterCollaborators(parameter, declared, storedMemberFieldsFrom)) {
      const fields =
        parameter.type === AST_NODE_TYPES.TSParameterProperty
          ? [reference.name]
          : reference.fields.length > 0
            ? reference.fields
            : [...(storedFieldsFrom.get(reference.name) ?? [])];
      if (fields.length === 0) continue;
      if (CONFIGISH_TYPE_RE.test(reference.typeName)) continue;
      if (CONFIGISH_NAME_RE.test(reference.name)) continue;
      // A bare type reference can still be one of three things a port would
      // protect nothing about, each of them the inline shape this rule already
      // rejects wearing a nominal name.
      if (typeParameters.has(reference.typeName)) continue;
      if (BUILTIN_CONTAINER_TYPE_RE.test(reference.typeName)) continue;
      if (VALUE_TYPE_RE.test(reference.typeName)) continue;
      if (declared().functionAliases.has(reference.typeName)) continue;
      collaborators.push({ ...reference, fields });
    }
  }

  return { collaborators, constructedFields };
};

/** Every collaborator a single constructor parameter contributes: 0, 1, or (destructured) many. */
const parameterCollaborators = (
  parameter: TSESTree.Parameter,
  declared: () => FileTypeIndex,
  storedMemberFieldsFrom: ReadonlyMap<string, ReadonlyMap<string, ReadonlySet<string>>>,
): readonly Collaborator[] => {
  let target: TSESTree.Node = parameter;
  if (target.type === AST_NODE_TYPES.AssignmentPattern) target = target.left;
  if (target.type === AST_NODE_TYPES.ObjectPattern) {
    return objectPatternCollaborators(target, declared);
  }
  const named = namedParameterCollaborator(parameter);
  if (
    named !== null &&
    !CONFIGISH_NAME_RE.test(named.name) &&
    !CONFIGISH_TYPE_RE.test(named.typeName)
  ) return [named];
  return namedBagCollaborators(parameter, declared, storedMemberFieldsFrom);
};

/** Resolve `this.repo = options.repo` without treating the whole options bag as a service. */
const namedBagCollaborators = (
  annotated: TSESTree.Parameter,
  declared: () => FileTypeIndex,
  storedMemberFieldsFrom: ReadonlyMap<string, ReadonlyMap<string, ReadonlySet<string>>>,
): Collaborator[] => {
  let target: TSESTree.Node = annotated;
  if (target.type === AST_NODE_TYPES.TSParameterProperty) target = target.parameter;
  if (target.type === AST_NODE_TYPES.AssignmentPattern) target = target.left;
  if (target.type !== AST_NODE_TYPES.Identifier) return [];
  const members = bagMemberTypes(target.typeAnnotation?.typeAnnotation, declared);
  if (members === null) return [];
  const storedMembers = storedMemberFieldsFrom.get(target.name);
  if (storedMembers === undefined) return [];

  const collaborators: Collaborator[] = [];
  for (const [name, fields] of storedMembers) {
    if (CONFIGISH_NAME_RE.test(name)) continue;
    const reference = members.get(name);
    if (reference === undefined) continue;
    collaborators.push({ name, ...reference, fields: [...fields] });
  }
  return collaborators;
};

const namedParameterCollaborator = (annotated: TSESTree.Parameter): Collaborator | null => {
  let target: TSESTree.Node = annotated;
  if (target.type === AST_NODE_TYPES.TSParameterProperty) target = target.parameter;
  if (target.type === AST_NODE_TYPES.AssignmentPattern) target = target.left;
  if (target.type !== AST_NODE_TYPES.Identifier) return null;
  const reference = readTypeReference(target.typeAnnotation?.typeAnnotation);
  if (reference === null) return null;
  return { name: target.name, ...reference, fields: [] };
};

interface ConstructorFacts {
  /** Parameters assigned to an instance field, either as a parameter property or in the body. */
  readonly collaborators: readonly Collaborator[];
  /** How many instance fields the constructor fills with a `new` expression. */
  readonly constructedFields: number;
}

/** Resolve separately stored collaborators from a locally typed constructor bag. */
const objectPatternCollaborators = (
  pattern: TSESTree.ObjectPattern,
  declared: () => FileTypeIndex,
): Collaborator[] => {
  const annotation = pattern.typeAnnotation?.typeAnnotation;
  if (annotation === undefined) return [];
  const members = bagMemberTypes(annotation, declared);
  if (members === null) return [];

  const collaborators: Collaborator[] = [];
  for (const property of pattern.properties) {
    if (property.type !== AST_NODE_TYPES.Property || property.computed) continue;
    if (property.key.type !== AST_NODE_TYPES.Identifier) continue;
    const key = property.key.name;
    const bound =
      property.value.type === AST_NODE_TYPES.AssignmentPattern
        ? property.value.left
        : property.value;
    if (bound.type !== AST_NODE_TYPES.Identifier) continue;
    // A renamed binding (`{ repo: userRepo }`) offers two names; either one
    // reading as config-ish is enough to drop it, on the same reasoning that
    // drops a config-ish parameter name.
    if (CONFIGISH_NAME_RE.test(key)) continue;
    const reference = members.get(key);
    if (reference === undefined) continue;
    collaborators.push({ name: bound.name, ...reference, fields: [] });
  }
  return collaborators;
};

/**
 * Member types of an options-object parameter's annotation: the annotation's own
 * body when it is written inline, otherwise the declaration it names, resolved
 * in this file only.
 */
const bagMemberTypes = (
  annotation: TSESTree.TypeNode | undefined,
  declared: () => FileTypeIndex,
): MemberTypes | null => {
  if (annotation === undefined) return null;
  if (annotation.type === AST_NODE_TYPES.TSTypeLiteral) {
    return propertySignatureTypes(annotation.members);
  }
  // A qualified `catalog.Deps` names another module by construction.
  if (
    annotation.type !== AST_NODE_TYPES.TSTypeReference ||
    annotation.typeName.type !== AST_NODE_TYPES.Identifier
  ) {
    return null;
  }
  return declared().objects.get(annotation.typeName.name) ?? null;
};

/** Framework router wiring is mounted at bootstrap rather than injected into consumers. */
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

const invokedInstanceField = (call: TSESTree.CallExpression): string | null => {
  const direct = instanceField(call.callee);
  if (direct !== null) return direct;
  let callee: TSESTree.Node = call.callee;
  while (
    callee.type === AST_NODE_TYPES.ChainExpression ||
    callee.type === AST_NODE_TYPES.TSAsExpression ||
    callee.type === AST_NODE_TYPES.TSNonNullExpression ||
    callee.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    callee.type === AST_NODE_TYPES.TSTypeAssertion
  ) callee = callee.expression;
  return callee.type === AST_NODE_TYPES.MemberExpression ? instanceField(callee.object) : null;
};

const instanceField = (candidate: TSESTree.Node): string | null => {
  let node = candidate;
  while (
    node.type === AST_NODE_TYPES.ChainExpression ||
    node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression ||
    node.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    node.type === AST_NODE_TYPES.TSTypeAssertion
  ) node = node.expression;
  return node.type === AST_NODE_TYPES.MemberExpression &&
    node.object.type === AST_NODE_TYPES.ThisExpression
    ? staticMemberName(node)
    : null;
};

/** Instance fields whose retained object is called or receives a direct method call. */
const behaviorallyInvokedFields = (body: TSESTree.ClassBody): ReadonlySet<string> => {
  const invoked = new Set<string>();
  const visit = (current: TSESTree.Node): void => {
    if (
      current.type === AST_NODE_TYPES.ClassDeclaration ||
      current.type === AST_NODE_TYPES.ClassExpression ||
      current.type === AST_NODE_TYPES.FunctionDeclaration ||
      current.type === AST_NODE_TYPES.FunctionExpression
    ) return;
    if (current.type === AST_NODE_TYPES.CallExpression) {
      const field = invokedInstanceField(current);
      if (field !== null) invoked.add(field);
    }
    for (const key of Object.keys(current) as (keyof TSESTree.Node)[]) {
      if (key === "parent") continue;
      const value = current[key];
      for (const child of (Array.isArray(value) ? value : [value]) as unknown[]) {
        if (
          child !== null &&
          typeof child === "object" &&
          typeof (child as { type?: unknown }).type === "string"
        ) visit(child as TSESTree.Node);
      }
    }
  };
  for (const member of body.body) {
    if (member.type === AST_NODE_TYPES.StaticBlock || member.static) continue;
    if (member.type === AST_NODE_TYPES.MethodDefinition) {
      if (member.value.body !== null && member.value.body !== undefined) visit(member.value.body);
      continue;
    }
    if (member.type !== AST_NODE_TYPES.PropertyDefinition || member.value === null) continue;
    visit(
      member.value.type === AST_NODE_TYPES.ArrowFunctionExpression
        ? member.value.body
        : member.value,
    );
  }
  return invoked;
};

const stem = (name: string): string => name.replace(/^I(?=[A-Z])/, "").replace(/Impl$/, "");

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

const publicMethodNames = (
  body: TSESTree.ClassBody,
  functionAliases: ReadonlySet<string>,
): string[] => {
  const names: string[] = [];
  for (const member of body.body) {
    if (member.type === AST_NODE_TYPES.PropertyDefinition) {
      if (member.static || member.accessibility === "private" || member.accessibility === "protected") continue;
      // ECMAScript #private fields have no TypeScript accessibility modifier.
      // A function-valued #field is still implementation detail and must not
      // become the synthetic public surface member `…`.
      if (member.key.type === AST_NODE_TYPES.PrivateIdentifier) continue;
      if (
        member.value?.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
        member.value?.type !== AST_NODE_TYPES.FunctionExpression &&
        member.typeAnnotation?.typeAnnotation.type !== AST_NODE_TYPES.TSFunctionType &&
        !(
          member.typeAnnotation?.typeAnnotation.type === AST_NODE_TYPES.TSTypeReference &&
          member.typeAnnotation.typeAnnotation.typeName.type === AST_NODE_TYPES.Identifier &&
          functionAliases.has(member.typeAnnotation.typeAnnotation.typeName.name)
        )
      ) continue;
      names.push(member.key.type === AST_NODE_TYPES.Identifier ? member.key.name : "…");
      continue;
    }
    if (member.type !== AST_NODE_TYPES.MethodDefinition) continue;
    if (member.kind !== "method" || member.static) continue;
    if (member.accessibility === "private" || member.accessibility === "protected") continue;
    if (member.key.type === AST_NODE_TYPES.PrivateIdentifier) continue;
    if (member.key.type === AST_NODE_TYPES.Identifier) names.push(member.key.name);
    else names.push("…");
  }
  return names;
};

const isFluentConstructionObject = (
  node: TSESTree.ClassDeclaration,
  getText: (node: TSESTree.Node) => string,
): boolean => {
  if (node.id === null) return false;
  const methods = node.body.body.filter(
    (member): member is TSESTree.MethodDefinition =>
      member.type === AST_NODE_TYPES.MethodDefinition &&
      member.kind === "method" &&
      !member.static &&
      member.accessibility !== "private" &&
      member.accessibility !== "protected" &&
      member.value.body !== null,
  );
  if (methods.length === 0) return false;
  return methods.every((member) => {
    const result = member.value.returnType?.typeAnnotation;
    if (result === undefined) return false;
    const returnsOwnType =
      result.type === AST_NODE_TYPES.TSTypeReference &&
      result.typeName.type === AST_NODE_TYPES.Identifier &&
      result.typeName.name === node.id?.name;
    return returnsOwnType ||
      (FLUENT_BUILDER_NAME_RE.test(node.id?.name ?? "") && FLUENT_RESULT_TYPE_RE.test(getText(result)));
  });
};

function localClassAbstractness(program: TSESTree.Program): ReadonlyMap<string, boolean> {
  const classes = new Map<string, boolean>();
  const parents = new Map<string, string>();
  for (const statement of program.body) {
    const declaration = statement.type === AST_NODE_TYPES.ExportNamedDeclaration ||
      statement.type === AST_NODE_TYPES.ExportDefaultDeclaration
      ? statement.declaration
      : statement;
    if (declaration?.type === AST_NODE_TYPES.ClassDeclaration && declaration.id !== null) {
      classes.set(declaration.id.name, declaration.abstract === true);
      if (declaration.superClass?.type === AST_NODE_TYPES.Identifier) {
        parents.set(declaration.id.name, declaration.superClass.name);
      }
    }
  }
  for (let pass = 0; pass < classes.size; pass += 1) {
    let changed = false;
    for (const [name, parent] of parents) {
      if (classes.get(name) !== true && classes.get(parent) === true) {
        classes.set(name, true);
        changed = true;
      }
    }
    if (!changed) break;
  }
  return classes;
}

function localInterfaceSurfaces(program: TSESTree.Program): ReadonlyMap<string, ReadonlySet<string>> {
  const interfaces = new Map<string, Set<string>>();
  const parents = new Map<string, string[]>();
  const functionAliases = new Set<string>();
  for (const statement of program.body) {
    const declaration = statement.type === AST_NODE_TYPES.ExportNamedDeclaration
      ? statement.declaration
      : statement;
    if (
      declaration?.type === AST_NODE_TYPES.TSTypeAliasDeclaration &&
      (declaration.typeAnnotation.type === AST_NODE_TYPES.TSFunctionType ||
        declaration.typeAnnotation.type === AST_NODE_TYPES.TSConstructorType)
    ) functionAliases.add(declaration.id.name);
  }
  for (const statement of program.body) {
    const declaration = statement.type === AST_NODE_TYPES.ExportNamedDeclaration
      ? statement.declaration
      : statement;
    if (declaration?.type === AST_NODE_TYPES.TSTypeAliasDeclaration) {
      const callables = interfaces.get(declaration.id.name) ?? new Set<string>();
      const parts = declaration.typeAnnotation.type === AST_NODE_TYPES.TSIntersectionType
        ? declaration.typeAnnotation.types
        : [declaration.typeAnnotation];
      const inherited = parents.get(declaration.id.name) ?? [];
      for (const part of parts) {
        if (part.type === AST_NODE_TYPES.TSTypeReference && part.typeName.type === AST_NODE_TYPES.Identifier) {
          inherited.push(part.typeName.name);
          continue;
        }
        if (part.type !== AST_NODE_TYPES.TSTypeLiteral) continue;
        for (const member of part.members) {
          if (
            member.type !== AST_NODE_TYPES.TSMethodSignature &&
            member.type !== AST_NODE_TYPES.TSPropertySignature
          ) continue;
          if (member.computed || member.key.type !== AST_NODE_TYPES.Identifier) continue;
          if (member.type === AST_NODE_TYPES.TSMethodSignature) {
            callables.add(member.key.name);
            continue;
          }
          if (member.type !== AST_NODE_TYPES.TSPropertySignature) continue;
          const annotation = member.typeAnnotation?.typeAnnotation;
          if (
            annotation?.type === AST_NODE_TYPES.TSFunctionType ||
            (annotation?.type === AST_NODE_TYPES.TSTypeReference &&
              annotation.typeName.type === AST_NODE_TYPES.Identifier &&
              functionAliases.has(annotation.typeName.name))
          ) callables.add(member.key.name);
        }
      }
      interfaces.set(declaration.id.name, callables);
      parents.set(declaration.id.name, inherited);
      continue;
    }
    if (declaration?.type !== AST_NODE_TYPES.TSInterfaceDeclaration) continue;
    const callables = interfaces.get(declaration.id.name) ?? new Set<string>();
    for (const member of declaration.body.body) {
      if (
        member.type !== AST_NODE_TYPES.TSMethodSignature &&
        member.type !== AST_NODE_TYPES.TSPropertySignature
      ) continue;
      if (member.computed || member.key.type !== AST_NODE_TYPES.Identifier) continue;
      if (
        member.type === AST_NODE_TYPES.TSMethodSignature ||
        member.typeAnnotation?.typeAnnotation.type === AST_NODE_TYPES.TSFunctionType ||
        (member.typeAnnotation?.typeAnnotation.type === AST_NODE_TYPES.TSTypeReference &&
          member.typeAnnotation.typeAnnotation.typeName.type === AST_NODE_TYPES.Identifier &&
          functionAliases.has(member.typeAnnotation.typeAnnotation.typeName.name))
      ) callables.add(member.key.name);
    }
    interfaces.set(declaration.id.name, callables);
    parents.set(
      declaration.id.name,
      [
        ...(parents.get(declaration.id.name) ?? []),
        ...declaration.extends.flatMap((heritage) =>
        heritage.expression.type === AST_NODE_TYPES.Identifier ? [heritage.expression.name] : ["*"],
        ),
      ],
    );
  }
  for (let pass = 0; pass <= interfaces.size; pass += 1) {
    let changed = false;
    for (const [name, inherited] of parents) {
      const surface = interfaces.get(name);
      if (surface === undefined) continue;
      for (const parent of inherited) {
        const parentSurface = interfaces.get(parent);
        const additions = parentSurface ?? new Set(["*"]);
        for (const method of additions) {
          if (!surface.has(method)) {
            surface.add(method);
            changed = true;
          }
        }
      }
    }
    if (!changed) break;
  }
  return interfaces;
}

function hasServicePort(
  node: TSESTree.ClassDeclaration,
  methods: readonly string[],
  classes: ReadonlyMap<string, boolean>,
  interfaces: ReadonlyMap<string, ReadonlySet<string>>,
): boolean {
  if (node.superClass !== null) {
    if (node.superClass.type !== AST_NODE_TYPES.Identifier) return true;
    const localAbstract = classes.get(node.superClass.name);
    if (localAbstract === undefined || localAbstract) return true;
  }
  if (node.id !== null) {
    const classStem = stem(node.id.name);
    const structuralPort = [...interfaces].find(([name]) => stem(name) === classStem)?.[1];
    if (
      structuralPort !== undefined &&
      (structuralPort.has("*") || methods.every((method) => structuralPort.has(method)))
    ) return true;
  }
  if (node.implements.length === 0) return false;
  const combined = new Set<string>();
  for (const implementation of node.implements) {
    if (implementation.expression.type !== AST_NODE_TYPES.Identifier) return true;
    const name = implementation.expression.name;
    const localAbstract = classes.get(name);
    if (localAbstract === true) return true;
    const surface = interfaces.get(name);
    if (surface === undefined && localAbstract === undefined) return true;
    if (surface === undefined) continue;
    if (surface.has("*")) return true;
    for (const method of surface) combined.add(method);
  }
  return methods.every((method) => combined.has(method));
}

export default createRule<Options, MessageIds>({
  name: "require-port-for-service",
  documentation: REQUIRE_PORT_FOR_SERVICE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Advise when an exported service with injected collaborators has public methods not covered by its declared ports.",
    },
    schema: [],
    messages: {
      requireInterface:
        "`{{name}}` stores injected collaborator(s) ({{deps}}), and its declared ports do not cover its public callable surface ({{methods}}). Where consumers need substitution, type them against one or more focused interfaces; do not create one broad interface solely to satisfy this advisory.",
    },
  },
  defaultOptions: [],
  create(context) {
    const { filename } = context;
    if (isTestFile(filename) || isStoryFile(filename) || isScriptFile(filename)) return {};
    if (isGeneratedFile(filename, context.sourceCode.getText())) return {};

    // One pass over the module's top level, and only for a file that actually
    // has an options-object constructor to read.
    let declaredTypes: FileTypeIndex | null = null;
    const detachedExports = detachedValueExports(context.sourceCode.ast);
    const localClasses = localClassAbstractness(context.sourceCode.ast);
    const localInterfaces = localInterfaceSurfaces(context.sourceCode.ast);
    const objectTypes = (): FileTypeIndex =>
      (declaredTypes ??= fileTypeIndex(context.sourceCode.ast));

    return {
      ClassDeclaration(node: TSESTree.ClassDeclaration): void {
        if (node.id === null) return;
        if (!isExportedClass(node, detachedExports)) return;
        if (ERROR_VALUE_NAME_RE.test(node.id.name)) return;
        // The port itself must never fire.
        if (node.abstract === true) return;
        if (node.decorators.length > 0) return;

        const ctor = node.body.body.find(
          (member): member is TSESTree.MethodDefinition =>
            member.type === AST_NODE_TYPES.MethodDefinition &&
            member.kind === "constructor" &&
            member.value.body !== null &&
            member.value.body !== undefined,
        );
        if (ctor === undefined) return;

        const constructorFacts = readConstructor(
          ctor,
          objectTypes,
          typeParameterNames(node.typeParameters, ctor.value.typeParameters),
        );
        const invoked = behaviorallyInvokedFields(node.body);
        const collaborators = constructorFacts.collaborators.filter((collaborator) =>
          collaborator.fields.some((field) => invoked.has(field)),
        );
        if (collaborators.length === 0) return;
        if (constructorFacts.constructedFields > collaborators.length) return;
        // HTTP wiring: a router factory is mounted by the bootstrap, not injected.
        if (isFrameworkWiring(node.body)) return;
        // A lone third-party transport is not a seam a port could protect.
        if (isTransportWrapper(node.id.name, collaborators, context.sourceCode.ast)) return;
        if (isFluentConstructionObject(node, (result) => context.sourceCode.getText(result))) return;

        const methods = publicMethodNames(node.body, objectTypes().functionAliases);
        if (methods.length === 0) return;
        if (hasServicePort(node, methods, localClasses, localInterfaces)) return;

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
