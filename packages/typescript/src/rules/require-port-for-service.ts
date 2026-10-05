/**
 * @fileoverview require-port-for-service — advisory detection for exported services that may benefit from focused consumer ports.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-port-for-service.test.ts
 */

import type { ESTree } from "@oxlint/plugins";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { sourceOrigin } from "./_source-origin.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import {
  isGeneratedFile,
  isScriptFile,
  isStoryFile,
  isTestFile,
} from "./_paths.js";

type MessageIds = "requireInterface";
type Options = readonly [];

export const REQUIRE_PORT_FOR_SERVICE_DOCUMENTATION = {
  summary:
    "Advise when an exported service with injected collaborators has public methods not covered by its declared ports.",
  rationale:
    "A declared port keeps consumers coupled to the service capability instead of its concrete implementation.",
  remediation:
    "Declare and implement an interface covering the service's public methods.",
  category: "architecture",
  aliases: ["require-interface-for-injected-service"],
  examples: [
    {
      id: "declared-service-port",
      title: "Implement the service port",
      outcome: "no-match",
      files: [
        {
          path: "src/service.ts",
          source:
            "interface Handler { handle(): void }\nexport class RequestHandler implements Handler { constructor(private readonly store: TaskStore) {} handle(): void { this.store.handle(); } }",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "concrete-injected-service",
      title: "Do not expose only the concrete service",
      outcome: "match",
      files: [
        {
          path: "src/service.ts",
          source:
            "export class RequestHandler { constructor(private readonly store: TaskStore) {} handle(): void { this.store.handle(); } }",
        },
      ],
      focusPath: "src/service.ts",
      expectedCount: 1,
      public: true,
    },
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
const VALUE_TYPE_RE =
  /^(?:ArrayBuffer|Blob|Buffer|Date|NodePath|RegExp|URL|URLSearchParams)$/;

const TRANSPORT_WRAPPER_NAME_RE = /(?:Client$|^Http[A-Z])/;
/** Error values carry diagnostic data; their callable formatting surface is not a service port. */
const ERROR_VALUE_NAME_RE = /Error$/;
const FLUENT_BUILDER_NAME_RE = /Builder$/;
const FLUENT_RESULT_TYPE_RE = /(?:Builder|Base|Query|Without)(?:\W|$)/;

/** Router-factory call that marks HTTP wiring. */
const ROUTER_FACTORY_NAME = "Router";

/** Namespaced framework HTTP types; unqualified DOM globals do not match. */
const FRAMEWORK_HTTP_TYPES: ReadonlySet<string> = new Set([
  "Request",
  "Response",
  "NextFunction",
]);
const STORAGE_ASSIGNMENT_OPERATORS: ReadonlySet<string> = new Set([
  "=",
  "&&=",
  "??=",
  "||=",
]);

interface Collaborator {
  readonly name: string;
  /** Rightmost segment of the type name — what the config-ish guards test. */
  readonly typeName: string;
  /** Full source spelling, including any namespace qualifier, for the message. */
  readonly display: string;
  /** Instance fields that retain this constructor parameter. */
  readonly fields: readonly string[];
}

const staticMemberName = (member: ESTree.MemberExpression): string | null => {
  if (member.property.type === "PrivateIdentifier")
    return `#${member.property.name}`;
  if (!member.computed && member.property.type === "Identifier")
    return member.property.name;
  return member.computed &&
    member.property.type === "Literal" &&
    typeof member.property.value === "string"
    ? member.property.value
    : null;
};

const detachedValueExports = (program: ESTree.Program): ReadonlySet<string> => {
  const names = new Set<string>();
  for (const statement of program.body) {
    if (
      statement.type === "ExportNamedDeclaration" &&
      statement.declaration === null &&
      statement.source === null &&
      statement.exportKind !== "type"
    ) {
      for (const specifier of statement.specifiers) {
        if (
          specifier.exportKind !== "type" &&
          specifier.local.type === "Identifier"
        )
          names.add(specifier.local.name);
      }
    } else if (
      statement.type === "ExportDefaultDeclaration" &&
      statement.declaration.type === "Identifier"
    ) {
      names.add(statement.declaration.name);
    } else if (
      statement.type === "TSExportAssignment" &&
      statement.expression.type === "Identifier"
    ) {
      names.add(statement.expression.name);
    }
  }
  return names;
};

const isExportedClass = (
  node: ESTree.Class,
  detached: ReadonlySet<string>,
): boolean =>
  node.parent.type === "ExportNamedDeclaration" ||
  node.parent.type === "ExportDefaultDeclaration" ||
  (node.id !== null && detached.has(node.id.name));

export const createExportedServiceClassResolver = (
  program: ESTree.Program,
): ((node: ESTree.Class) => boolean) => {
  const detached = detachedValueExports(program);
  return (node): boolean => isExportedClass(node, detached);
};

/** The rightmost segment plus the full spelling of a bare type reference, or null for anything else. */
const readTypeReference = (
  annotation: ESTree.TSType | undefined,
): { readonly typeName: string; readonly display: string } | null => {
  if (annotation?.type === "TSUnionType") {
    const members = annotation.types.filter(
      (member) =>
        member.type !== "TSUndefinedKeyword" && member.type !== "TSNullKeyword",
    );
    annotation = members.length === 1 ? members[0] : undefined;
  }
  if (annotation === undefined || annotation.type !== "TSTypeReference")
    return null;
  const { typeName } = annotation;
  const rightmost =
    typeName.type === "Identifier"
      ? typeName.name
      : typeName.type === "TSQualifiedName"
        ? typeName.right.name
        : null;
  if (rightmost === null) return null;
  return { typeName: rightmost, display: qualifiedName(typeName) };
};

/** `catalog.Client` -> `"catalog.Client"`; a nested qualifier is flattened the same way. */
const qualifiedName = (name: ESTree.TSTypeReference["typeName"]): string =>
  name.type === "Identifier"
    ? name.name
    : name.type === "TSQualifiedName"
      ? `${qualifiedName(name.left)}.${name.right.name}`
      : "";

/** Property signatures of a `{ a: A; b: B }` body, keyed by property name. */
const propertySignatureTypes = (
  members: readonly ESTree.TSTypeLiteral["members"][number][],
): Map<string, TypeReference> => {
  const types = new Map<string, TypeReference>();
  for (const member of members) {
    if (member.type !== "TSPropertySignature") continue;
    if (member.computed || member.key.type !== "Identifier") continue;
    const reference = readTypeReference(member.typeAnnotation?.typeAnnotation);
    if (reference === null) continue;
    types.set(member.key.name, reference);
  }
  return types;
};

type TypeReference = { readonly typeName: string; readonly display: string };
type MemberTypes = ReadonlyMap<string, TypeReference>;

const fileTypeIndex = (program: ESTree.Program): FileTypeIndex => {
  const objects = new Map<string, MemberTypes>();
  const functionAliases = localFunctionAliases(program);
  function collectDeclaredType(statement: ESTree.Statement): void {
    const declaration =
      statement.type === "ExportNamedDeclaration"
        ? statement.declaration
        : statement;
    if (declaration?.type === "TSInterfaceDeclaration") {
      objects.set(
        declaration.id.name,
        propertySignatureTypes(declaration.body.body),
      );
      return;
    }
    if (declaration?.type !== "TSTypeAliasDeclaration") return;
    const aliased = declaration.typeAnnotation;
    // `type Deps = { … }` and `type Deps = Base & { … }` both resolve; the
    // intersection form is how a bag is usually extended.
    const literals =
      aliased.type === "TSTypeLiteral"
        ? [aliased]
        : aliased.type === "TSIntersectionType"
          ? aliased.types.filter((part) => part.type === "TSTypeLiteral")
          : [];
    if (literals.length === 0) return;
    const merged = new Map<string, TypeReference>();
    for (const literal of literals) {
      for (const [name, reference] of propertySignatureTypes(literal.members)) {
        merged.set(name, reference);
      }
    }
    objects.set(declaration.id.name, merged);
  }

  for (const statement of program.body) {
    collectDeclaredType(statement);
  }
  return { objects, functionAliases };
};

/** Direct callable aliases and local aliases to them share the same capability. */
function localFunctionAliases(program: ESTree.Program): ReadonlySet<string> {
  const names = new Set<string>();
  const parents = new Map<string, string>();
  for (const statement of program.body) {
    const declaration =
      statement.type === "ExportNamedDeclaration"
        ? statement.declaration
        : statement;
    if (declaration?.type !== "TSTypeAliasDeclaration") continue;
    const annotation = declaration.typeAnnotation;
    if (
      annotation.type === "TSFunctionType" ||
      annotation.type === "TSConstructorType"
    )
      names.add(declaration.id.name);
    if (
      annotation.type === "TSTypeReference" &&
      annotation.typeName.type === "Identifier"
    )
      parents.set(declaration.id.name, annotation.typeName.name);
  }
  for (let pass = 0; pass < parents.size; pass += 1) {
    let changed = false;
    for (const [name, parent] of parents) {
      if (names.has(parent) && !names.has(name)) {
        names.add(name);
        changed = true;
      }
    }
    if (!changed) break;
  }
  return names;
}

/** Locally declared object shapes and function aliases used to resolve constructor bags. */
interface FileTypeIndex {
  /** `interface Deps { … }` / `type Deps = { … }`, by name. */
  readonly objects: ReadonlyMap<string, MemberTypes>;
  /** `type Replayer = (e: Event) => void` — a callback with a nominal name. */
  readonly functionAliases: ReadonlySet<string>;
}

/** Names bound by `class Foo<T>` / `constructor<T>()` — placeholders, not implementations. */
const typeParameterNames = (
  ...declarations: readonly (
    | ESTree.TSTypeParameterDeclaration
    | null
    | undefined
  )[]
): ReadonlySet<string> => {
  const names = new Set<string>();
  for (const declaration of declarations) {
    for (const parameter of declaration?.params ?? [])
      names.add(parameter.name.name);
  }
  return names;
};

const readConstructor = (
  ctor: ESTree.MethodDefinition,
  declared: () => FileTypeIndex,
  typeParameters: ReadonlySet<string>,
): ConstructorFacts => {
  const body = ctor.value.body;
  const storedFieldsFrom = new Map<string, Set<string>>();
  const storedMemberFieldsFrom = new Map<string, Map<string, Set<string>>>();
  const constructedFieldNames = new Set<string>();
  const localBindings = new Set<string>();
  let constructedFields = 0;

  if (body !== null && body !== undefined) scanStoredFields(body);

  function scanStoredFields(body: ESTree.BlockStatement): void {
    const pending: ESTree.Node[] = [...body.body];
    function recordStoredField(current: ESTree.Node): void {
      if (
        current.type === "ArrowFunctionExpression" ||
        current.type === "FunctionExpression" ||
        current.type === "FunctionDeclaration" ||
        current.type === "ClassExpression" ||
        current.type === "ClassDeclaration"
      )
        return;
      if (
        current.type === "VariableDeclarator" &&
        current.id.type === "Identifier"
      )
        localBindings.add(current.id.name);
      const expression =
        current.type === "ExpressionStatement" ? current.expression : null;
      const storedField =
        expression?.type === "AssignmentExpression" &&
        expression.left.type === "MemberExpression" &&
        expression.left.object.type === "ThisExpression"
          ? staticMemberName(expression.left)
          : null;
      if (
        expression?.type !== "AssignmentExpression" ||
        !STORAGE_ASSIGNMENT_OPERATORS.has(expression.operator) ||
        expression.left.type !== "MemberExpression" ||
        expression.left.object.type !== "ThisExpression" ||
        storedField === null
      ) {
        enqueueChildren(current);
        return;
      }
      let source = expression.right;
      while (
        source.type === "TSNonNullExpression" ||
        source.type === "TSAsExpression" ||
        source.type === "TSSatisfiesExpression" ||
        source.type === "TSTypeAssertion"
      )
        source = source.expression;
      if (source.type === "NewExpression") {
        constructedFields += 1;
        constructedFieldNames.add(storedField);
      } else if (source.type === "Identifier") {
        // `this.svc = svc`
        const fields = storedFieldsFrom.get(source.name) ?? new Set<string>();
        fields.add(storedField);
        storedFieldsFrom.set(source.name, fields);
      } else if (
        source.type === "MemberExpression" &&
        source.object.type === "Identifier"
      ) {
        // `this.slack = deps.slack` — a dependency bag spread onto fields.
        const fields =
          storedFieldsFrom.get(source.object.name) ?? new Set<string>();
        fields.add(storedField);
        storedFieldsFrom.set(source.object.name, fields);
        const member = staticMemberName(source);
        if (member !== null) {
          const members =
            storedMemberFieldsFrom.get(source.object.name) ??
            new Map<string, Set<string>>();
          const memberFields = members.get(member) ?? new Set<string>();
          memberFields.add(storedField);
          members.set(member, memberFields);
          storedMemberFieldsFrom.set(source.object.name, members);
        }
      }
    }

    function enqueueChildren(current: ESTree.Node): void {
      forEachOwnAstChild(current, (child) => {
        pending.push(child);
      });
    }

    while (pending.length > 0) {
      const current = pending.pop();
      if (current === undefined) break;
      recordStoredField(current);
    }
  }

  const collaborators: Collaborator[] = [];
  function collectCollaborators(parameter: ESTree.ParamPattern): void {
    for (const reference of parameterCollaborators(
      parameter,
      declared,
      storedMemberFieldsFrom,
    )) {
      if (localBindings.has(reference.name)) continue;
      let fields = reference.fields;
      if (parameter.type === "TSParameterProperty") fields = [reference.name];
      else if (fields.length === 0)
        fields = [...(storedFieldsFrom.get(reference.name) ?? [])];
      const injectedFields = fields.filter(
        (field) => !constructedFieldNames.has(field),
      );
      if (injectedFields.length === 0) continue;
      if (CONFIGISH_TYPE_RE.test(reference.typeName)) continue;
      if (CONFIGISH_NAME_RE.test(reference.name)) continue;
      // A bare type reference can still be one of three things a port would
      // protect nothing about, each of them the inline shape this rule already
      // rejects wearing a nominal name.
      if (typeParameters.has(reference.typeName)) continue;
      if (BUILTIN_CONTAINER_TYPE_RE.test(reference.typeName)) continue;
      if (VALUE_TYPE_RE.test(reference.typeName)) continue;
      if (declared().functionAliases.has(reference.typeName)) continue;
      collaborators.push({ ...reference, fields: injectedFields });
    }
  }

  for (const parameter of ctor.value.params) {
    collectCollaborators(parameter);
  }

  return { collaborators, constructedFields };
};

/** Every collaborator a single constructor parameter contributes: 0, 1, or (destructured) many. */
const parameterCollaborators = (
  parameter: ESTree.ParamPattern,
  declared: () => FileTypeIndex,
  storedMemberFieldsFrom: ReadonlyMap<
    string,
    ReadonlyMap<string, ReadonlySet<string>>
  >,
): readonly Collaborator[] => {
  let target: ESTree.Node = parameter;
  if (target.type === "AssignmentPattern") target = target.left;
  if (target.type === "ObjectPattern") {
    return objectPatternCollaborators(target, declared);
  }
  const named = namedParameterCollaborator(parameter);
  if (
    named !== null &&
    !CONFIGISH_NAME_RE.test(named.name) &&
    !CONFIGISH_TYPE_RE.test(named.typeName)
  )
    return [named];
  return namedBagCollaborators(parameter, declared, storedMemberFieldsFrom);
};

/** Resolve `this.repo = options.repo` without treating the whole options bag as a service. */
const namedBagCollaborators = (
  annotated: ESTree.ParamPattern,
  declared: () => FileTypeIndex,
  storedMemberFieldsFrom: ReadonlyMap<
    string,
    ReadonlyMap<string, ReadonlySet<string>>
  >,
): Collaborator[] => {
  let target: ESTree.Node = annotated;
  if (target.type === "TSParameterProperty") target = target.parameter;
  if (target.type === "AssignmentPattern") target = target.left;
  if (target.type !== "Identifier") return [];
  const members = bagMemberTypes(
    target.typeAnnotation?.typeAnnotation,
    declared,
  );
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

const namedParameterCollaborator = (
  annotated: ESTree.ParamPattern,
): Collaborator | null => {
  let target: ESTree.Node = annotated;
  if (target.type === "TSParameterProperty") target = target.parameter;
  if (target.type === "AssignmentPattern") target = target.left;
  if (target.type !== "Identifier") return null;
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
  pattern: Extract<ESTree.Node, { type: "ObjectPattern" }>,
  declared: () => FileTypeIndex,
): Collaborator[] => {
  const annotation = pattern.typeAnnotation?.typeAnnotation;
  if (annotation === undefined) return [];
  const members = bagMemberTypes(annotation, declared);
  if (members === null) return [];

  const collaborators: Collaborator[] = [];
  for (const property of pattern.properties) {
    if (property.type !== "Property" || property.computed) continue;
    if (property.key.type !== "Identifier") continue;
    const key = property.key.name;
    const bound =
      property.value.type === "AssignmentPattern"
        ? property.value.left
        : property.value;
    if (bound.type !== "Identifier") continue;
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
  annotation: ESTree.TSType | undefined,
  declared: () => FileTypeIndex,
): MemberTypes | null => {
  if (annotation === undefined) return null;
  if (annotation.type === "TSTypeLiteral") {
    return propertySignatureTypes(annotation.members);
  }
  // A qualified `catalog.Deps` names another module by construction.
  if (
    annotation.type !== "TSTypeReference" ||
    annotation.typeName.type !== "Identifier"
  ) {
    return null;
  }
  return declared().objects.get(annotation.typeName.name) ?? null;
};

/** Framework router wiring is mounted at bootstrap rather than injected into consumers. */
const isFrameworkWiring = (body: ESTree.ClassBody): boolean =>
  subtreeHas(body, (node) => {
    if (node.type === "CallExpression") {
      const { callee } = node;
      if (callee.type === "Identifier")
        return callee.name === ROUTER_FACTORY_NAME;
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

/** Walk every descendant node, `parent` links excluded, until `found` returns true. */
const subtreeHas = (
  root: ESTree.Node,
  found: (node: ESTree.Node) => boolean,
): boolean => {
  let hit = false;
  const visit = (current: ESTree.Node): void => {
    if (hit) return;
    if (found(current)) {
      hit = true;
      return;
    }
    forEachOwnAstChild(current, (child) => {
      visit(child);
      return hit;
    });
  };
  visit(root);
  return hit;
};

const invokedInstanceField = (call: ESTree.CallExpression): string | null => {
  const direct = instanceField(call.callee);
  if (direct !== null) return direct;
  let callee: ESTree.Node = call.callee;
  while (
    callee.type === "ChainExpression" ||
    callee.type === "TSAsExpression" ||
    callee.type === "TSNonNullExpression" ||
    callee.type === "TSSatisfiesExpression" ||
    callee.type === "TSTypeAssertion"
  )
    callee = callee.expression;
  return callee.type === "MemberExpression"
    ? instanceField(callee.object)
    : null;
};

const instanceField = (candidate: ESTree.Node): string | null => {
  let node = candidate;
  while (
    node.type === "ChainExpression" ||
    node.type === "TSAsExpression" ||
    node.type === "TSNonNullExpression" ||
    node.type === "TSSatisfiesExpression" ||
    node.type === "TSTypeAssertion"
  )
    node = node.expression;
  return node.type === "MemberExpression" &&
    node.object.type === "ThisExpression"
    ? staticMemberName(node)
    : null;
};

/** Instance fields whose retained object is called or receives a direct method call. */
const behaviorallyInvokedFields = (
  body: ESTree.ClassBody,
): ReadonlySet<string> => {
  const invoked = new Set<string>();
  const visit = (current: ESTree.Node): void => {
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
      if (member.value.body !== null && member.value.body !== undefined)
        visit(member.value.body);
      continue;
    }
    if (member.type !== "PropertyDefinition" || member.value === null) continue;
    visit(
      member.value.type === "ArrowFunctionExpression"
        ? member.value.body
        : member.value,
    );
  }
  return invoked;
};

const stem = (name: string): string =>
  name.replace(/^I(?=[A-Z])/, "").replace(/Impl$/, "");

/** Report whether the class is a thin wrapper over somebody else's HTTP transport. */
const isTransportWrapper = (
  className: string,
  collaborators: readonly Collaborator[],
  program: ESTree.Program,
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
const fileInterfaceNames = (program: ESTree.Program): string[] => {
  const names: string[] = [];
  for (const statement of program.body) {
    const declaration =
      statement.type === "ExportNamedDeclaration"
        ? statement.declaration
        : statement;
    if (declaration?.type === "TSInterfaceDeclaration")
      names.push(declaration.id.name);
  }
  return names;
};

const publicMethodNames = (
  body: ESTree.ClassBody,
  functionAliases: ReadonlySet<string>,
): string[] => {
  const names: string[] = [];
  function collectPublicCallable(member: ESTree.ClassElement): void {
    if (member.type === "PropertyDefinition") {
      if (
        member.static ||
        member.accessibility === "private" ||
        member.accessibility === "protected"
      )
        return;
      // ECMAScript #private fields have no TypeScript accessibility modifier.
      // A function-valued #field is still implementation detail and must not
      // become the synthetic public surface member `…`.
      if (member.key.type === "PrivateIdentifier") return;
      if (
        member.value?.type !== "ArrowFunctionExpression" &&
        member.value?.type !== "FunctionExpression" &&
        member.typeAnnotation?.typeAnnotation.type !== "TSFunctionType" &&
        !(
          member.typeAnnotation?.typeAnnotation.type === "TSTypeReference" &&
          member.typeAnnotation.typeAnnotation.typeName.type === "Identifier" &&
          functionAliases.has(
            member.typeAnnotation.typeAnnotation.typeName.name,
          )
        )
      )
        return;
      names.push(declaredMemberName(member) ?? "…");
      return;
    }
    if (member.type !== "MethodDefinition") return;
    if (member.kind !== "method" || member.static) return;
    if (
      member.accessibility === "private" ||
      member.accessibility === "protected"
    )
      return;
    if (member.key.type === "PrivateIdentifier") return;
    names.push(declaredMemberName(member) ?? "…");
  }

  for (const member of body.body) {
    collectPublicCallable(member);
  }
  return names;
};

const isFluentConstructionObject = (
  node: ESTree.Class,
  getText: (node: ESTree.Node) => string,
): boolean => {
  if (node.id === null) return false;
  const methods = node.body.body.filter(
    (member): member is ESTree.MethodDefinition =>
      member.type === "MethodDefinition" &&
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
      result.type === "TSTypeReference" &&
      result.typeName.type === "Identifier" &&
      result.typeName.name === node.id?.name;
    return (
      returnsOwnType ||
      (FLUENT_BUILDER_NAME_RE.test(node.id?.name ?? "") &&
        FLUENT_RESULT_TYPE_RE.test(getText(result)))
    );
  });
};

function localClassAbstractness(
  program: ESTree.Program,
): ReadonlyMap<string, boolean> {
  const classes = new Map<string, boolean>();
  const parents = new Map<string, string>();
  for (const statement of program.body) {
    const declaration =
      statement.type === "ExportNamedDeclaration" ||
      statement.type === "ExportDefaultDeclaration"
        ? statement.declaration
        : statement;
    if (declaration?.type === "ClassDeclaration" && declaration.id !== null) {
      classes.set(declaration.id.name, declaration.abstract === true);
      if (declaration.superClass?.type === "Identifier") {
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

function declaredMemberName(member: {
  key: ESTree.Node;
  computed: boolean;
}): string | null {
  if (!member.computed && member.key.type === "Identifier")
    return member.key.name;
  if (member.key.type === "Literal" && typeof member.key.value === "string")
    return member.key.value;
  return null;
}

function localInterfaceSurfaces(
  program: ESTree.Program,
): ReadonlyMap<string, ReadonlySet<string>> {
  const interfaces = new Map<string, Set<string>>();
  const parents = new Map<string, string[]>();
  const functionAliases = localFunctionAliases(program);
  function collectInterfaceSurface(statement: ESTree.Statement): void {
    const declaration =
      statement.type === "ExportNamedDeclaration"
        ? statement.declaration
        : statement;
    if (declaration?.type === "TSTypeAliasDeclaration") {
      const callables =
        interfaces.get(declaration.id.name) ?? new Set<string>();
      const parts =
        declaration.typeAnnotation.type === "TSIntersectionType"
          ? declaration.typeAnnotation.types
          : [declaration.typeAnnotation];
      const inherited = parents.get(declaration.id.name) ?? [];
      for (const part of parts) {
        if (
          part.type === "TSTypeReference" &&
          part.typeName.type === "Identifier"
        ) {
          inherited.push(part.typeName.name);
          continue;
        }
        if (part.type === "TSTypeReference") {
          inherited.push("*");
          continue;
        }
        if (part.type !== "TSTypeLiteral") continue;
        addCallableMembers(part.members, callables);
      }
      interfaces.set(declaration.id.name, callables);
      parents.set(declaration.id.name, inherited);
      return;
    }
    if (declaration?.type !== "TSInterfaceDeclaration") return;
    const callables = interfaces.get(declaration.id.name) ?? new Set<string>();
    addCallableMembers(declaration.body.body, callables);
    interfaces.set(declaration.id.name, callables);
    parents.set(declaration.id.name, [
      ...(parents.get(declaration.id.name) ?? []),
      ...declaration.extends.flatMap((heritage) =>
        heritage.expression.type === "Identifier"
          ? [heritage.expression.name]
          : ["*"],
      ),
    ]);
  }

  for (const statement of program.body) {
    collectInterfaceSurface(statement);
  }
  function addCallableMembers(
    members: readonly ESTree.TSTypeLiteral["members"][number][],
    callables: Set<string>,
  ): void {
    for (const member of members) {
      if (
        member.type !== "TSMethodSignature" &&
        member.type !== "TSPropertySignature"
      )
        continue;
      const name = declaredMemberName(member);
      if (name === null) continue;
      if (member.type === "TSMethodSignature") {
        callables.add(name);
        continue;
      }
      if (member.type !== "TSPropertySignature") continue;
      const annotation = member.typeAnnotation?.typeAnnotation;
      if (
        annotation?.type === "TSFunctionType" ||
        (annotation?.type === "TSTypeReference" &&
          annotation.typeName.type === "Identifier" &&
          functionAliases.has(annotation.typeName.name))
      )
        callables.add(name);
    }
  }

  function expandInheritedSurfaces(): boolean {
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
    return changed;
  }

  for (let pass = 0; pass <= interfaces.size; pass += 1) {
    const changed = expandInheritedSurfaces();
    if (!changed) break;
  }
  return interfaces;
}

function hasServicePort(
  node: ESTree.Class,
  methods: readonly string[],
  classes: ReadonlyMap<string, boolean>,
  interfaces: ReadonlyMap<string, ReadonlySet<string>>,
): boolean {
  if (node.superClass !== null) {
    if (node.superClass.type !== "Identifier") return true;
    const localAbstract = classes.get(node.superClass.name);
    if (localAbstract === undefined || localAbstract) return true;
  }
  if ((node.implements?.length ?? 0) === 0) return false;
  return implementedSurfaceCovers(node, methods, classes, interfaces);
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
    const { filename, text } = sourceOrigin(context);
    if (isTestFile(filename) || isStoryFile(filename) || isScriptFile(filename))
      return {};
    if (isGeneratedFile(filename, text)) return {};

    // One pass over the module's top level, and only for a file that actually
    // has an options-object constructor to read.
    let declaredTypes: FileTypeIndex | null = null;
    const detachedExports = detachedValueExports(context.sourceCode.ast);
    const localClasses = localClassAbstractness(context.sourceCode.ast);
    const localInterfaces = localInterfaceSurfaces(context.sourceCode.ast);
    const objectTypes = (): FileTypeIndex =>
      (declaredTypes ??= fileTypeIndex(context.sourceCode.ast));
    return {
      ClassDeclaration(node: ESTree.Class): void {
        if (node.id === null) return;
        if (!isExportedClass(node, detachedExports)) return;
        if (ERROR_VALUE_NAME_RE.test(node.id.name)) return;
        // The port itself must never fire.
        if (node.abstract === true) return;
        if (node.decorators.length > 0) return;

        const ctor = node.body.body.find(
          (member): member is ESTree.MethodDefinition =>
            member.type === "MethodDefinition" &&
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
        const collaborators = constructorFacts.collaborators.filter(
          (collaborator) =>
            collaborator.fields.some((field) => invoked.has(field)),
        );
        if (collaborators.length === 0) return;
        if (constructorFacts.constructedFields > collaborators.length) return;
        // HTTP wiring: a router factory is mounted by the bootstrap, not injected.
        if (isFrameworkWiring(node.body)) return;
        // A lone third-party transport is not a seam a port could protect.
        if (
          isTransportWrapper(
            node.id.name,
            collaborators,
            context.sourceCode.ast,
          )
        )
          return;
        if (
          isFluentConstructionObject(node, (result) =>
            context.sourceCode.getText(result),
          )
        )
          return;

        const methods = publicMethodNames(
          node.body,
          objectTypes().functionAliases,
        );
        if (methods.length === 0) return;
        if (hasServicePort(node, methods, localClasses, localInterfaces))
          return;

        context.report({
          node: node.id,
          messageId: "requireInterface",
          data: {
            name: node.id.name,
            deps: collaborators
              .map((c) => `${c.name}: ${c.display}`)
              .join(", "),
            methods: methods.join(", "),
          },
        });
      },
    };
  },
});

function implementedSurfaceCovers(
  node: ESTree.Class,
  methods: readonly string[],
  classes: ReadonlyMap<string, boolean>,
  interfaces: ReadonlyMap<string, ReadonlySet<string>>,
): boolean {
  const combined = new Set<string>();
  for (const implementation of node.implements ?? []) {
    if (implementation.expression.type !== "Identifier") return true;
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

/** Shared, provenance-based evidence for the strict declared-contract rule. */
export function createServiceOperationResolver(
  program: ESTree.Program,
): (node: ESTree.Class) => readonly string[] {
  let declaredTypes: FileTypeIndex | null = null;
  return (node): readonly string[] => {
    const ctor = node.body.body.find(
      (member): member is ESTree.MethodDefinition =>
        member.type === "MethodDefinition" &&
        member.kind === "constructor" &&
        member.value.body !== null,
    );
    if (ctor === undefined) return [];
    const declared = (): FileTypeIndex =>
      (declaredTypes ??= fileTypeIndex(program));
    const facts = readConstructor(
      ctor,
      declared,
      typeParameterNames(node.typeParameters, ctor.value.typeParameters),
    );
    const retained = new Set(
      facts.collaborators.flatMap((collaborator) => collaborator.fields),
    );
    if (retained.size === 0) return [];

    const callers = new Map<string, Set<string>>();
    const active = new Set<string>();
    for (const [name, body] of serviceOperationBodies(node)) {
      forEachServiceCall(body, (call) => {
        if (retained.has(invokedInstanceField(call) ?? "")) active.add(name);
        if (
          call.callee.type === "MemberExpression" &&
          call.callee.object.type === "ThisExpression"
        ) {
          const callee = staticMemberName(call.callee);
          if (callee !== null) {
            const linked = callers.get(callee) ?? new Set<string>();
            linked.add(name);
            callers.set(callee, linked);
          }
        }
      });
    }
    const pending = [...active];
    while (pending.length > 0) {
      const callee = pending.pop();
      if (callee === undefined) break;
      for (const caller of callers.get(callee) ?? []) {
        if (active.has(caller)) continue;
        active.add(caller);
        pending.push(caller);
      }
    }
    return publicMethodNames(node.body, declared().functionAliases).filter(
      (name) => active.has(name),
    );
  };
}

/** Method and function-property bodies, excluding static or rewritten operations. */
function serviceOperationBodies(
  node: ESTree.Class,
): ReadonlyMap<string, ESTree.Node> {
  const bodies = new Map<string, ESTree.Node>();
  for (const member of node.body.body) {
    if (
      member.type !== "MethodDefinition" &&
      member.type !== "PropertyDefinition"
    )
      continue;
    if (member.static || member.decorators.length > 0) continue;
    if (member.type === "MethodDefinition" && member.kind !== "method")
      continue;
    if (
      member.value?.type !== "FunctionExpression" &&
      member.value?.type !== "ArrowFunctionExpression"
    )
      continue;
    const name = declaredMemberName(member);
    if (name !== null && member.value.body !== null)
      bodies.set(name, member.value.body);
  }
  return bodies;
}

/** Calls in the operation itself, without assuming nested callbacks execute. */
function forEachServiceCall(
  node: ESTree.Node,
  onCall: (call: ESTree.CallExpression) => void,
): void {
  if (
    node.type === "FunctionDeclaration" ||
    node.type === "FunctionExpression" ||
    node.type === "ArrowFunctionExpression" ||
    node.type === "ClassDeclaration" ||
    node.type === "ClassExpression"
  )
    return;
  if (node.type === "BlockStatement") {
    for (const statement of node.body) {
      forEachServiceCall(statement, onCall);
      if (terminatesOperation(statement)) break;
    }
    return;
  }
  const branch = literalExecutionBranch(node);
  if (branch !== null) {
    forEachServiceCall(branch, onCall);
    return;
  }
  if (node.type === "CallExpression") onCall(node);
  forEachOwnAstChild(node, (child) => {
    forEachServiceCall(child, onCall);
  });
}

/** Boolean literals select a branch without guessing at arbitrary expressions. */
function literalExecutionBranch(node: ESTree.Node): ESTree.Node | null {
  if (
    node.type === "WhileStatement" &&
    node.test.type === "Literal" &&
    node.test.value === false
  )
    return node.test;
  if (
    (node.type === "IfStatement" || node.type === "ConditionalExpression") &&
    node.test.type === "Literal" &&
    typeof node.test.value === "boolean"
  ) {
    return node.test.value ? node.consequent : (node.alternate ?? node.test);
  }
  if (
    node.type !== "LogicalExpression" ||
    node.left.type !== "Literal" ||
    typeof node.left.value !== "boolean"
  )
    return null;
  if (node.operator === "&&") return node.left.value ? node.right : node.left;
  if (node.operator === "||") return node.left.value ? node.left : node.right;
  return node.left;
}

/** Only unconditional exits and selected literal branches stop the operation. */
function terminatesOperation(node: ESTree.Node): boolean {
  if (node.type === "ReturnStatement" || node.type === "ThrowStatement")
    return true;
  if (node.type === "BlockStatement")
    return node.body.some(terminatesOperation);
  if (node.type !== "IfStatement") return false;
  const branch = literalExecutionBranch(node);
  if (branch !== null) return terminatesOperation(branch);
  return (
    node.alternate !== null &&
    terminatesOperation(node.consequent) &&
    terminatesOperation(node.alternate)
  );
}

/** `null` means a declared contract cannot be resolved by this syntax-only pass. */
export function hasDeclaredServiceContract(
  node: ESTree.Class,
  operations: readonly string[],
  program: ESTree.Program,
): boolean | null {
  const interfaces = localInterfaceSurfaces(program);
  const classes = localClassDeclarations(program);
  const functionAliases = fileTypeIndex(program).functionAliases;
  const covered = new Set<string>();
  const pending = [node];
  const seen = new Set<ESTree.Class>();

  function addImplementedContracts(current: ESTree.Class): boolean {
    for (const implementation of current.implements ?? []) {
      if (implementation.expression.type !== "Identifier") return false;
      const name = implementation.expression.name;
      const surface = interfaces.get(name);
      const base = classes.get(name);
      if (surface === undefined && base === undefined) return false;
      if (surface?.has("*")) return false;
      for (const method of surface ?? []) covered.add(method);
      if (base?.abstract) pending.push(base);
    }
    return true;
  }

  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined || seen.has(current)) continue;
    seen.add(current);
    if (current.decorators.length > 0) return null;
    if (current.abstract) {
      for (const method of abstractContractOperations(current, functionAliases))
        covered.add(method);
    }
    if (!addImplementedContracts(current)) return null;
    if (current.superClass === null) continue;
    if (current.superClass.type !== "Identifier") return null;
    const base = classes.get(current.superClass.name);
    if (base === undefined) return null;
    pending.push(base);
  }
  return operations.every((name) => covered.has(name));
}

/** Declared classes preserve their own abstract status and explicit ancestry. */
function localClassDeclarations(
  program: ESTree.Program,
): ReadonlyMap<string, ESTree.Class> {
  const classes = new Map<string, ESTree.Class>();
  for (const statement of program.body) {
    const declaration =
      statement.type === "ExportNamedDeclaration" ||
      statement.type === "ExportDefaultDeclaration"
        ? statement.declaration
        : statement;
    if (declaration?.type === "ClassDeclaration" && declaration.id !== null)
      classes.set(declaration.id.name, declaration);
  }
  return classes;
}

/** Public concrete and abstract callable members of an abstract contract. */
function abstractContractOperations(
  node: ESTree.Class,
  functionAliases: ReadonlySet<string>,
): ReadonlySet<string> {
  const methods = new Set(publicMethodNames(node.body, functionAliases));
  for (const member of node.body.body) {
    if (
      member.type !== "TSAbstractMethodDefinition" &&
      member.type !== "TSAbstractPropertyDefinition"
    )
      continue;
    if (
      member.static ||
      member.accessibility === "private" ||
      member.accessibility === "protected"
    )
      continue;
    if (member.type === "TSAbstractPropertyDefinition") {
      const annotation = member.typeAnnotation?.typeAnnotation;
      if (
        annotation?.type !== "TSFunctionType" &&
        !(
          annotation?.type === "TSTypeReference" &&
          annotation.typeName.type === "Identifier" &&
          functionAliases.has(annotation.typeName.name)
        )
      )
        continue;
    }
    const name = declaredMemberName(member);
    if (name !== null) methods.add(name);
  }
  return methods;
}
