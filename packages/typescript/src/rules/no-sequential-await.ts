/**
 * @fileoverview Disallow `await` expressions located directly inside the body
 * of a `for` / `for-of` / `for-in` / `while` loop (or an async `.forEach` /
 * `.map` / `.filter` callback) within the same function scope. Awaiting serially
 * inside a loop serializes I/O that is often better expressed as
 * `await Promise.all(xs.map(async (x) => ...))`, letting the operations run
 * concurrently.
 *
 * This rule is intentionally conservative — it prefers a false negative over a
 * false positive:
 *   - `for await...of` is NOT flagged (async iteration is the correct tool).
 *   - awaits inside a function/arrow defined within the loop are NOT flagged
 *     (they belong to a different function scope).
 *   - awaits not inside any loop are NOT flagged.
 *
 * Real-world sweeps (VS Code, NestJS, Next.js) surfaced whole classes of loops
 * where serial awaits are REQUIRED and `Promise.all` would change semantics.
 * Those are suppressed here:
 *   (a) the loop short-circuits or retries — its body (this scope) contains a
 *       `return` / `break` / `continue`;
 *   (b) the awaited value threads through the iteration — `x = await f(x)`,
 *       `content = await p(content)` (the assignment target is read inside the
 *       awaited expression);
 *   (c) the await is a timer yield — `await new Promise((r) => setTimeout(r))`;
 *   (d) the iterable's name/derivation signals ordering — `*Sorted*`,
 *       `.reverse()`, lifecycle `hooks`, pipeline `stages`, etc.
 *   (e) a `while` / `do-while` whose CONTINUATION depends on state the body
 *       computes — cursor pagination:
 *       `do { const page = await list(cursor); cursor = page.nextCursor } while (cursor)`.
 *       The next request's input is the previous response's output, so the
 *       iteration count is unknowable up front and there is nothing to collect
 *       into a `Promise.all`. Guard (b) misses this because the cursor is
 *       assigned from a property of the awaited value, not from the await
 *       itself; guard (a) misses it because the `while` test IS the exit.
 *       Deliberately narrow: only a plain `=` assignment to a test-read
 *       variable counts, so a hand-rolled counter loop (`while (i < n) { i++;
 *       await g(i) }`) still fires.
 * The genuinely parallelizable shape — independent awaits whose results are
 * collected or discarded without a cross-iteration dependency or early exit —
 * still fires.
 *
 * At most one report is emitted per offending loop / callback.
 *
 * CORPUS SWEEP (2220 files across zod / TanStack Query / react-router / swr /
 * zustand, 2026-07): 64 raw hits. Three further suppressions came out of it:
 *
 *   (f) TEST AND BENCHMARK FILES — 45 hits. A loop in a test is a table-driven
 *       case sweep or a teardown, and its iterations share one global fixture,
 *       so serial IS the contract.
 *       `react-router/packages/react-router/__tests__/dom/special-characters-test.tsx:312`
 *       (`for (let charDef of specialChars) { await testParamValues(...) }`, 10
 *       hits in that file alone) mounts and unmounts a React tree into the same
 *       JSDOM container per case; `Promise.all` would interleave them into one
 *       container and the suite would simply be wrong. Teardown has the same
 *       shape —
 *       `react-router/packages/create-react-router/__tests__/create-react-router-test.ts:77`
 *       (`for (let dir of tempDirs) await rm(dir, ...)`). A BENCHMARK is the
 *       purest case: `zod/packages/bench/object-async.ts:6`
 *       (`for (const _ of DATA) await zod3.parseAsync(_)`) exists precisely to
 *       measure one operation at a time; concurrency would destroy the number
 *       it is trying to produce.
 *   (g) `await Promise.resolve()` / `await Promise.reject()` — a microtask
 *       flush used to let queued work settle, the microtask twin of the
 *       `await new Promise(setTimeout)` already covered by (c). There is no I/O
 *       to parallelize. `query/packages/lit-query/src/tests/infinite-and-options.test.ts:207`
 *       (`for (let i = 0; i < 5; i += 1) { host.update(); await Promise.resolve() }`).
 *   (h) `preset` / `plugin` / `extension` added to the ordered-iterable hints —
 *       a preset or plugin list is a lifecycle chain exactly like the `hook` and
 *       `middleware` entries already there, and each entry may observe what the
 *       previous one wrote. `react-router/packages/react-router-dev/config/config.ts:776`
 *       (`for (let preset of reactRouterUserConfig.presets ?? []) await
 *       preset.reactRouterConfigResolved?.({ reactRouterConfig })`) threads one
 *       mutable `reactRouterConfig` through every preset in order.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";

type MessageIds = "noSequentialAwait";
type Options = readonly [];

/**
 * Array iteration methods whose async callback with an `await` inside is the
 * classic serial-await footgun (`.forEach` ignores the returned promise
 * entirely; a discarded `.map` / `.filter` floats its promises).
 */
const ARRAY_ITERATION_METHODS = new Set<string>(["forEach", "map", "filter"]);

/**
 * Text on the iterable (its identifier name or derivation) that signals an
 * ORDERED sequence whose elements must be processed one-after-another —
 * lifecycle hooks, sorted / reversed lists, pipeline stages. Awaiting serially
 * over such a sequence is the contract, so the report is suppressed. Broad by
 * design: the rule prefers a false negative to a false positive.
 */
const SEQUENTIAL_ITERABLE_HINT =
  /sort|reverse|ordered|sequence|hook|middleware|pipeline|preset|plugin|extension|\bstage|\bstep|\bphase|migration|chain|buffer|stream|teleport|chunk|\bqueue|drain/i;

/**
 * Guard (f): a benchmark file. A benchmark loop measures ONE operation at a
 * time; running the iterations concurrently would destroy the measurement, so
 * the serial await is the entire point.
 */
const BENCH_FILE_RE = /(^|[\\/])bench(marks?)?[\\/]|\.bench\.[cm]?[jt]sx?$/i;

/**
 * Node types that introduce a new function scope. We never descend across one
 * of these when looking for awaits belonging to a loop, because an `await`
 * inside a nested function/arrow is awaited by *that* function, not by the loop.
 */
function isFunctionLike(node: TSESTree.Node): boolean {
  return (
    node.type === "FunctionDeclaration" ||
    node.type === "FunctionExpression" ||
    node.type === "ArrowFunctionExpression"
  );
}

type LoopNode =
  | TSESTree.ForStatement
  | TSESTree.ForOfStatement
  | TSESTree.ForInStatement
  | TSESTree.WhileStatement
  | TSESTree.DoWhileStatement;

/**
 * Statement node types that introduce a nested loop. When scanning a loop's
 * body we must NOT descend into another loop — that inner loop's awaits belong
 * to it and are reported when the inner loop is visited. This keeps reporting
 * at one-per-loop and avoids double-flagging an outer loop for an await that
 * only appears inside a nested loop.
 */
function isLoop(node: TSESTree.Node): boolean {
  return (
    node.type === "ForStatement" ||
    node.type === "ForOfStatement" ||
    node.type === "ForInStatement" ||
    node.type === "WhileStatement" ||
    node.type === "DoWhileStatement"
  );
}

function isNode(value: unknown): value is TSESTree.Node {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

/**
 * Visits `root` and its descendants, calling `visit` on each, without crossing
 * into a nested function scope or descending into a nested loop — the same
 * ownership boundaries the rule uses to decide which awaits belong to a loop.
 */
function visitScope(
  root: TSESTree.Node,
  visit: (node: TSESTree.Node) => void,
): void {
  visit(root);
  for (const key of Object.keys(root) as (keyof TSESTree.Node)[]) {
    if (key === "parent") {
      continue;
    }
    const value = root[key];
    const children = Array.isArray(value) ? value : [value];
    for (const child of children) {
      if (isNode(child) && !isFunctionLike(child) && !isLoop(child)) {
        visitScope(child, visit);
      }
    }
  }
}

function collectAwaits(root: TSESTree.Node): TSESTree.AwaitExpression[] {
  const awaits: TSESTree.AwaitExpression[] = [];
  visitScope(root, (node) => {
    if (node.type === "AwaitExpression") {
      awaits.push(node);
    }
  });
  return awaits;
}

/**
 * Guard (i): the loop body ASSERTS. A loop containing `expect(...)` (or
 * `assert(...)`) is sweeping a table of cases, and its iterations share one
 * fixture — a browser page, a rendered tree, a temp directory. Running them
 * concurrently interleaves the assertions so a failure names the wrong case,
 * and for a single-page driver it is not even possible.
 *
 * This is the syntactic form of guard (f): react-router spells its suites
 * `integration/vite-css-test.ts`, which no path predicate matching `*.test.ts`
 * can see. Corpus evidence (2026-07): 17 of the 31 hits surviving guard (f) were
 * exactly this — `react-router/integration/vite-server-bundles-test.ts:282`
 * (`for (let path of _404s) { let response = await page.goto(...);
 * expect(response?.status()).toBe(404) }`, one Playwright page that cannot
 * navigate to two URLs at once) and
 * `react-router/integration/sri-test.ts:121`.
 */
const ASSERTION_CALLEE_RE = /^(expect|assert|should|invariant)$/;

/**
 * Guard (a): the scope contains a `return` / `break` / `continue`, marking a
 * retry / short-circuit / early-exit loop whose serial awaits are intentional.
 */
function hasEarlyExit(root: TSESTree.Node): boolean {
  let found = false;
  visitScope(root, (node) => {
    if (
      node.type === "ReturnStatement" ||
      node.type === "BreakStatement" ||
      node.type === "ContinueStatement"
    ) {
      found = true;
    }
  });
  return found;
}

/**
 * Guard (c): `await new Promise(...)` — a deliberate event-loop / timer yield,
 * not parallelizable I/O.
 */
const TIMER_HELPER_RE = /^(sleep|timeout|delay|wait|pause|tick)$/i;

function calleeName(callee: TSESTree.Node): string | null {
  if (callee.type === "Identifier") return callee.name;
  if (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.property.type === "Identifier"
  ) {
    return callee.property.name;
  }
  return null;
}

function isTimerYield(node: TSESTree.AwaitExpression): boolean {
  const arg = node.argument;
  // `await new Promise((r) => setTimeout(r))` — the canonical event-loop yield.
  if (
    arg.type === "NewExpression" &&
    arg.callee.type === "Identifier" &&
    arg.callee.name === "Promise"
  ) {
    return true;
  }
  // `await sleep(ms)` / `await delay()` / `await this.wait()` — a poll/throttle
  // yield in a `while` loop, deliberately serial.
  if (arg.type === "CallExpression") {
    // Guard (g): `await Promise.resolve()` / `await Promise.reject()` is a
    // microtask flush — the microtask twin of the `new Promise(setTimeout)`
    // yield above. There is no I/O in it to run concurrently.
    if (
      arg.callee.type === "MemberExpression" &&
      !arg.callee.computed &&
      arg.callee.object.type === "Identifier" &&
      arg.callee.object.name === "Promise" &&
      arg.callee.property.type === "Identifier" &&
      (arg.callee.property.name === "resolve" ||
        arg.callee.property.name === "reject")
    ) {
      return true;
    }
    const name = calleeName(arg.callee);
    return name !== null && TIMER_HELPER_RE.test(name);
  }
  return false;
}

const QUEUE_DRAIN_METHODS = /^(shift|pop|dequeue|next|poll)$/;

/**
 * Guard: `await queue.shift()` / `await this.stack.pop()` — draining a mutable
 * receiver one element at a time. Each call consumes the shared queue, so the
 * iterations are order-dependent and cannot be parallelized.
 */
function isQueueDrain(node: TSESTree.AwaitExpression): boolean {
  const arg = node.argument;
  return (
    arg.type === "CallExpression" &&
    arg.callee.type === "MemberExpression" &&
    !arg.callee.computed &&
    arg.callee.property.type === "Identifier" &&
    QUEUE_DRAIN_METHODS.test(arg.callee.property.name)
  );
}

/** Guard (i): does this scope contain an assertion call? */
function hasAssertion(root: TSESTree.Node): boolean {
  let found = false;
  visitScope(root, (node) => {
    if (node.type !== "CallExpression") {
      return;
    }
    let callee: TSESTree.Node = node.callee;
    // Unwrap `expect(x).resolves`, `assert.ok`, `chai.expect` — the base name.
    while (callee.type === "MemberExpression") {
      callee = callee.object;
    }
    if (callee.type === "CallExpression") {
      callee = callee.callee;
    }
    if (callee.type === "Identifier" && ASSERTION_CALLEE_RE.test(callee.name)) {
      found = true;
    }
  });
  return found;
}

function referencesName(root: TSESTree.Node, name: string): boolean {
  let found = false;
  visitScope(root, (node) => {
    if (node.type === "Identifier" && node.name === name) {
      found = true;
    }
  });
  return found;
}

/**
 * Guard (b): the awaited value is threaded into the next iteration — the await
 * is the RHS of `target = await ...` / `const target = await ...` and `target`
 * is read inside the awaited expression (`x = await f(x)`,
 * `content = await p(content)`). Parallelizing would break the data dependency.
 */
function isThreadedAccumulator(node: TSESTree.AwaitExpression): boolean {
  const parent = node.parent;
  let target: string | null = null;
  if (
    parent.type === "AssignmentExpression" &&
    parent.operator === "=" &&
    parent.right === node &&
    parent.left.type === "Identifier"
  ) {
    target = parent.left.name;
  } else if (
    parent.type === "VariableDeclarator" &&
    parent.init === node &&
    parent.id.type === "Identifier"
  ) {
    target = parent.id.name;
  }
  if (target === null) {
    return false;
  }
  return referencesName(node.argument, target);
}

/** Every identifier name read by a loop's test expression. */
function namesReadBy(test: TSESTree.Node): Set<string> {
  const names = new Set<string>();
  visitScope(test, (node) => {
    if (node.type === "Identifier") {
      names.add(node.name);
    }
  });
  return names;
}

/**
 * Guard (e): a `while` / `do-while` whose continuation condition is recomputed
 * by its own body — the cursor-pagination shape. True when the body plainly
 * assigns (`=`) to a variable the test reads. `++` / `+=` are excluded so a
 * hand-rolled counter loop, which IS parallelizable, keeps firing.
 */
function testStateIsAssignedInBody(
  test: TSESTree.Node,
  body: TSESTree.Node,
): boolean {
  const testNames = namesReadBy(test);
  if (testNames.size === 0) {
    return false;
  }
  let found = false;
  visitScope(body, (node) => {
    if (
      node.type === "AssignmentExpression" &&
      node.operator === "=" &&
      node.left.type === "Identifier" &&
      testNames.has(node.left.name)
    ) {
      found = true;
    }
  });
  return found;
}

/**
 * Decides whether a set of awaits owned by a loop/callback is worth reporting.
 * Suppressed when the loop short-circuits (a) or iterates an ordered sequence
 * (d); otherwise reported if AT LEAST ONE await is genuinely parallelizable —
 * i.e. not a timer yield (c) and not a threaded accumulator (b).
 */
function shouldReport(
  awaits: readonly TSESTree.AwaitExpression[],
  earlyExit: boolean,
  iterableText: string | null,
  asserts = false,
): boolean {
  if (awaits.length === 0) {
    return false;
  }
  if (earlyExit) {
    return false;
  }
  if (asserts) {
    return false;
  }
  if (iterableText !== null && SEQUENTIAL_ITERABLE_HINT.test(iterableText)) {
    return false;
  }
  return awaits.some(
    (node) =>
      !isTimerYield(node) &&
      !isThreadedAccumulator(node) &&
      !isQueueDrain(node),
  );
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-sequential-await",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow serial `await` inside a loop; use `await Promise.all(...)` to run the operations concurrently.",
    },
    schema: [],
    messages: {
      noSequentialAwait:
        "Avoid `await` inside a loop — it serializes I/O. Collect the promises and `await Promise.all(xs.map(async (x) => ...))` instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    // Guard (f): fixtures and benchmarks serialize on purpose — see @fileoverview.
    if (isTestFile(context.filename) || BENCH_FILE_RE.test(context.filename)) {
      return {};
    }

    /**
     * The parts of a loop where an await "belonging to this loop" can live: the
     * body, plus the C-style `for` init/test/update or the for-of/for-in
     * iterable or the while/do-while test. A part that is itself a nested loop
     * is owned by that loop and checked when it is visited.
     */
    function loopParts(node: LoopNode): (TSESTree.Node | null)[] {
      // Only parts that run PER ITERATION can serialize awaits. The C-`for`
      // init and the for-of/for-in iterable are evaluated ONCE, so an `await`
      // there (`for (const x of await Promise.allSettled(...))`) is a single
      // await, not a loop-serialized one — exclude them.
      if (node.type === "ForStatement") {
        return [node.body, node.test, node.update];
      }
      if (node.type === "ForOfStatement" || node.type === "ForInStatement") {
        return [node.body];
      }
      return [node.body, node.test];
    }

    function iterableTextOf(node: LoopNode): string | null {
      if (node.type === "ForOfStatement" || node.type === "ForInStatement") {
        return context.sourceCode.getText(node.right);
      }
      return null;
    }

    function checkLoop(node: LoopNode): void {
      if (
        (node.type === "WhileStatement" || node.type === "DoWhileStatement") &&
        testStateIsAssignedInBody(node.test, node.body)
      ) {
        return;
      }

      const awaits: TSESTree.AwaitExpression[] = [];
      let earlyExit = false;
      let asserts = false;
      for (const part of loopParts(node)) {
        if (part === null || isLoop(part)) {
          continue;
        }
        awaits.push(...collectAwaits(part));
        if (!earlyExit && hasEarlyExit(part)) {
          earlyExit = true;
        }
        if (!asserts && hasAssertion(part)) {
          asserts = true;
        }
      }
      if (shouldReport(awaits, earlyExit, iterableTextOf(node), asserts)) {
        context.report({ node, messageId: "noSequentialAwait" });
      }
    }

    return {
      ForStatement: checkLoop,
      ForInStatement: checkLoop,
      WhileStatement: checkLoop,
      DoWhileStatement: checkLoop,
      ForOfStatement(node: TSESTree.ForOfStatement): void {
        // `for await...of` is correct async iteration — never flag it.
        if (node.await) {
          return;
        }
        checkLoop(node);
      },
      CallExpression(node: TSESTree.CallExpression): void {
        const callee = node.callee;
        if (callee.type !== "MemberExpression" || callee.computed) {
          return;
        }
        if (
          callee.property.type !== "Identifier" ||
          !ARRAY_ITERATION_METHODS.has(callee.property.name)
        ) {
          return;
        }
        const callback = node.arguments[0];
        if (
          callback === undefined ||
          !isFunctionLike(callback) ||
          !("async" in callback && callback.async)
        ) {
          return;
        }
        // A discarded `.map` / `.filter` (statement position) floats its
        // promises just like `.forEach`; when its result is kept
        // (`Promise.all(...)`, an assignment, a `return`) the awaits are
        // consumed correctly, so only flag `.forEach` or a bare-statement call.
        if (
          callee.property.name !== "forEach" &&
          node.parent.type !== "ExpressionStatement"
        ) {
          return;
        }
        const awaits = collectAwaits(callback.body);
        const earlyExit = hasEarlyExit(callback.body);
        const iterableText = context.sourceCode.getText(callee.object);
        if (
          shouldReport(awaits, earlyExit, iterableText, hasAssertion(callback.body))
        ) {
          context.report({ node, messageId: "noSequentialAwait" });
        }
      },
    };
  },
});
