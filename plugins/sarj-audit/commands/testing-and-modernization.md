# Testing Strategy & Modernization Audit

Audit the test suite for fidelity and architectural quality, and evaluate the codebase for opportunities to replace complex, hand-rolled code with battle-tested third-party libraries or modern stdlib features.

> [!NOTE]
> This audit evaluates test design strategy and library adoption requiring high-level human/AI judgment.
> Deterministic AST test rules (such as `no_sleep_in_test_body`, `tautological_mock_assertion`, `zero_assertion_test`, `duplicate_test_body`, or `no_raw_sql_in_tests`) are enforced by `@sarj/eslint-plugin` and `sarj-python-lint`. Do **not** re-audit deterministic lint rules.

---

## What this audits

### 1. High-Fidelity Test Strategy & Architecture
- **Over-Mocking & Low-Fidelity Mocks**: Excessive reliance on `unittest.mock.MagicMock` or `AsyncMock` to fake complex components like data stores or HTTP clients, leading to tests that pass against invalid contracts or mask un-awaited coroutines and schema drift.
- **Test Double Selection Hierarchy**:
  1. **Tier 1 (Real Infrastructure in Container/Test DB)**: Use real DB fixtures (`testcontainers`, Postgres/SQLite test DBs) for repositories and queries — **mandatory for data access layers**.
  2. **Tier 2 (In-Memory Fakes)**: Use stateful, protocol-compliant in-memory implementations (`FakeUserStore`) for internal domain services.
  3. **Tier 3 (Network Interceptors)**: Use declarative network interceptors (`msw` for TS, `respx`/`responses` for Python) for external API testing rather than patching client methods.
  4. **Tier 4 (Spec'd Mocks)**: Reserve `Mock(spec=...)` strictly for pure leaf dependencies.
- **Testing Private Implementation Details**: Tests binding to private methods (`_private_func`, `._internal_state`), patching internal helpers via `@patch('app.service._helper')`, or asserting internal call counts (`assert_called_once_with`) rather than asserting observable outputs on public interfaces.

### 2. Third-Party Library Adoption & Codebase Modernization
- **Hand-Rolled Infrastructure Logic**: Custom implementations of complex concurrency patterns (semaphores, batching, rate-limiting, retry with exponential backoff) that should be replaced by mature packages (`p-limit`, `p-retry`, `tenacity`) or modern stdlib features (`asyncio.TaskGroup` in Python 3.11+).
- **Hand-Rolled Domain & Parsing Logic**: Hand-rolled date/time calculations, CSV parsing, URL manipulation, binary encoding, or crypto operations that introduce edge-case bugs and should use battle-tested libraries (`date-fns`, `papaparse`, `validator`, `nanoid`, or Python 3.11+ `tomllib`).
- **Library Safety Checklist**: Verify that any proposed library: (1) is NOT already covered by standard library features, (2) is compatible with target runtimes (Node, Edge, Browser, Python), and (3) reduces overall code volume by 50%+ without adding excessive bundle size.

---

## Phase 0: Discover project structure

Run the shared **[stack-detection](./stack-detection.md)** pass first.

Inventory existing dependencies (`package.json`, `pyproject.toml`), test runners (`vitest`, `pytest`), and test double packages (`testcontainers`, `respx`, `msw`, `freezegun`) to avoid recommending libraries already in use or incompatible with target runtimes.

---

## Phase 1: Audit (parallel agents)

Spawn 2 parallel audit agents:

### Agent 1: Test Strategy & Fidelity Audit
- **Grep & Search Vectors**: Search test files for `AsyncMock()`, `MagicMock()`, `@patch(`, `vi.spyOn`, `jest.spyOn`, and private method calls (`._`).
- Audit test suites for `AsyncMock`/`MagicMock` over-use on data stores and complex domain services.
- Identify tests asserting on private/internal class methods (`._private`) instead of public contract outputs.
- Evaluate test double selection against the 4-tier hierarchy (promote store mocks to real DB fixtures / fakes).

### Agent 2: Library Adoption & Modernization Audit
- **Grep & Search Vectors**: Search application files for custom `setTimeout`/`sleep` retry loops, hand-rolled batching, string splitting for URLs/query params, custom date math, and manual CSV parsers.
- Check stdlib availability first (Python 3.11+ `asyncio.TaskGroup`, `tomllib`, Web Crypto API).
- Search for hand-rolled async concurrency control (batching, throttling, retries).
- Estimate line reduction and verify runtime compatibility for proposed package replacements.

---

## Phase 2: Compile findings

Deduplicate findings across agents and compile a single summary table:

| Focus Area | File & Lines | Current Approach | Recommendation | Impact | Line / Maintenance Reduction |
|------------|--------------|------------------|----------------|--------|------------------------------|

Sort by impact (**High** > **Medium** > **Low**), then by file path.

Group into:
- **High Impact**: Replacing brittle mocks on core data stores with real DB fixtures / in-memory fakes; replacing fragile custom retry/concurrency code with standard libraries or `TaskGroup`.
- **Medium Impact**: Refactoring tests from private implementation details to public contract assertions; adopting standard packages or network interceptors (`msw`/`respx`).
- **Low Impact / Future**: Minor utility library consolidations.

---

## Phase 3: Generate recommendations & refactoring plan

For each High and Medium finding:
1. Provide a concrete example of replacing low-fidelity `AsyncMock` with a real store fixture or fake.
2. Show before-and-after snippets for hand-rolled logic vs library adoption, noting line count savings, stdlib applicability, and bundle/runtime impact.

Do NOT automatically apply changes. Present recommendations for review.
